import json
import os
import shlex
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


class SystemUpdateService:
    def __init__(self, repo_root: Optional[Path] = None) -> None:
        self.repo_root = Path(repo_root or Path(__file__).resolve().parents[4]).resolve()
        self.script_path = self.repo_root / "scripts" / "server_update.sh"
        state_dir_raw = str(os.getenv("PM_AGENT_STATE_DIR", "output/state") or "output/state").strip()
        state_root = Path(state_dir_raw).expanduser()
        if not state_root.is_absolute():
            state_root = (self.repo_root / state_root).resolve()
        self.state_root = state_root
        self.update_root = self.state_root / "system_updates"
        self.jobs_path = self.update_root / "jobs.json"
        self.update_root.mkdir(parents=True, exist_ok=True)

    def _git_available(self) -> bool:
        return shutil.which("git") is not None

    def _is_git_checkout(self) -> bool:
        if not self._git_available():
            return False
        if not (self.repo_root / ".git").exists():
            return False
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"

    def _run_git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def _git_output(self, *args: str) -> str:
        result = self._run_git(*args)
        if result.returncode != 0:
            return ""
        return (result.stdout or "").strip()

    def _load_jobs(self) -> List[Dict[str, Any]]:
        payload = _read_json(self.jobs_path, [])
        if not isinstance(payload, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                normalized.append(dict(item))
        return normalized

    def _save_jobs(self, jobs: List[Dict[str, Any]]) -> None:
        self.update_root.mkdir(parents=True, exist_ok=True)
        self.jobs_path.write_text(json.dumps(jobs[-50:], ensure_ascii=False, indent=2), encoding="utf-8")

    def _is_pid_running(self, pid: Optional[int]) -> bool:
        if not pid or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def _extract_exit_code(self, log_path: Path) -> Optional[int]:
        if not log_path.exists():
            return None
        marker = "__PM_UPDATE_EXIT_CODE__="
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None
        for line in reversed(text.splitlines()):
            if marker in line:
                raw = line.split(marker, 1)[1].strip()
                try:
                    return int(raw)
                except ValueError:
                    return None
        return None

    def _refresh_jobs(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        changed = False
        refreshed: List[Dict[str, Any]] = []
        for job in jobs:
            next_job = dict(job)
            status = str(next_job.get("status") or "unknown")
            pid = int(next_job.get("pid") or 0)
            log_path = Path(str(next_job.get("log_path") or ""))
            if status == "running" and pid and not self._is_pid_running(pid):
                exit_code = self._extract_exit_code(log_path)
                next_job["exit_code"] = exit_code
                next_job["status"] = "succeeded" if exit_code == 0 else "failed"
                next_job["finished_at"] = next_job.get("finished_at") or iso_now()
                changed = True
            refreshed.append(next_job)
        if changed:
            self._save_jobs(refreshed)
        return refreshed

    def _ref_exists(self, ref_name: str) -> bool:
        result = self._run_git("rev-parse", "--verify", "--quiet", f"{ref_name}^{{commit}}")
        return result.returncode == 0

    def _resolve_commit(self, ref_name: str) -> str:
        return self._git_output("rev-parse", "--short", ref_name)

    def _version_options(self) -> List[Dict[str, Any]]:
        options: List[Dict[str, Any]] = []
        if self._ref_exists("main"):
            options.append(
                {
                    "ref": "main",
                    "kind": "branch",
                    "commit": self._resolve_commit("main"),
                    "label": "main（最新主分支）",
                }
            )

        tags_output = self._git_output("tag", "--sort=-version:refname")
        tags = [item.strip() for item in tags_output.splitlines() if item.strip()]
        for tag in tags[:40]:
            options.append(
                {
                    "ref": tag,
                    "kind": "tag",
                    "commit": self._resolve_commit(tag),
                    "label": tag,
                }
            )
        return options

    def _runtime_capabilities(self) -> Dict[str, Any]:
        if not self._git_available():
            return {
                "supported": False,
                "can_execute": False,
                "execution_enabled": False,
                "reason": "服务器未安装 git，无法读取或更新版本。",
            }
        if not self._is_git_checkout():
            return {
                "supported": False,
                "can_execute": False,
                "execution_enabled": False,
                "reason": "当前运行目录不是完整 git 工作区（常见于纯 Docker 镜像运行）。",
            }
        if not self.script_path.exists():
            return {
                "supported": False,
                "can_execute": False,
                "execution_enabled": False,
                "reason": "未找到 scripts/server_update.sh，请先更新代码版本。",
            }
        execution_enabled = _env_flag("PM_AGENT_WEB_UPDATE_ENABLED", default=False)
        if not execution_enabled:
            return {
                "supported": True,
                "can_execute": False,
                "execution_enabled": False,
                "reason": "默认关闭 Web 执行更新。若要启用，请在服务器设置 PM_AGENT_WEB_UPDATE_ENABLED=true 后重启 API。",
            }
        return {
            "supported": True,
            "can_execute": True,
            "execution_enabled": True,
            "reason": None,
        }

    def get_status(self) -> Dict[str, Any]:
        capabilities = self._runtime_capabilities()
        jobs = self._refresh_jobs(self._load_jobs())
        branch = self._git_output("symbolic-ref", "--short", "HEAD")
        tag = self._git_output("describe", "--tags", "--exact-match", "HEAD")
        commit = self._git_output("rev-parse", "--short", "HEAD")
        project_name = str(os.getenv("COMPOSE_PROJECT_NAME", "") or "").strip() or None
        default_ref = tag or "main"
        suggested_command_parts = ["./scripts/server_update.sh", "--ref", default_ref]
        if project_name:
            suggested_command_parts.extend(["--project-name", project_name])
        active_job = next((item for item in reversed(jobs) if str(item.get("status")) == "running"), None)
        recent_jobs = list(reversed(jobs[-10:]))
        return {
            "supported": bool(capabilities["supported"]),
            "can_execute": bool(capabilities["can_execute"]),
            "execution_enabled": bool(capabilities["execution_enabled"]),
            "reason": capabilities.get("reason"),
            "repo_root": str(self.repo_root),
            "current_ref": tag or branch or commit,
            "current_tag": tag or None,
            "current_branch": branch or None,
            "current_commit": commit,
            "default_ref": default_ref,
            "compose_project_name": project_name,
            "options": self._version_options() if capabilities["supported"] else [],
            "suggested_command": " ".join(suggested_command_parts),
            "active_job": active_job,
            "recent_jobs": recent_jobs,
        }

    def trigger_update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        capabilities = self._runtime_capabilities()
        if not capabilities["supported"]:
            raise ValueError(str(capabilities.get("reason") or "当前环境不支持 Web 更新。"))
        if not capabilities["can_execute"]:
            raise ValueError(str(capabilities.get("reason") or "当前环境未启用 Web 更新执行权限。"))

        jobs = self._refresh_jobs(self._load_jobs())
        running = next((item for item in reversed(jobs) if str(item.get("status")) == "running"), None)
        if running:
            raise ValueError("已有更新任务在执行，请等待完成后再触发下一次更新。")

        target_ref = str(payload.get("ref") or "main").strip() or "main"
        if not self._ref_exists(target_ref):
            raise ValueError(f"版本 `{target_ref}` 不存在，请先 fetch tags 或检查输入。")

        use_prod = bool(payload.get("use_prod"))
        project_name = str(payload.get("project_name") or "").strip()
        skip_backup = bool(payload.get("skip_backup"))
        skip_pull = bool(payload.get("skip_pull"))
        skip_build = bool(payload.get("skip_build"))

        command_parts = [str(self.script_path), "--ref", target_ref]
        if use_prod:
            command_parts.append("--prod")
        if project_name:
            command_parts.extend(["--project-name", project_name])
        if skip_backup:
            command_parts.append("--no-backup")
        if skip_pull:
            command_parts.append("--no-pull")
        if skip_build:
            command_parts.append("--skip-build")

        admin_email = str(payload.get("admin_email") or "").strip()
        admin_password = str(payload.get("admin_password") or "").strip()
        admin_name = str(payload.get("admin_name") or "").strip()
        if use_prod and admin_email and admin_password:
            command_parts.extend(["--admin-email", admin_email, "--admin-password", admin_password])
            if admin_name:
                command_parts.extend(["--admin-name", admin_name])

        self.update_root.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex[:12]
        log_path = self.update_root / f"{iso_now().replace(':', '').replace('+00:00', 'Z')}-{job_id}.log"
        quoted_command = " ".join(shlex.quote(part) for part in command_parts)
        wrapped_command = f"{quoted_command}; code=$?; echo \"__PM_UPDATE_EXIT_CODE__=$code\""

        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"[{iso_now()}] Starting update job {job_id}\n")
            stream.write(f"[{iso_now()}] Command: {quoted_command}\n")

        log_stream = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            ["bash", "-lc", wrapped_command],
            cwd=str(self.repo_root),
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=os.environ.copy(),
        )
        log_stream.close()

        record = {
            "job_id": job_id,
            "ref": target_ref,
            "use_prod": use_prod,
            "project_name": project_name or None,
            "skip_backup": skip_backup,
            "skip_pull": skip_pull,
            "skip_build": skip_build,
            "status": "running",
            "pid": process.pid,
            "started_at": iso_now(),
            "finished_at": None,
            "exit_code": None,
            "log_path": str(log_path),
            "command": quoted_command,
        }
        jobs.append(record)
        self._save_jobs(jobs)
        return record
