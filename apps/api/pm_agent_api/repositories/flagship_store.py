from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Any, Dict, List, Optional

from pm_agent_api.repositories.in_memory_store import InMemoryStateRepository


LOGGER = logging.getLogger(__name__)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ObjectStorageSettings:
    bucket: str
    endpoint_url: Optional[str] = None
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    region: Optional[str] = None
    key_prefix: str = "pm-agent"


class S3ObjectStore:
    def __init__(self, settings: ObjectStorageSettings) -> None:
        try:
            import boto3
        except ImportError as error:  # pragma: no cover - optional dependency
            raise RuntimeError("Flagship storage requires `boto3` for S3-compatible object storage.") from error

        self.settings = settings
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url or None,
            aws_access_key_id=settings.access_key_id or None,
            aws_secret_access_key=settings.secret_access_key or None,
            region_name=settings.region or None,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.settings.bucket)
        except Exception:
            create_kwargs: Dict[str, Any] = {"Bucket": self.settings.bucket}
            region = str(self.settings.region or "").strip()
            if region and region != "us-east-1":
                create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
            self.client.create_bucket(**create_kwargs)

    def _normalize_key(self, key: str) -> str:
        prefix = str(self.settings.key_prefix or "").strip().strip("/")
        suffix = str(key or "").strip().strip("/")
        if prefix and suffix:
            return f"{prefix}/{suffix}"
        if prefix:
            return prefix
        return suffix

    def put_json(self, key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        object_key = self._normalize_key(key)
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        response = self.client.put_object(
            Bucket=self.settings.bucket,
            Key=object_key,
            Body=body,
            ContentType="application/json; charset=utf-8",
        )
        etag = str(response.get("ETag") or "").strip('"')
        return {
            "storage": "s3",
            "bucket": self.settings.bucket,
            "key": object_key,
            "etag": etag or None,
            "size_bytes": len(body),
            "content_type": "application/json",
            "stored_at": iso_now(),
        }

    def get_json(self, pointer: Dict[str, Any]) -> Dict[str, Any]:
        response = self.client.get_object(
            Bucket=str(pointer.get("bucket") or self.settings.bucket),
            Key=str(pointer.get("key") or ""),
        )
        body = response["Body"].read().decode("utf-8")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Stored object payload must be a JSON object.")
        return payload

    def delete(self, pointer: Optional[Dict[str, Any]]) -> None:
        if not isinstance(pointer, dict):
            return
        key = str(pointer.get("key") or "").strip()
        if not key:
            return
        self.client.delete_object(
            Bucket=str(pointer.get("bucket") or self.settings.bucket),
            Key=key,
        )


class FlagshipStateRepository:
    STREAM_CLOSED_EVENT = InMemoryStateRepository.STREAM_CLOSED_EVENT
    ACTIVE_JOB_STATUSES = InMemoryStateRepository.ACTIVE_JOB_STATUSES
    MAX_PERSISTED_JOB_EVENTS = InMemoryStateRepository.MAX_PERSISTED_JOB_EVENTS
    REQUIRED_JOB_FIELDS = InMemoryStateRepository.REQUIRED_JOB_FIELDS

    STATE_SCOPE_JOB = "job"
    STATE_SCOPE_ASSET = "asset"
    STATE_SCOPE_CHAT_SESSION = "chat_session"
    STATE_SCOPE_USER = "user"
    STATE_SCOPE_AUTH_SESSION = "auth_session"
    STATE_SCOPE_INVITE = "invite"
    STATE_SCOPE_RUNTIME_CONFIG = "runtime_config"
    STATE_SCOPE_AUTH_POLICY = "auth_policy"
    GLOBAL_DOCUMENT_ID = "__global__"
    REDIS_EVENT_CHANNEL_PREFIX = "pm-agent:job-events"
    REDIS_WORKER_QUEUE_KEY = "pm-agent:background-jobs"

    def __init__(
        self,
        *,
        postgres_dsn: str,
        redis_url: Optional[str] = None,
        object_storage: Optional[ObjectStorageSettings] = None,
    ) -> None:
        try:
            import psycopg  # noqa: F401
        except ImportError as error:  # pragma: no cover - optional dependency
            raise RuntimeError("Flagship storage requires `psycopg` (psycopg3).") from error

        configured_state_root = str(os.getenv("PM_AGENT_STATE_DIR", "") or "").strip()
        self._state_root = Path(configured_state_root).expanduser() if configured_state_root else _repo_root() / "output" / "state"
        self._state_root.mkdir(parents=True, exist_ok=True)
        self._postgres_dsn = postgres_dsn
        self._lock = threading.RLock()
        self._cache_dir = tempfile.TemporaryDirectory(prefix="pm-agent-flagship-cache-")
        cache_root = Path(self._cache_dir.name)
        self._cache = InMemoryStateRepository(
            state_root=cache_root,
            runtime_config_path=cache_root / "runtime_config.json",
        )
        self.job_queues: Dict[str, "Queue[Dict[str, Any]]"] = {}
        self.job_stream_subscribers: Dict[str, List["Queue[Dict[str, Any]]"]] = {}
        self._redis_listener_controls: Dict[int, tuple[Any, threading.Event, threading.Thread]] = {}
        self._redis_client = self._build_redis_client(redis_url)
        self._object_store = S3ObjectStore(object_storage) if object_storage else None
        self._bootstrap_schema()

    @classmethod
    def from_env(cls) -> "FlagshipStateRepository":
        postgres_dsn = str(
            os.getenv("PM_AGENT_POSTGRES_DSN")
            or os.getenv("PM_AGENT_DATABASE_URL")
            or ""
        ).strip()
        if not postgres_dsn:
            raise RuntimeError("Flagship storage requires `PM_AGENT_POSTGRES_DSN` or `PM_AGENT_DATABASE_URL`.")
        redis_url = str(os.getenv("PM_AGENT_REDIS_URL") or "").strip() or None
        bucket = str(os.getenv("PM_AGENT_OBJECT_STORAGE_BUCKET") or "").strip()
        object_storage = None
        if bucket:
            object_storage = ObjectStorageSettings(
                bucket=bucket,
                endpoint_url=str(os.getenv("PM_AGENT_OBJECT_STORAGE_ENDPOINT") or "").strip() or None,
                access_key_id=str(os.getenv("PM_AGENT_OBJECT_STORAGE_ACCESS_KEY") or "").strip() or None,
                secret_access_key=str(os.getenv("PM_AGENT_OBJECT_STORAGE_SECRET_KEY") or "").strip() or None,
                region=str(os.getenv("PM_AGENT_OBJECT_STORAGE_REGION") or "").strip() or None,
                key_prefix=str(os.getenv("PM_AGENT_OBJECT_STORAGE_PREFIX") or "pm-agent").strip() or "pm-agent",
            )
        return cls(postgres_dsn=postgres_dsn, redis_url=redis_url, object_storage=object_storage)

    def _connect(self):
        import psycopg

        return psycopg.connect(self._postgres_dsn, autocommit=True)

    def _build_redis_client(self, redis_url: Optional[str]):
        if not redis_url:
            return None
        try:
            import redis
        except ImportError as error:  # pragma: no cover - optional dependency
            raise RuntimeError("Flagship storage requires `redis` when `PM_AGENT_REDIS_URL` is set.") from error
        return redis.Redis.from_url(redis_url, decode_responses=False)

    def _bootstrap_schema(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS state_documents (
                    scope TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    owner_user_id TEXT,
                    payload TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (scope, document_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_state_documents_owner
                ON state_documents (scope, owner_user_id)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS job_events (
                    cursor BIGSERIAL PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    event_name TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_job_events_job_cursor
                ON job_events (job_id, cursor)
                """
            )

    def _json_dumps(self, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)

    def _json_loads(self, payload: str) -> Dict[str, Any]:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("Repository payload must be a JSON object.")
        return data

    def _upsert_document(
        self,
        scope: str,
        document_id: str,
        payload: Dict[str, Any],
        owner_user_id: Optional[str] = None,
    ) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO state_documents (scope, document_id, owner_user_id, payload, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (scope, document_id)
                DO UPDATE SET
                    owner_user_id = EXCLUDED.owner_user_id,
                    payload = EXCLUDED.payload,
                    updated_at = NOW()
                """,
                (scope, document_id, owner_user_id, self._json_dumps(payload)),
            )

    def _delete_document(self, scope: str, document_id: str) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM state_documents WHERE scope = %s AND document_id = %s",
                (scope, document_id),
            )

    def _delete_documents_for_owner(self, scope: str, owner_user_id: str) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM state_documents WHERE scope = %s AND owner_user_id = %s",
                (scope, owner_user_id),
            )

    def _select_document(self, scope: str, document_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM state_documents WHERE scope = %s AND document_id = %s",
                (scope, document_id),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return self._json_loads(str(row[0]))

    def _select_documents(self, scope: str, owner_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT payload FROM state_documents WHERE scope = %s"
        params: List[Any] = [scope]
        if owner_user_id is not None:
            query += " AND owner_user_id = %s"
            params.append(owner_user_id)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
        return [self._json_loads(str(row[0])) for row in rows]

    def _asset_pointer_payload(self, job_id: str, assets: Dict[str, Any]) -> Dict[str, Any]:
        if not self._object_store:
            return assets
        pointer = self._object_store.put_json(f"assets/{job_id}/{uuid.uuid4().hex}.json", assets)
        return {
            "job_id": job_id,
            "__object_storage__": pointer,
        }

    def _resolve_assets_payload(self, payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not payload:
            return None
        pointer = payload.get("__object_storage__")
        if isinstance(pointer, dict):
            return self._object_store.get_json(pointer) if self._object_store else None
        return payload

    def _delete_asset_blob(self, payload: Optional[Dict[str, Any]]) -> None:
        if not self._object_store or not payload:
            return
        pointer = payload.get("__object_storage__")
        if isinstance(pointer, dict):
            self._object_store.delete(pointer)

    def _job_owner_user_id(self, job_id: str) -> Optional[str]:
        job = self._select_document(self.STATE_SCOPE_JOB, job_id)
        if not job:
            return None
        return str(job.get("owner_user_id") or "").strip() or None

    def _event_channel(self, job_id: str) -> str:
        return f"{self.REDIS_EVENT_CHANNEL_PREFIX}:{job_id}"

    def _prune_job_events(self, job_id: str) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM job_events
                WHERE cursor IN (
                    SELECT cursor
                    FROM job_events
                    WHERE job_id = %s
                    ORDER BY cursor DESC
                    OFFSET %s
                )
                """,
                (job_id, self.MAX_PERSISTED_JOB_EVENTS),
            )

    def _insert_job_event(self, job_id: str, event: Dict[str, Any]) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO job_events (job_id, event_id, event_name, payload, created_at)
                VALUES (%s, %s, %s, %s, NOW())
                """,
                (job_id, event["id"], event["event"], self._json_dumps(event["payload"])),
            )
        self._prune_job_events(job_id)

    def _queue_event_locally(self, job_id: str, event: Dict[str, Any], fanout_subscribers: bool) -> None:
        event_queue = self.job_queues.setdefault(job_id, Queue())
        event_queue.put(deepcopy(event))
        if not fanout_subscribers:
            return
        for subscriber_queue in self.job_stream_subscribers.setdefault(job_id, []):
            subscriber_queue.put(deepcopy(event))

    def _pump_redis_events(
        self,
        subscriber_queue: "Queue[Dict[str, Any]]",
        pubsub: Any,
        stop_event: threading.Event,
    ) -> None:
        while not stop_event.is_set():
            message = pubsub.get_message(timeout=0.5)
            if not message or message.get("type") != "message":
                continue
            raw_data = message.get("data")
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")
            if not raw_data:
                continue
            try:
                payload = json.loads(str(raw_data))
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                subscriber_queue.put(payload)
        try:
            pubsub.close()
        except Exception:
            pass

    def _decode_queue_job_id(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, bytes):
            text = value.decode("utf-8")
        else:
            text = str(value)
        normalized = text.strip()
        return normalized or None

    def _load_cache_job(self, job_id: str) -> None:
        job = self._select_document(self.STATE_SCOPE_JOB, job_id)
        if job:
            self._cache.jobs[job_id] = deepcopy(job)
            self._cache.job_queues.setdefault(job_id, Queue())
            self._cache.job_stream_subscribers.setdefault(job_id, [])
            return
        self._cache.jobs.pop(job_id, None)

    def _load_cache_chat_session(self, session_id: str) -> None:
        session = self._select_document(self.STATE_SCOPE_CHAT_SESSION, session_id)
        if session:
            self._cache.chat_sessions[session_id] = deepcopy(session)
            return
        self._cache.chat_sessions.pop(session_id, None)

    def _load_cache_user(self, user_id: str) -> None:
        user = self._select_document(self.STATE_SCOPE_USER, user_id)
        if user:
            self._cache.users[user_id] = deepcopy(user)
            return
        self._cache.users.pop(user_id, None)

    def _load_cache_auth_session(self, token_hash: str) -> None:
        auth_session = self._select_document(self.STATE_SCOPE_AUTH_SESSION, token_hash)
        if auth_session:
            self._cache.auth_sessions[token_hash] = deepcopy(auth_session)
            return
        self._cache.auth_sessions.pop(token_hash, None)

    def _load_cache_invite(self, invite_id: str) -> None:
        invite = self._select_document(self.STATE_SCOPE_INVITE, invite_id)
        if invite:
            self._cache.invites[invite_id] = deepcopy(invite)
            return
        self._cache.invites.pop(invite_id, None)

    def create_job(self, job: Dict[str, Any]) -> None:
        with self._lock:
            job_id = str(job["id"])
            self._cache.create_job(job)
            stored_job = deepcopy(self._cache.jobs[job_id])
            self._upsert_document(
                self.STATE_SCOPE_JOB,
                job_id,
                stored_job,
                owner_user_id=str(stored_job.get("owner_user_id") or "").strip() or None,
            )
            self.job_queues.setdefault(job_id, Queue())
            self.job_stream_subscribers.setdefault(job_id, [])

    def update_job(self, job_id: str, job: Dict[str, Any]) -> None:
        with self._lock:
            self._load_cache_job(job_id)
            self._cache.update_job(job_id, job)
            stored_job = deepcopy(self._cache.jobs[job_id])
            self._upsert_document(
                self.STATE_SCOPE_JOB,
                job_id,
                stored_job,
                owner_user_id=str(stored_job.get("owner_user_id") or "").strip() or None,
            )

    def list_jobs(self, owner_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        jobs = [
            self._cache._reconcile_job_counters(job)
            for job in self._select_documents(self.STATE_SCOPE_JOB, owner_user_id=owner_user_id)
        ]
        jobs.sort(
            key=lambda item: item.get("updated_at") or item.get("completed_at") or item.get("created_at") or "",
            reverse=True,
        )
        return jobs

    def count_active_jobs(self, owner_user_id: Optional[str] = None) -> int:
        return sum(
            1
            for job in self.list_jobs(owner_user_id=owner_user_id)
            if job.get("status") in self.ACTIVE_JOB_STATUSES
        )

    def count_active_detached_workers(self, owner_user_id: Optional[str] = None) -> int:
        active_worker_count = 0
        for job in self.list_jobs(owner_user_id=owner_user_id):
            background_process = job.get("background_process") or {}
            if not isinstance(background_process, dict) or not background_process.get("active"):
                continue
            mode = str(job.get("execution_mode") or background_process.get("mode") or "").strip()
            if mode == "worker":
                worker_pid = int(background_process.get("worker_pid") or 0) if str(background_process.get("worker_pid") or "").strip() else 0
                if self._shared_worker_running(worker_pid):
                    active_worker_count += 1
                    continue
                if worker_pid > 0:
                    background_process["active"] = False
                    background_process["finished_at"] = iso_now()
                    job["background_process"] = background_process
                    self.update_job(str(job.get("id") or ""), job)
                continue
            if self._cache._is_detached_worker_running(job):
                active_worker_count += 1
                continue
            background_process["active"] = False
            background_process["finished_at"] = iso_now()
            job["background_process"] = background_process
            self.update_job(str(job.get("id") or ""), job)
        return active_worker_count

    def _shared_worker_running(self, worker_pid: int) -> bool:
        if worker_pid <= 0:
            return False
        try:
            os.kill(worker_pid, 0)
        except OSError:
            return False
        cmdline = self._cache._process_cmdline(worker_pid)
        if not cmdline:
            return True
        return "pm_agent_api.worker_daemon" in cmdline

    def get_job(self, job_id: str, owner_user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        job = self._select_document(self.STATE_SCOPE_JOB, job_id)
        if not job:
            return None
        if owner_user_id and str(job.get("owner_user_id") or "").strip() != owner_user_id:
            return None
        return self._cache._reconcile_job_counters(job)

    def set_assets(self, job_id: str, assets: Dict[str, Any]) -> None:
        sanitized = self._cache._sanitize_assets(assets)
        current_payload = self._select_document(self.STATE_SCOPE_ASSET, job_id)
        owner_user_id = self._job_owner_user_id(job_id)
        pointer_payload = self._asset_pointer_payload(job_id, sanitized)
        self._upsert_document(
            self.STATE_SCOPE_ASSET,
            job_id,
            pointer_payload,
            owner_user_id=owner_user_id,
        )
        self._delete_asset_blob(current_payload)

    def _delete_job_event_records(self, job_id: str) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM job_events WHERE job_id = %s", (job_id,))

    def delete_job(self, job_id: str) -> None:
        with self._lock:
            assets_payload = self._select_document(self.STATE_SCOPE_ASSET, job_id)
            self._delete_asset_blob(assets_payload)
            self._delete_document(self.STATE_SCOPE_JOB, job_id)
            self._delete_document(self.STATE_SCOPE_ASSET, job_id)
            self._delete_job_event_records(job_id)
            self.job_queues.pop(job_id, None)
            subscriber_queues = self.job_stream_subscribers.pop(job_id, [])
            for subscriber_queue in subscriber_queues:
                subscriber_queue.put({"event": self.STREAM_CLOSED_EVENT, "payload": {}})

    def delete_jobs_for_user(self, owner_user_id: str) -> None:
        for job in self.list_jobs(owner_user_id=owner_user_id):
            job_id = str(job.get("id") or "").strip()
            if job_id:
                self.delete_job(job_id)

    def get_assets(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self._resolve_assets_payload(self._select_document(self.STATE_SCOPE_ASSET, job_id))

    def find_task(self, job_id: str, task_id: str, owner_user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        job = self.get_job(job_id, owner_user_id=owner_user_id)
        if not job:
            return None
        for task in job.get("tasks", []):
            if task.get("id") == task_id:
                return deepcopy(task)
        return None

    def get_job_event_cursor(self, job_id: str) -> Optional[str]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT MAX(cursor) FROM job_events WHERE job_id = %s", (job_id,))
            row = cursor.fetchone()
        if not row or row[0] is None:
            return None
        return str(row[0])

    def read_job_events_since(self, job_id: str, cursor: Optional[str]) -> tuple[List[Dict[str, Any]], Optional[str]]:
        normalized_cursor = 0
        if cursor is not None:
            try:
                normalized_cursor = max(0, int(cursor))
            except ValueError:
                normalized_cursor = 0
        with self._connect() as connection, connection.cursor() as db_cursor:
            db_cursor.execute(
                """
                SELECT cursor, event_id, event_name, payload
                FROM job_events
                WHERE job_id = %s AND cursor > %s
                ORDER BY cursor ASC
                """,
                (job_id, normalized_cursor),
            )
            rows = db_cursor.fetchall()
        events: List[Dict[str, Any]] = []
        next_cursor = cursor
        for row in rows:
            next_cursor = str(row[0])
            events.append(
                {
                    "id": str(row[1]),
                    "event": str(row[2]),
                    "payload": self._json_loads(str(row[3])),
                }
            )
        return events, next_cursor

    def publish_job_event(self, job_id: str, event_name: str, payload: Dict[str, Any]) -> None:
        event = {
            "id": uuid.uuid4().hex,
            "event": event_name,
            "payload": payload,
        }
        redis_client = self._redis_client
        with self._lock:
            self._insert_job_event(job_id, event)
            if redis_client is not None:
                self._queue_event_locally(job_id, event, fanout_subscribers=False)
            else:
                self._queue_event_locally(job_id, event, fanout_subscribers=True)
        if redis_client is None:
            return
        try:
            redis_client.publish(
                self._event_channel(job_id),
                self._json_dumps(event),
            )
        except Exception as error:
            LOGGER.warning("Redis publish failed for job event %s/%s: %s", job_id, event_name, error)
            with self._lock:
                for subscriber_queue in list(self.job_stream_subscribers.get(job_id, [])):
                    subscriber_queue.put(deepcopy(event))

    def get_job_queue(self, job_id: str) -> "Queue[Dict[str, Any]]":
        with self._lock:
            return self.job_queues.setdefault(job_id, Queue())

    def subscribe_job_events(self, job_id: str) -> "Queue[Dict[str, Any]]":
        subscriber_queue: "Queue[Dict[str, Any]]" = Queue()
        if self._redis_client is not None:
            pubsub = self._redis_client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(self._event_channel(job_id))
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._pump_redis_events,
                args=(subscriber_queue, pubsub, stop_event),
                daemon=True,
            )
            with self._lock:
                self.job_stream_subscribers.setdefault(job_id, []).append(subscriber_queue)
                self.job_queues.setdefault(job_id, Queue())
                self._redis_listener_controls[id(subscriber_queue)] = (pubsub, stop_event, thread)
            thread.start()
            return subscriber_queue
        with self._lock:
            self.job_stream_subscribers.setdefault(job_id, []).append(subscriber_queue)
            self.job_queues.setdefault(job_id, Queue())
        return subscriber_queue

    def unsubscribe_job_events(self, job_id: str, subscriber_queue: "Queue[Dict[str, Any]]") -> None:
        with self._lock:
            subscribers = self.job_stream_subscribers.setdefault(job_id, [])
            if subscriber_queue in subscribers:
                subscribers.remove(subscriber_queue)
            control = self._redis_listener_controls.pop(id(subscriber_queue), None)
        if control:
            _, stop_event, thread = control
            stop_event.set()
            if thread.is_alive():
                thread.join(timeout=1.0)
        subscriber_queue.put({"event": self.STREAM_CLOSED_EVENT, "payload": {}})

    def create_chat_session(self, session: Dict[str, Any]) -> None:
        with self._lock:
            session_id = str(session["id"])
            self._load_cache_chat_session(session_id)
            self._cache.create_chat_session(session)
            stored = deepcopy(self._cache.chat_sessions[session_id])
            self._upsert_document(
                self.STATE_SCOPE_CHAT_SESSION,
                session_id,
                stored,
                owner_user_id=str(stored.get("owner_user_id") or "").strip() or None,
            )

    def list_chat_sessions(
        self,
        research_job_id: Optional[str] = None,
        owner_user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sessions = self._select_documents(self.STATE_SCOPE_CHAT_SESSION, owner_user_id=owner_user_id)
        if research_job_id is not None:
            sessions = [item for item in sessions if item.get("research_job_id") == research_job_id]
        sessions.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
        return [deepcopy(item) for item in sessions]

    def get_chat_session(self, session_id: str, owner_user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        session = self._select_document(self.STATE_SCOPE_CHAT_SESSION, session_id)
        if not session:
            return None
        if owner_user_id and str(session.get("owner_user_id") or "").strip() != owner_user_id:
            return None
        return deepcopy(session)

    def get_latest_chat_session_for_job(
        self,
        research_job_id: str,
        owner_user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        sessions = self.list_chat_sessions(research_job_id=research_job_id, owner_user_id=owner_user_id)
        return sessions[0] if sessions else None

    def update_chat_session(
        self,
        session_id: str,
        session: Dict[str, Any],
        owner_user_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._load_cache_chat_session(session_id)
            current_session = self._cache.chat_sessions.get(session_id)
            if current_session and owner_user_id and str(current_session.get("owner_user_id") or "").strip() != owner_user_id:
                raise KeyError(session_id)
            self._cache.update_chat_session(session_id, session, owner_user_id=owner_user_id)
            stored = deepcopy(self._cache.chat_sessions[session_id])
            self._upsert_document(
                self.STATE_SCOPE_CHAT_SESSION,
                session_id,
                stored,
                owner_user_id=str(stored.get("owner_user_id") or "").strip() or None,
            )

    def append_chat_message(
        self,
        session_id: str,
        message: Dict[str, Any],
        owner_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            self._load_cache_chat_session(session_id)
            stored_message = self._cache.append_chat_message(session_id, message, owner_user_id=owner_user_id)
            stored = deepcopy(self._cache.chat_sessions[session_id])
            self._upsert_document(
                self.STATE_SCOPE_CHAT_SESSION,
                session_id,
                stored,
                owner_user_id=str(stored.get("owner_user_id") or "").strip() or None,
            )
            return stored_message

    def delete_chat_session(self, session_id: str) -> None:
        self._delete_document(self.STATE_SCOPE_CHAT_SESSION, session_id)

    def delete_chat_sessions_for_user(self, owner_user_id: str) -> None:
        self._delete_documents_for_owner(self.STATE_SCOPE_CHAT_SESSION, owner_user_id)

    def create_user(self, user: Dict[str, Any]) -> None:
        with self._lock:
            user_id = str(user["id"])
            self._load_cache_user(user_id)
            self._cache.create_user(user)
            stored = deepcopy(self._cache.users[user_id])
            self._upsert_document(
                self.STATE_SCOPE_USER,
                user_id,
                stored,
            )

    def update_user(self, user_id: str, user: Dict[str, Any]) -> None:
        with self._lock:
            self._load_cache_user(user_id)
            self._cache.update_user(user_id, user)
            self._upsert_document(self.STATE_SCOPE_USER, user_id, deepcopy(self._cache.users[user_id]))

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        user = self._select_document(self.STATE_SCOPE_USER, user_id)
        return deepcopy(user) if user else None

    def delete_user(self, user_id: str) -> None:
        self._delete_document(self.STATE_SCOPE_USER, user_id)

    def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        normalized_email = str(email or "").strip().lower()
        for user in self.list_users():
            if str(user.get("email") or "").strip().lower() == normalized_email:
                return deepcopy(user)
        return None

    def list_users(self) -> List[Dict[str, Any]]:
        users = self._select_documents(self.STATE_SCOPE_USER)
        users.sort(key=lambda item: item.get("created_at") or "", reverse=False)
        return [deepcopy(item) for item in users]

    def count_users(self) -> int:
        return len(self.list_users())

    def create_auth_session(self, auth_session: Dict[str, Any]) -> None:
        with self._lock:
            token_hash = str(auth_session["token_hash"])
            self._load_cache_auth_session(token_hash)
            self._cache.create_auth_session(auth_session)
            stored = deepcopy(self._cache.auth_sessions[token_hash])
            self._upsert_document(
                self.STATE_SCOPE_AUTH_SESSION,
                token_hash,
                stored,
                owner_user_id=str(stored.get("user_id") or "").strip() or None,
            )

    def get_auth_session(self, token_hash: str) -> Optional[Dict[str, Any]]:
        auth_session = self._select_document(self.STATE_SCOPE_AUTH_SESSION, token_hash)
        return deepcopy(auth_session) if auth_session else None

    def update_auth_session(self, token_hash: str, auth_session: Dict[str, Any]) -> None:
        with self._lock:
            self._load_cache_auth_session(token_hash)
            self._cache.update_auth_session(token_hash, auth_session)
            stored = deepcopy(self._cache.auth_sessions[token_hash])
            self._upsert_document(
                self.STATE_SCOPE_AUTH_SESSION,
                token_hash,
                stored,
                owner_user_id=str(stored.get("user_id") or "").strip() or None,
            )

    def delete_auth_session(self, token_hash: str) -> None:
        self._delete_document(self.STATE_SCOPE_AUTH_SESSION, token_hash)

    def delete_auth_sessions_for_user(self, user_id: str) -> None:
        self._delete_documents_for_owner(self.STATE_SCOPE_AUTH_SESSION, user_id)

    def create_invite(self, invite: Dict[str, Any]) -> None:
        with self._lock:
            invite_id = str(invite["id"])
            self._load_cache_invite(invite_id)
            self._cache.create_invite(invite)
            self._upsert_document(self.STATE_SCOPE_INVITE, invite_id, deepcopy(self._cache.invites[invite_id]))

    def update_invite(self, invite_id: str, invite: Dict[str, Any]) -> None:
        with self._lock:
            self._load_cache_invite(invite_id)
            self._cache.update_invite(invite_id, invite)
            self._upsert_document(self.STATE_SCOPE_INVITE, invite_id, deepcopy(self._cache.invites[invite_id]))

    def get_invite(self, invite_id: str) -> Optional[Dict[str, Any]]:
        invite = self._select_document(self.STATE_SCOPE_INVITE, invite_id)
        return deepcopy(invite) if invite else None

    def list_invites(self, active_only: bool = False) -> List[Dict[str, Any]]:
        invites = self._select_documents(self.STATE_SCOPE_INVITE)
        if active_only:
            invites = [invite for invite in invites if not invite.get("disabled_at") and not invite.get("used_at")]
        invites.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return [deepcopy(item) for item in invites]

    def find_invite_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        normalized_code = str(code or "").strip()
        if not normalized_code:
            return None
        for invite in self.list_invites():
            if str(invite.get("code") or "").strip() != normalized_code:
                continue
            if invite.get("disabled_at") or invite.get("used_at"):
                return None
            return deepcopy(invite)
        return None

    def get_runtime_config(self, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if user_id:
            runtime_config = self._select_document(self.STATE_SCOPE_RUNTIME_CONFIG, user_id)
            if runtime_config:
                return deepcopy(runtime_config)
        runtime_config = self._select_document(self.STATE_SCOPE_RUNTIME_CONFIG, self.GLOBAL_DOCUMENT_ID)
        return deepcopy(runtime_config) if runtime_config else None

    def get_auth_policy(self) -> Optional[Dict[str, Any]]:
        auth_policy = self._select_document(self.STATE_SCOPE_AUTH_POLICY, self.GLOBAL_DOCUMENT_ID)
        return deepcopy(auth_policy) if auth_policy else None

    def delete_runtime_config(self, user_id: str) -> None:
        self._delete_document(self.STATE_SCOPE_RUNTIME_CONFIG, user_id)

    def set_runtime_config(self, runtime_config: Dict[str, Any], user_id: Optional[str] = None) -> None:
        self._upsert_document(
            self.STATE_SCOPE_RUNTIME_CONFIG,
            user_id or self.GLOBAL_DOCUMENT_ID,
            deepcopy(runtime_config),
            owner_user_id=user_id,
        )

    def set_auth_policy(self, auth_policy: Dict[str, Any]) -> None:
        self._upsert_document(
            self.STATE_SCOPE_AUTH_POLICY,
            self.GLOBAL_DOCUMENT_ID,
            deepcopy(auth_policy),
        )

    def supports_background_worker(self) -> bool:
        return self._redis_client is not None

    def enqueue_background_job(self, job_id: str) -> None:
        if self._redis_client is None:
            raise RuntimeError("Flagship background worker mode requires Redis.")
        self._redis_client.rpush(self.REDIS_WORKER_QUEUE_KEY, str(job_id))

    def dequeue_background_job(self, timeout_seconds: float = 1.0) -> Optional[str]:
        if self._redis_client is None:
            return None
        timeout = max(1, int(round(float(timeout_seconds))))
        result = self._redis_client.blpop(self.REDIS_WORKER_QUEUE_KEY, timeout=timeout)
        if not result:
            return None
        _, value = result
        return self._decode_queue_job_id(value)
