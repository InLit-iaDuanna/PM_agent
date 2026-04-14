import json
import logging
import os
import shutil
import threading
import tempfile
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Dict, Iterator, List, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix runtimes
    fcntl = None


LOGGER = logging.getLogger(__name__)

MARKET_STEP_LABELS = {
    "research-definition": "研究定义",
    "market-definition": "市场定义与分层",
    "market-trends": "市场规模与趋势",
    "user-research": "用户研究",
    "competitor-analysis": "竞争产品分析",
    "experience-teardown": "体验拆解",
    "reviews-and-sentiment": "评论与舆情分析",
    "business-and-channels": "商业与渠道研究",
    "opportunities-and-risks": "机会与风险评估",
    "recommendations": "建议与待验证假设",
    "validation": "验证",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_runtime_config_root() -> Path:
    configured_config_dir = os.getenv("PM_AGENT_CONFIG_DIR", "").strip()
    if configured_config_dir:
        return Path(configured_config_dir).expanduser()

    xdg_config_home = os.getenv("XDG_CONFIG_HOME", "").strip()
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "pm-agent"

    return Path.home() / ".config" / "pm-agent"


class InMemoryStateRepository:
    STREAM_CLOSED_EVENT = "__stream.closed__"
    ACTIVE_JOB_STATUSES = {"queued", "planning", "researching", "verifying", "synthesizing"}
    MAX_PERSISTED_JOB_EVENTS = max(50, int(os.getenv("PM_AGENT_MAX_JOB_EVENTS", "500") or "500"))
    REQUIRED_JOB_FIELDS = {
        "topic",
        "industry_template",
        "research_mode",
        "depth_preset",
        "status",
        "overall_progress",
        "current_phase",
        "eta_seconds",
        "completed_task_count",
        "running_task_count",
        "failed_task_count",
        "phase_progress",
    }

    def __init__(
        self,
        *,
        state_root: Optional[Path | str] = None,
        runtime_config_path: Optional[Path | str] = None,
    ) -> None:
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.assets: Dict[str, Dict[str, Any]] = {}
        self.chat_sessions: Dict[str, Dict[str, Any]] = {}
        self.users: Dict[str, Dict[str, Any]] = {}
        self.auth_sessions: Dict[str, Dict[str, Any]] = {}
        self.invites: Dict[str, Dict[str, Any]] = {}
        self.auth_policy: Optional[Dict[str, Any]] = None
        self.runtime_config: Optional[Dict[str, Any]] = None
        self.runtime_configs: Dict[str, Dict[str, Any]] = {}
        self.job_queues: Dict[str, "Queue[Dict[str, Any]]"] = {}
        self.job_stream_subscribers: Dict[str, List["Queue[Dict[str, Any]]"]] = {}
        self.background_job_queue: "Queue[str]" = Queue()
        self._lock = threading.RLock()
        configured_state_root = os.getenv("PM_AGENT_STATE_DIR", "").strip()
        if state_root is not None:
            self._state_root = Path(state_root).expanduser()
        elif configured_state_root:
            self._state_root = Path(configured_state_root).expanduser()
        else:
            self._state_root = _repo_root() / "output" / "state"
        self._locks_dir = self._state_root / ".locks"
        self._jobs_dir = self._state_root / "jobs"
        self._assets_dir = self._state_root / "assets"
        self._chat_sessions_dir = self._state_root / "chat_sessions"
        self._users_dir = self._state_root / "users"
        self._auth_sessions_dir = self._state_root / "auth_sessions"
        self._invites_dir = self._state_root / "invites"
        self._auth_policy_path = self._state_root / "auth_policy.json"
        self._job_events_dir = self._state_root / "job_events"
        self._runtime_configs_dir = self._state_root / "runtime_configs"
        configured_runtime_config_path = os.getenv("PM_AGENT_RUNTIME_CONFIG_PATH", "").strip()
        if runtime_config_path is not None:
            self._runtime_config_path = Path(runtime_config_path).expanduser()
        elif configured_runtime_config_path:
            self._runtime_config_path = Path(configured_runtime_config_path).expanduser()
        elif configured_state_root:
            self._runtime_config_path = self._state_root / "runtime_config.json"
        else:
            self._runtime_config_path = _default_runtime_config_root() / "runtime_config.json"
        self._legacy_runtime_config_path = self._state_root / "runtime_config.json"
        for directory in (
            self._jobs_dir,
            self._assets_dir,
            self._chat_sessions_dir,
            self._users_dir,
            self._auth_sessions_dir,
            self._invites_dir,
            self._job_events_dir,
            self._runtime_configs_dir,
            self._runtime_config_path.parent,
            self._locks_dir / "jobs",
            self._locks_dir / "assets",
            self._locks_dir / "job_events",
            self._locks_dir / "chat_sessions",
            self._locks_dir / "runtime_configs",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_runtime_config()
        self._load_state()

    def _read_json(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except OSError as error:
            LOGGER.warning("Failed to read state file %s: %s", path, error)
            return None
        except (ValueError, TypeError) as error:
            LOGGER.warning("State file %s is invalid JSON and will be quarantined: %s", path, error)
            self._quarantine_invalid_json(path)
            return None

        if not isinstance(payload, dict):
            LOGGER.warning("State file %s does not contain a JSON object and will be quarantined.", path)
            self._quarantine_invalid_json(path)
            return None

        return payload

    def _write_json(self, path: Path, payload: Dict[str, Any], private: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            if private:
                os.chmod(temp_path, 0o600)
            os.replace(temp_path, path)
            if private:
                os.chmod(path, 0o600)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def _quarantine_invalid_json(self, path: Path) -> None:
        if not path.exists():
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        quarantine_path = path.with_name(f"{path.name}.corrupt-{timestamp}")
        try:
            os.replace(path, quarantine_path)
            LOGGER.warning("Moved invalid state file %s to %s", path, quarantine_path)
        except OSError as error:
            LOGGER.warning("Failed to quarantine invalid state file %s: %s", path, error)

    def _migrate_legacy_runtime_config(self) -> None:
        if self._runtime_config_path == self._legacy_runtime_config_path:
            return
        if self._runtime_config_path.exists() or not self._legacy_runtime_config_path.exists():
            return

        payload = self._read_json(self._legacy_runtime_config_path)
        if not payload:
            return

        self._write_json(self._runtime_config_path, payload, private=True)
        try:
            self._legacy_runtime_config_path.unlink()
        except OSError as error:
            LOGGER.warning(
                "Failed to remove legacy runtime config %s after migration: %s",
                self._legacy_runtime_config_path,
                error,
            )

    def _fallback_claim_text(self, claim: Dict[str, Any]) -> str:
        caveats = claim.get("caveats")
        if isinstance(caveats, list):
            for item in caveats:
                text = str(item or "").strip()
                if text:
                    return text
        elif isinstance(caveats, str) and caveats.strip():
            return caveats.strip()

        market_step = str(claim.get("market_step") or "").strip()
        if market_step:
            market_step_label = MARKET_STEP_LABELS.get(market_step, market_step.replace("-", " "))
            return f"{market_step_label}维度已有补充结论，但原始 claim_text 缺失，请结合关联证据复核。"
        return "这条结构化结论缺少正文，请结合关联证据复核。"

    def _sanitize_claim(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = deepcopy(claim)
        claim_text = sanitized.get("claim_text")
        if not isinstance(claim_text, str) or not claim_text.strip():
            sanitized["claim_text"] = self._fallback_claim_text(sanitized)

        caveats = sanitized.get("caveats")
        if isinstance(caveats, str):
            sanitized["caveats"] = [caveats] if caveats.strip() else []
        elif not isinstance(caveats, list):
            sanitized["caveats"] = []

        return sanitized

    def _sanitize_assets(self, assets: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = deepcopy(assets)
        claims = sanitized.get("claims")
        if isinstance(claims, list):
            sanitized["claims"] = [self._sanitize_claim(claim) if isinstance(claim, dict) else claim for claim in claims]
        report_versions = sanitized.get("report_versions")
        if isinstance(report_versions, list):
            sanitized["report_versions"] = [
                item
                for item in report_versions
                if isinstance(item, dict)
                and str(item.get("version_id") or "").strip()
                and str(item.get("markdown") or "").strip()
            ]
        else:
            sanitized["report_versions"] = []

        artifacts = sanitized.get("artifacts")
        sanitized["artifacts"] = artifacts if isinstance(artifacts, list) else []
        return sanitized

    def _job_path(self, job_id: str) -> Path:
        return self._jobs_dir / f"{job_id}.json"

    def _job_lock_path(self, job_id: str) -> Path:
        return self._locks_dir / "jobs" / f"{job_id}.lock"

    def _assets_path(self, job_id: str) -> Path:
        return self._assets_dir / f"{job_id}.json"

    def _assets_lock_path(self, job_id: str) -> Path:
        return self._locks_dir / "assets" / f"{job_id}.lock"

    def _chat_session_path(self, session_id: str) -> Path:
        return self._chat_sessions_dir / f"{session_id}.json"

    def _chat_session_lock_path(self, session_id: str) -> Path:
        return self._locks_dir / "chat_sessions" / f"{session_id}.lock"

    def _user_path(self, user_id: str) -> Path:
        return self._users_dir / f"{user_id}.json"

    def _auth_session_path(self, token_hash: str) -> Path:
        return self._auth_sessions_dir / f"{token_hash}.json"

    def _invite_path(self, invite_id: str) -> Path:
        return self._invites_dir / f"{invite_id}.json"

    def _runtime_config_lock_path(self) -> Path:
        return self._locks_dir / "runtime_config.lock"

    def _auth_policy_lock_path(self) -> Path:
        return self._locks_dir / "auth_policy.lock"

    def _runtime_config_path_for_user(self, user_id: str) -> Path:
        return self._runtime_configs_dir / f"{user_id}.json"

    def _runtime_config_lock_path_for_user(self, user_id: str) -> Path:
        return self._locks_dir / "runtime_configs" / f"{user_id}.lock"

    def _job_event_dir(self, job_id: str) -> Path:
        return self._job_events_dir / job_id

    def _job_events_lock_path(self, job_id: str) -> Path:
        return self._locks_dir / "job_events" / f"{job_id}.lock"

    def _job_event_cursor(self, job_id: str) -> Optional[str]:
        event_dir = self._job_event_dir(job_id)
        if not event_dir.exists():
            return None
        event_files = sorted(path.name for path in event_dir.glob("*.json"))
        return event_files[-1] if event_files else None

    def _job_event_payload_path(self, job_id: str, event_id: str) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return self._job_event_dir(job_id) / f"{timestamp}-{event_id}.json"

    def _touch_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        touched = self._reconcile_job_counters(job)
        now = self._timestamp_now()
        touched.setdefault("created_at", touched.get("updated_at") or now)
        touched["updated_at"] = now
        return touched

    @contextmanager
    def _file_lock(self, lock_path: Path) -> Iterator[None]:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _reconcile_job_counters(self, job: Dict[str, Any]) -> Dict[str, Any]:
        reconciled = deepcopy(job)
        tasks = reconciled.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            return reconciled

        try:
            current_source_count = max(0, int(reconciled.get("source_count", 0) or 0))
        except (TypeError, ValueError):
            current_source_count = 0
        task_source_count = 0
        for task in tasks:
            try:
                task_source_count += max(0, int((task or {}).get("source_count", 0) or 0))
            except (AttributeError, TypeError, ValueError):
                continue

        # If task-level sources are available, prefer their total to avoid stale inflated counters.
        if task_source_count > 0:
            reconciled["source_count"] = task_source_count
        else:
            reconciled["source_count"] = current_source_count

        reconciled["completed_task_count"] = sum(1 for task in tasks if (task or {}).get("status") == "completed")
        reconciled["running_task_count"] = sum(1 for task in tasks if (task or {}).get("status") == "running")
        reconciled["failed_task_count"] = sum(1 for task in tasks if (task or {}).get("status") == "failed")
        return reconciled

    def _touch_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        touched = deepcopy(session)
        now = self._timestamp_now()
        touched.setdefault("created_at", touched.get("updated_at") or now)
        touched["updated_at"] = now
        return touched

    def _timestamp_now(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def _process_cmdline(self, pid: int) -> str:
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if not cmdline_path.exists():
            return ""
        try:
            return cmdline_path.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="ignore")
        except OSError:
            return ""

    def _is_detached_worker_running(self, job: Dict[str, Any]) -> bool:
        background_process = job.get("background_process") or {}
        if not isinstance(background_process, dict) or not background_process.get("active"):
            return False

        try:
            pid = int(background_process.get("pid") or 0)
        except (TypeError, ValueError):
            return False
        if pid <= 0:
            return False

        try:
            os.kill(pid, 0)
        except OSError:
            return False

        cmdline = self._process_cmdline(pid)
        if not cmdline:
            return True

        job_id = str(job.get("id") or "").strip()
        return "pm_agent_api.worker_entry" in cmdline and job_id in cmdline

    def _recover_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        recovered = deepcopy(job)
        recovered.setdefault("activity_log", [])
        if recovered.get("status") in self.ACTIVE_JOB_STATUSES:
            if self._is_detached_worker_running(recovered):
                return recovered

            now = self._timestamp_now()
            recovery_message = "服务在任务执行中重启，且后台 worker 不再存活，这个任务已标记为失败。请基于当前结果继续查看，或重新发起新的研究任务。"
            recovered["status"] = "failed"
            recovered["completion_mode"] = "diagnostic"
            recovered["eta_seconds"] = 0
            recovered["running_task_count"] = 0
            recovered["latest_error"] = recovery_message
            recovered["latest_warning"] = None
            recovered["completed_at"] = now
            tasks = recovered.get("tasks")
            if isinstance(tasks, list):
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    if task.get("status") in {"queued", "running"}:
                        task["status"] = "failed"
                        task["current_action"] = "执行中断（服务恢复后判定失败）"
                recovered["failed_task_count"] = sum(1 for task in tasks if isinstance(task, dict) and task.get("status") == "failed")
            background_process = recovered.get("background_process") or {}
            if isinstance(background_process, dict):
                background_process["active"] = False
                background_process["finished_at"] = now
                recovered["background_process"] = background_process
            recovered["activity_log"].append(
                {
                    "id": f"{recovered['id']}-recovered",
                    "timestamp": now,
                    "level": "warning",
                    "message": recovery_message,
                }
            )
        return recovered

    def _is_valid_job(self, job: Dict[str, Any]) -> bool:
        return bool(job.get("id")) and self.REQUIRED_JOB_FIELDS.issubset(job.keys())

    def _load_state(self) -> None:
        with self._lock:
            for path in sorted(self._jobs_dir.glob("*.json")):
                payload = self._read_json(path)
                if payload and self._is_valid_job(payload):
                    recovered = self._recover_job(payload)
                    self.jobs[recovered["id"]] = recovered
                    self.job_queues.setdefault(recovered["id"], Queue())
                    self.job_stream_subscribers.setdefault(recovered["id"], [])
                    self._write_json(path, recovered)

            for path in sorted(self._assets_dir.glob("*.json")):
                payload = self._read_json(path)
                if payload and path.stem:
                    sanitized_assets = self._sanitize_assets(payload)
                    self.assets[path.stem] = sanitized_assets
                    if sanitized_assets != payload:
                        self._write_json(path, sanitized_assets)

            self._refresh_chat_sessions_from_disk()
            self._refresh_users_from_disk()
            self._refresh_auth_sessions_from_disk()
            self._refresh_invites_from_disk()
            self._refresh_auth_policy_from_disk()
            self._refresh_runtime_config_from_disk()

    def _refresh_job_from_disk(self, job_id: str) -> None:
        with self._file_lock(self._job_lock_path(job_id)):
            payload = self._read_json(self._job_path(job_id))
            if payload and self._is_valid_job(payload):
                recovered = self._recover_job(payload)
                self.jobs[recovered["id"]] = recovered
                self.job_queues.setdefault(recovered["id"], Queue())
                self.job_stream_subscribers.setdefault(recovered["id"], [])
                if recovered != payload:
                    self._write_json(self._job_path(job_id), recovered)

    def _refresh_jobs_from_disk(self) -> None:
        for path in sorted(self._jobs_dir.glob("*.json")):
            self._refresh_job_from_disk(path.stem)

    def _refresh_assets_from_disk(self, job_id: str) -> None:
        with self._file_lock(self._assets_lock_path(job_id)):
            payload = self._read_json(self._assets_path(job_id))
            if payload:
                sanitized = self._sanitize_assets(payload)
                self.assets[job_id] = sanitized
                if sanitized != payload:
                    self._write_json(self._assets_path(job_id), sanitized)

    def _refresh_chat_session_from_disk(self, session_id: str) -> None:
        payload = self._read_json(self._chat_session_path(session_id))
        if payload and payload.get("id"):
            self.chat_sessions[str(payload["id"])] = payload
            return
        self.chat_sessions.pop(session_id, None)

    def _refresh_chat_sessions_from_disk(self) -> None:
        refreshed: Dict[str, Dict[str, Any]] = {}
        for path in sorted(self._chat_sessions_dir.glob("*.json")):
            payload = self._read_json(path)
            if payload and payload.get("id"):
                refreshed[str(payload["id"])] = payload
        self.chat_sessions = refreshed

    def _refresh_user_from_disk(self, user_id: str) -> None:
        payload = self._read_json(self._user_path(user_id))
        if payload and payload.get("id"):
            self.users[str(payload["id"])] = payload
            return
        self.users.pop(user_id, None)

    def _refresh_users_from_disk(self) -> None:
        refreshed: Dict[str, Dict[str, Any]] = {}
        for path in sorted(self._users_dir.glob("*.json")):
            payload = self._read_json(path)
            if payload and payload.get("id"):
                refreshed[str(payload["id"])] = payload
        self.users = refreshed

    def _refresh_auth_session_from_disk(self, token_hash: str) -> None:
        payload = self._read_json(self._auth_session_path(token_hash))
        if payload and payload.get("token_hash"):
            self.auth_sessions[str(payload["token_hash"])] = payload
            return
        self.auth_sessions.pop(token_hash, None)

    def _refresh_auth_sessions_from_disk(self) -> None:
        refreshed: Dict[str, Dict[str, Any]] = {}
        for path in sorted(self._auth_sessions_dir.glob("*.json")):
            payload = self._read_json(path)
            if payload and payload.get("token_hash"):
                refreshed[str(payload["token_hash"])] = payload
        self.auth_sessions = refreshed

    def _refresh_invite_from_disk(self, invite_id: str) -> None:
        payload = self._read_json(self._invite_path(invite_id))
        if payload and payload.get("id"):
            self.invites[str(payload["id"])] = payload
            return
        self.invites.pop(invite_id, None)

    def _refresh_invites_from_disk(self) -> None:
        refreshed: Dict[str, Dict[str, Any]] = {}
        for path in sorted(self._invites_dir.glob("*.json")):
            payload = self._read_json(path)
            if payload and payload.get("id"):
                refreshed[str(payload["id"])] = payload
        self.invites = refreshed

    def _refresh_runtime_config_from_disk(self) -> None:
        runtime_config = self._read_json(self._runtime_config_path)
        self.runtime_config = runtime_config if runtime_config else None

    def _refresh_auth_policy_from_disk(self) -> None:
        auth_policy = self._read_json(self._auth_policy_path)
        self.auth_policy = auth_policy if auth_policy else None

    def _refresh_runtime_config_for_user_from_disk(self, user_id: str) -> None:
        runtime_config = self._read_json(self._runtime_config_path_for_user(user_id))
        if runtime_config:
            self.runtime_configs[user_id] = runtime_config
            return
        self.runtime_configs.pop(user_id, None)

    def _message_identity(self, message: Any) -> str:
        if not isinstance(message, dict):
            return ""
        message_id = str(message.get("id") or "").strip()
        if message_id:
            return message_id
        created_at = str(message.get("created_at") or "").strip()
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or "").strip()
        if created_at and role and content:
            return f"{created_at}|{role}|{content}"
        return ""

    def _merge_chat_messages(self, current_messages: Any, incoming_messages: Any) -> List[Any]:
        merged: List[Any] = []
        message_indexes: Dict[str, int] = {}

        def append_or_replace(message: Any) -> None:
            identity = self._message_identity(message)
            copied_message = deepcopy(message)
            if identity and identity in message_indexes:
                merged[message_indexes[identity]] = copied_message
                return
            if identity:
                message_indexes[identity] = len(merged)
            merged.append(copied_message)

        if isinstance(current_messages, list):
            for message in current_messages:
                append_or_replace(message)
        if isinstance(incoming_messages, list):
            for message in incoming_messages:
                append_or_replace(message)
        return merged

    def _merge_chat_session_payload(self, current_session: Dict[str, Any], incoming_session: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(current_session)
        for key, value in incoming_session.items():
            if key == "messages":
                continue
            merged[key] = deepcopy(value)
        merged["messages"] = self._merge_chat_messages(current_session.get("messages"), incoming_session.get("messages"))
        return merged

    def get_job_event_cursor(self, job_id: str) -> Optional[str]:
        with self._lock:
            with self._file_lock(self._job_events_lock_path(job_id)):
                return self._job_event_cursor(job_id)

    def read_job_events_since(self, job_id: str, cursor: Optional[str]) -> tuple[List[Dict[str, Any]], Optional[str]]:
        with self._lock:
            with self._file_lock(self._job_events_lock_path(job_id)):
                event_dir = self._job_event_dir(job_id)
                if not event_dir.exists():
                    return [], cursor

                event_files = sorted(path.name for path in event_dir.glob("*.json"))
                pending_files = [name for name in event_files if cursor is None or name > cursor]
                events: List[Dict[str, Any]] = []
                next_cursor = cursor

                for name in pending_files:
                    payload = self._read_json(event_dir / name)
                    if not payload:
                        continue
                    events.append(payload)
                    next_cursor = name

                return events, next_cursor

    def _prune_job_events_locked(self, job_id: str) -> None:
        event_dir = self._job_event_dir(job_id)
        if not event_dir.exists():
            return
        event_files = sorted(path for path in event_dir.glob("*.json"))
        overflow = len(event_files) - self.MAX_PERSISTED_JOB_EVENTS
        if overflow <= 0:
            return
        for path in event_files[:overflow]:
            path.unlink(missing_ok=True)

    def create_job(self, job: Dict[str, Any]) -> None:
        with self._lock:
            touched_job = self._touch_job(job)
            job_id = str(touched_job["id"])
            with self._file_lock(self._job_lock_path(job_id)):
                self.jobs[job_id] = touched_job
                self.job_queues[job_id] = Queue()
                self.job_stream_subscribers[job_id] = []
                self._write_json(self._job_path(job_id), touched_job)

    def update_job(self, job_id: str, job: Dict[str, Any]) -> None:
        with self._lock:
            touched_job = self._touch_job(job)
            with self._file_lock(self._job_lock_path(job_id)):
                self.jobs[job_id] = touched_job
                self._write_json(self._job_path(job_id), touched_job)

    def list_jobs(self, owner_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            self._refresh_jobs_from_disk()
            sorted_jobs = sorted(
                (self._reconcile_job_counters(job) for job in self.jobs.values()),
                key=lambda item: item.get("updated_at") or item.get("completed_at") or item.get("created_at") or "",
                reverse=True,
            )
            if not owner_user_id:
                return sorted_jobs
            return [job for job in sorted_jobs if str(job.get("owner_user_id") or "").strip() == owner_user_id]

    def count_active_jobs(self, owner_user_id: Optional[str] = None) -> int:
        with self._lock:
            self._refresh_jobs_from_disk()
            return sum(
                1
                for job in self.jobs.values()
                if job.get("status") in self.ACTIVE_JOB_STATUSES
                and (not owner_user_id or str(job.get("owner_user_id") or "").strip() == owner_user_id)
            )

    def count_active_detached_workers(self, owner_user_id: Optional[str] = None) -> int:
        with self._lock:
            self._refresh_jobs_from_disk()
            active_worker_count = 0
            for job_id, job in list(self.jobs.items()):
                background_process = job.get("background_process") or {}
                if not isinstance(background_process, dict) or not background_process.get("active"):
                    continue
                if self._is_detached_worker_running(job):
                    if not owner_user_id or str(job.get("owner_user_id") or "").strip() == owner_user_id:
                        active_worker_count += 1
                    continue
                background_process["active"] = False
                background_process["finished_at"] = self._timestamp_now()
                job["background_process"] = background_process
                self.jobs[job_id] = job
                with self._file_lock(self._job_lock_path(job_id)):
                    self._write_json(self._job_path(job_id), job)
            return active_worker_count

    def get_job(self, job_id: str, owner_user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._refresh_job_from_disk(job_id)
            job = self.jobs.get(job_id)
            if not job:
                return None
            if owner_user_id and str(job.get("owner_user_id") or "").strip() != owner_user_id:
                return None
            return self._reconcile_job_counters(job)

    def set_assets(self, job_id: str, assets: Dict[str, Any]) -> None:
        with self._lock:
            with self._file_lock(self._assets_lock_path(job_id)):
                self.assets[job_id] = self._sanitize_assets(assets)
                self._write_json(self._assets_path(job_id), self.assets[job_id])

    def _delete_job_locked(self, job_id: str) -> None:
        self.jobs.pop(job_id, None)
        self.assets.pop(job_id, None)
        self.job_queues.pop(job_id, None)
        subscriber_queues = self.job_stream_subscribers.pop(job_id, [])
        self._job_path(job_id).unlink(missing_ok=True)
        self._assets_path(job_id).unlink(missing_ok=True)
        shutil.rmtree(self._job_event_dir(job_id), ignore_errors=True)
        for subscriber_queue in subscriber_queues:
            subscriber_queue.put({"event": self.STREAM_CLOSED_EVENT, "payload": {}})

    def delete_job(self, job_id: str) -> None:
        with self._lock:
            self._delete_job_locked(job_id)

    def delete_jobs_for_user(self, owner_user_id: str) -> None:
        with self._lock:
            self._refresh_jobs_from_disk()
            job_ids = [
                job_id
                for job_id, job in self.jobs.items()
                if str(job.get("owner_user_id") or "").strip() == owner_user_id
            ]
            for job_id in job_ids:
                self._delete_job_locked(job_id)

    def get_assets(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._refresh_assets_from_disk(job_id)
            assets = self.assets.get(job_id)
            return deepcopy(assets) if assets else None

    def find_task(self, job_id: str, task_id: str, owner_user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self.get_job(job_id, owner_user_id=owner_user_id)
            if not job:
                return None
            for task in job.get("tasks", []):
                if task["id"] == task_id:
                    return deepcopy(task)
            return None

    def publish_job_event(self, job_id: str, event_name: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            event = {
                "id": uuid.uuid4().hex,
                "event": event_name,
                "payload": payload,
            }
            with self._file_lock(self._job_events_lock_path(job_id)):
                event_path = self._job_event_payload_path(job_id, event["id"])
                event_path.parent.mkdir(parents=True, exist_ok=True)
                self._write_json(event_path, event)
                self._prune_job_events_locked(job_id)
            event_queue = self.job_queues.setdefault(job_id, Queue())
            event_queue.put(deepcopy(event))
            for subscriber_queue in self.job_stream_subscribers.setdefault(job_id, []):
                subscriber_queue.put(deepcopy(event))

    def get_job_queue(self, job_id: str) -> "Queue[Dict[str, Any]]":
        return self.job_queues.setdefault(job_id, Queue())

    def subscribe_job_events(self, job_id: str) -> "Queue[Dict[str, Any]]":
        with self._lock:
            subscriber_queue: "Queue[Dict[str, Any]]" = Queue()
            self.job_stream_subscribers.setdefault(job_id, []).append(subscriber_queue)
            self.job_queues.setdefault(job_id, Queue())
            return subscriber_queue

    def unsubscribe_job_events(self, job_id: str, subscriber_queue: "Queue[Dict[str, Any]]") -> None:
        with self._lock:
            subscribers = self.job_stream_subscribers.setdefault(job_id, [])
            if subscriber_queue in subscribers:
                subscribers.remove(subscriber_queue)
        subscriber_queue.put({"event": self.STREAM_CLOSED_EVENT, "payload": {}})

    def create_chat_session(self, session: Dict[str, Any]) -> None:
        with self._lock:
            touched_session = self._touch_session(session)
            touched_session.setdefault("messages", [])
            session_id = str(touched_session["id"])
            with self._file_lock(self._chat_session_lock_path(session_id)):
                self._refresh_chat_session_from_disk(session_id)
                existing_session = self.chat_sessions.get(session_id)
                if existing_session:
                    touched_session = self._touch_session(self._merge_chat_session_payload(existing_session, touched_session))
                self.chat_sessions[session_id] = touched_session
                self._write_json(self._chat_session_path(session_id), touched_session)

    def list_chat_sessions(self, research_job_id: Optional[str] = None, owner_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            self._refresh_chat_sessions_from_disk()
            sessions = [
                deepcopy(session)
                for session in self.chat_sessions.values()
                if research_job_id is None or session.get("research_job_id") == research_job_id
            ]
            if owner_user_id:
                sessions = [session for session in sessions if str(session.get("owner_user_id") or "").strip() == owner_user_id]
            sessions.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
            return sessions

    def get_chat_session(self, session_id: str, owner_user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._refresh_chat_session_from_disk(session_id)
            session = self.chat_sessions.get(session_id)
            if session and owner_user_id and str(session.get("owner_user_id") or "").strip() != owner_user_id:
                return None
            return deepcopy(session) if session else None

    def get_latest_chat_session_for_job(self, research_job_id: str, owner_user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        sessions = self.list_chat_sessions(research_job_id=research_job_id, owner_user_id=owner_user_id)
        return sessions[0] if sessions else None

    def update_chat_session(self, session_id: str, session: Dict[str, Any], owner_user_id: Optional[str] = None) -> None:
        with self._lock:
            with self._file_lock(self._chat_session_lock_path(session_id)):
                self._refresh_chat_session_from_disk(session_id)
                current_session = self.chat_sessions.get(session_id) or {"id": session_id, "messages": []}
                if owner_user_id and str(current_session.get("owner_user_id") or "").strip() != owner_user_id:
                    raise KeyError(session_id)
                merged_session = self._merge_chat_session_payload(current_session, session)
                merged_session["id"] = session_id
                touched_session = self._touch_session(merged_session)
                self.chat_sessions[session_id] = touched_session
                self._write_json(self._chat_session_path(session_id), touched_session)

    def append_chat_message(self, session_id: str, message: Dict[str, Any], owner_user_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            with self._file_lock(self._chat_session_lock_path(session_id)):
                self._refresh_chat_session_from_disk(session_id)
                current_session = self.chat_sessions.get(session_id)
                if not current_session:
                    raise KeyError(session_id)
                if owner_user_id and str(current_session.get("owner_user_id") or "").strip() != owner_user_id:
                    raise KeyError(session_id)
                session = deepcopy(current_session)
                session["messages"] = self._merge_chat_messages(session.get("messages"), [deepcopy(message)])
                touched_session = self._touch_session(session)
                self.chat_sessions[session_id] = touched_session
                self._write_json(self._chat_session_path(session_id), touched_session)
            return deepcopy(message)

    def _delete_chat_session_locked(self, session_id: str) -> None:
        self.chat_sessions.pop(session_id, None)
        self._chat_session_path(session_id).unlink(missing_ok=True)
        self._chat_session_lock_path(session_id).unlink(missing_ok=True)

    def delete_chat_session(self, session_id: str) -> None:
        with self._lock:
            self._delete_chat_session_locked(session_id)

    def delete_chat_sessions_for_user(self, owner_user_id: str) -> None:
        with self._lock:
            self._refresh_chat_sessions_from_disk()
            session_ids = [
                session_id
                for session_id, session in self.chat_sessions.items()
                if str(session.get("owner_user_id") or "").strip() == owner_user_id
            ]
            for session_id in session_ids:
                self._delete_chat_session_locked(session_id)

    def create_user(self, user: Dict[str, Any]) -> None:
        with self._lock:
            user_id = str(user["id"])
            payload = deepcopy(user)
            now = self._timestamp_now()
            payload.setdefault("created_at", now)
            payload["updated_at"] = now
            self.users[user_id] = payload
            self._write_json(self._user_path(user_id), payload, private=True)

    def update_user(self, user_id: str, user: Dict[str, Any]) -> None:
        with self._lock:
            payload = deepcopy(user)
            payload["id"] = user_id
            payload.setdefault("created_at", self.users.get(user_id, {}).get("created_at") or self._timestamp_now())
            payload["updated_at"] = self._timestamp_now()
            self.users[user_id] = payload
            self._write_json(self._user_path(user_id), payload, private=True)

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._refresh_user_from_disk(user_id)
            user = self.users.get(user_id)
            return deepcopy(user) if user else None

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            self.users.pop(user_id, None)
            self._user_path(user_id).unlink(missing_ok=True)

    def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        normalized_email = str(email or "").strip().lower()
        with self._lock:
            self._refresh_users_from_disk()
            for user in self.users.values():
                if str(user.get("email") or "").strip().lower() == normalized_email:
                    return deepcopy(user)
            return None

    def list_users(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._refresh_users_from_disk()
            users = [deepcopy(user) for user in self.users.values()]
            users.sort(key=lambda item: item.get("created_at") or "", reverse=False)
            return users

    def count_users(self) -> int:
        with self._lock:
            self._refresh_users_from_disk()
            return len(self.users)

    def create_auth_session(self, auth_session: Dict[str, Any]) -> None:
        with self._lock:
            token_hash = str(auth_session["token_hash"])
            payload = deepcopy(auth_session)
            now = self._timestamp_now()
            payload.setdefault("created_at", now)
            payload.setdefault("last_seen_at", now)
            self.auth_sessions[token_hash] = payload
            self._write_json(self._auth_session_path(token_hash), payload, private=True)

    def get_auth_session(self, token_hash: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._refresh_auth_session_from_disk(token_hash)
            auth_session = self.auth_sessions.get(token_hash)
            return deepcopy(auth_session) if auth_session else None

    def update_auth_session(self, token_hash: str, auth_session: Dict[str, Any]) -> None:
        with self._lock:
            payload = deepcopy(auth_session)
            payload["token_hash"] = token_hash
            self.auth_sessions[token_hash] = payload
            self._write_json(self._auth_session_path(token_hash), payload, private=True)

    def delete_auth_session(self, token_hash: str) -> None:
        with self._lock:
            self.auth_sessions.pop(token_hash, None)
            self._auth_session_path(token_hash).unlink(missing_ok=True)

    def delete_auth_sessions_for_user(self, user_id: str) -> None:
        with self._lock:
            self._refresh_auth_sessions_from_disk()
            for token_hash, auth_session in list(self.auth_sessions.items()):
                if str(auth_session.get("user_id") or "").strip() != user_id:
                    continue
                self.auth_sessions.pop(token_hash, None)
                self._auth_session_path(token_hash).unlink(missing_ok=True)

    def create_invite(self, invite: Dict[str, Any]) -> None:
        with self._lock:
            invite_id = str(invite["id"])
            payload = deepcopy(invite)
            now = self._timestamp_now()
            payload.setdefault("created_at", now)
            payload["updated_at"] = now
            self.invites[invite_id] = payload
            self._write_json(self._invite_path(invite_id), payload, private=True)

    def update_invite(self, invite_id: str, invite: Dict[str, Any]) -> None:
        with self._lock:
            payload = deepcopy(invite)
            payload["id"] = invite_id
            payload.setdefault("created_at", self.invites.get(invite_id, {}).get("created_at") or self._timestamp_now())
            payload["updated_at"] = self._timestamp_now()
            self.invites[invite_id] = payload
            self._write_json(self._invite_path(invite_id), payload, private=True)

    def get_invite(self, invite_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._refresh_invite_from_disk(invite_id)
            invite = self.invites.get(invite_id)
            return deepcopy(invite) if invite else None

    def list_invites(self, active_only: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            self._refresh_invites_from_disk()
            invites = [deepcopy(invite) for invite in self.invites.values()]
            if active_only:
                invites = [invite for invite in invites if not invite.get("disabled_at") and not invite.get("used_at")]
            invites.sort(key=lambda item: item.get("created_at") or "", reverse=True)
            return invites

    def find_invite_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        normalized_code = str(code or "").strip()
        if not normalized_code:
            return None
        with self._lock:
            self._refresh_invites_from_disk()
            for invite in self.invites.values():
                if str(invite.get("code") or "").strip() != normalized_code:
                    continue
                if invite.get("disabled_at") or invite.get("used_at"):
                    return None
                return deepcopy(invite)
            return None

    def get_runtime_config(self, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            if user_id:
                self._refresh_runtime_config_for_user_from_disk(user_id)
                runtime_config = self.runtime_configs.get(user_id)
                if runtime_config:
                    return deepcopy(runtime_config)
            self._refresh_runtime_config_from_disk()
            return deepcopy(self.runtime_config) if self.runtime_config else None

    def get_auth_policy(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._refresh_auth_policy_from_disk()
            return deepcopy(self.auth_policy) if self.auth_policy else None

    def delete_runtime_config(self, user_id: str) -> None:
        with self._lock:
            self.runtime_configs.pop(user_id, None)
            self._runtime_config_path_for_user(user_id).unlink(missing_ok=True)
            self._runtime_config_lock_path_for_user(user_id).unlink(missing_ok=True)

    def set_runtime_config(self, runtime_config: Dict[str, Any], user_id: Optional[str] = None) -> None:
        with self._lock:
            if user_id:
                with self._file_lock(self._runtime_config_lock_path_for_user(user_id)):
                    self.runtime_configs[user_id] = deepcopy(runtime_config)
                    self._write_json(self._runtime_config_path_for_user(user_id), self.runtime_configs[user_id], private=True)
                return
            with self._file_lock(self._runtime_config_lock_path()):
                self.runtime_config = deepcopy(runtime_config)
                self._write_json(self._runtime_config_path, self.runtime_config, private=True)

    def set_auth_policy(self, auth_policy: Dict[str, Any]) -> None:
        with self._lock:
            with self._file_lock(self._auth_policy_lock_path()):
                self.auth_policy = deepcopy(auth_policy)
                self._write_json(self._auth_policy_path, self.auth_policy, private=True)

    def supports_background_worker(self) -> bool:
        return False

    def enqueue_background_job(self, job_id: str) -> None:
        self.background_job_queue.put(str(job_id))

    def dequeue_background_job(self, timeout_seconds: float = 1.0) -> Optional[str]:
        try:
            return self.background_job_queue.get(timeout=max(0.0, float(timeout_seconds)))
        except Empty:
            return None
