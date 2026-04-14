import json
import sys
import threading
import unittest
from pathlib import Path
from queue import Empty, Queue
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
API_SRC = ROOT / "apps" / "api"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from pm_agent_api.repositories.flagship_store import FlagshipStateRepository


class FlagshipRepositoryBehaviourTest(unittest.TestCase):
    def _build_repository(self) -> FlagshipStateRepository:
        repository = FlagshipStateRepository.__new__(FlagshipStateRepository)
        repository._lock = threading.RLock()
        repository.job_queues = {}
        repository.job_stream_subscribers = {}
        repository._redis_listener_controls = {}
        repository._insert_job_event = Mock()
        repository._event_channel = lambda job_id: f"pm-agent:job-events:{job_id}"
        repository._json_dumps = lambda payload: json.dumps(payload, ensure_ascii=False)
        repository._cache = type(
            "CacheStub",
            (),
            {
                "_process_cmdline": staticmethod(lambda pid: ""),
                "_is_detached_worker_running": staticmethod(lambda job: False),
            },
        )()
        repository.update_job = Mock()
        repository.list_jobs = Mock(return_value=[])
        return repository

    def test_publish_job_event_falls_back_to_local_subscribers_when_redis_publish_fails(self) -> None:
        repository = self._build_repository()
        subscriber = Queue()
        repository.job_stream_subscribers["job-1"] = [subscriber]

        class BrokenRedis:
            def publish(self, *_args, **_kwargs):
                raise RuntimeError("redis unavailable")

        repository._redis_client = BrokenRedis()

        repository.publish_job_event("job-1", "job.progress", {"message": "hello"})

        history_event = repository.get_job_queue("job-1").get_nowait()
        subscriber_event = subscriber.get_nowait()

        self.assertEqual(history_event["event"], "job.progress")
        self.assertEqual(subscriber_event["event"], "job.progress")
        self.assertEqual(subscriber_event["payload"]["message"], "hello")

    def test_count_active_detached_workers_does_not_count_unclaimed_shared_worker_jobs(self) -> None:
        repository = self._build_repository()
        repository._redis_client = None
        queued_job = {
            "id": "job-queued",
            "execution_mode": "worker",
            "background_process": {"mode": "worker", "active": True},
        }
        repository.list_jobs = Mock(return_value=[queued_job])

        active_count = repository.count_active_detached_workers()

        self.assertEqual(active_count, 0)
        repository.update_job.assert_not_called()

    def test_count_active_detached_workers_marks_shared_worker_inactive_when_pid_is_dead(self) -> None:
        repository = self._build_repository()
        repository._redis_client = None
        running_job = {
            "id": "job-running",
            "execution_mode": "worker",
            "background_process": {"mode": "worker", "active": True, "worker_pid": 4321},
        }
        repository.list_jobs = Mock(return_value=[running_job])

        with patch("pm_agent_api.repositories.flagship_store.os.kill", side_effect=OSError()):
            active_count = repository.count_active_detached_workers()

        self.assertEqual(active_count, 0)
        self.assertFalse(running_job["background_process"]["active"])
        repository.update_job.assert_called_once_with("job-running", running_job)

    def test_unsubscribe_job_events_closes_stream_without_racing_control_cleanup(self) -> None:
        repository = self._build_repository()
        repository._redis_client = None
        subscriber = repository.subscribe_job_events("job-1")

        repository.unsubscribe_job_events("job-1", subscriber)

        close_event = subscriber.get_nowait()
        self.assertEqual(close_event["event"], repository.STREAM_CLOSED_EVENT)
        with self.assertRaises(Empty):
            subscriber.get_nowait()


if __name__ == "__main__":
    unittest.main()
