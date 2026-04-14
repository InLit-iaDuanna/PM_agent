import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from queue import Empty
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
API_SRC = ROOT / "apps" / "api"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from pm_agent_api.repositories.in_memory_store import InMemoryStateRepository
from pm_agent_api.services.research_job_service import ResearchJobService


class StreamFanoutTest(unittest.TestCase):
    def _build_repository(self) -> InMemoryStateRepository:
        state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(state_dir.cleanup)
        env = {
            "PM_AGENT_STATE_DIR": state_dir.name,
            "PM_AGENT_RUNTIME_CONFIG_PATH": str(Path(state_dir.name) / "runtime-config.json"),
        }
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        repository = InMemoryStateRepository()
        repository.create_job(
            {
                "id": "job-1",
                "owner_user_id": "user-1",
                "topic": "AI PM",
                "industry_template": "ai_product",
                "research_mode": "standard",
                "depth_preset": "light",
                "status": "completed",
                "overall_progress": 100,
                "current_phase": "finalizing",
                "eta_seconds": 0,
                "source_count": 0,
                "competitor_count": 0,
                "completed_task_count": 0,
                "running_task_count": 0,
                "failed_task_count": 0,
                "claims_count": 0,
                "report_version_id": None,
                "phase_progress": [],
                "tasks": [],
            }
        )
        return repository

    def test_publish_job_event_fans_out_to_multiple_stream_subscribers(self) -> None:
        repository = self._build_repository()
        subscriber_a = repository.subscribe_job_events("job-1")
        subscriber_b = repository.subscribe_job_events("job-1")

        repository.publish_job_event("job-1", "job.progress", {"job_id": "job-1", "message": "hello"})

        history_event = repository.get_job_queue("job-1").get_nowait()
        event_a = subscriber_a.get_nowait()
        event_b = subscriber_b.get_nowait()

        self.assertEqual(history_event["event"], "job.progress")
        self.assertEqual(event_a["event"], "job.progress")
        self.assertEqual(event_b["event"], "job.progress")
        self.assertEqual(event_a["payload"]["message"], "hello")
        self.assertEqual(event_b["payload"]["message"], "hello")

    def test_unsubscribe_job_events_stops_future_delivery(self) -> None:
        repository = self._build_repository()
        subscriber_a = repository.subscribe_job_events("job-1")
        subscriber_b = repository.subscribe_job_events("job-1")

        repository.unsubscribe_job_events("job-1", subscriber_a)
        repository.publish_job_event("job-1", "job.progress", {"job_id": "job-1", "message": "only-b"})

        close_event = subscriber_a.get_nowait()
        event_b = subscriber_b.get_nowait()

        self.assertEqual(close_event["event"], repository.STREAM_CLOSED_EVENT)
        self.assertEqual(event_b["event"], "job.progress")
        with self.assertRaises(Empty):
            subscriber_a.get_nowait()

    def test_publish_job_event_prunes_old_persisted_history(self) -> None:
        repository = self._build_repository()
        repository.MAX_PERSISTED_JOB_EVENTS = 3

        for index in range(5):
            repository.publish_job_event("job-1", "job.progress", {"job_id": "job-1", "message": f"event-{index}"})

        event_dir = Path(os.environ["PM_AGENT_STATE_DIR"]) / "job_events" / "job-1"
        event_files = sorted(path.name for path in event_dir.glob("*.json"))

        self.assertEqual(len(event_files), 3)
        events, cursor = repository.read_job_events_since("job-1", None)
        self.assertEqual([event["payload"]["message"] for event in events], ["event-2", "event-3", "event-4"])
        self.assertEqual(cursor, event_files[-1])

    def test_repository_refreshes_job_state_written_by_second_repository(self) -> None:
        repository = self._build_repository()
        second_repository = InMemoryStateRepository()

        job = second_repository.get_job("job-1")
        assert job is not None
        job["status"] = "completed"
        job["overall_progress"] = 100
        job["current_phase"] = "finalizing"
        second_repository.update_job("job-1", job)

        refreshed = repository.get_job("job-1")

        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed["status"], "completed")
        self.assertEqual(refreshed["overall_progress"], 100)

    def test_stream_reads_finalize_blocked_event_published_from_second_repository(self) -> None:
        repository = self._build_repository()
        second_repository = InMemoryStateRepository()
        service = ResearchJobService(repository)

        async def capture_event() -> str:
            stream = service.stream("job-1")
            try:
                pending = asyncio.create_task(stream.__anext__())
                await asyncio.sleep(0.1)
                second_repository.publish_job_event(
                    "job-1",
                    "report.finalize_blocked",
                    {"job_id": "job-1", "message": "blocked by quality gate"},
                )
                return await asyncio.wait_for(pending, timeout=2.0)
            finally:
                await stream.aclose()

        chunk = asyncio.run(capture_event())

        self.assertIn("event: report.finalize_blocked", chunk)
        self.assertIn("blocked by quality gate", chunk)

    def test_repository_keeps_active_subprocess_job_running_on_reload(self) -> None:
        repository = self._build_repository()
        job = repository.get_job("job-1")
        assert job is not None
        job["status"] = "researching"
        job["current_phase"] = "collecting"
        job["execution_mode"] = "subprocess"
        job["background_process"] = {
            "pid": 54321,
            "active": True,
            "entrypoint": "pm_agent_api.worker_entry",
        }
        repository.update_job("job-1", job)

        with patch("os.kill", return_value=None), patch.object(
            InMemoryStateRepository,
            "_process_cmdline",
            return_value="python -m pm_agent_api.worker_entry --job-id job-1",
        ):
            reloaded = InMemoryStateRepository()
            refreshed = reloaded.get_job("job-1")

        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed["status"], "researching")

    def test_chat_sessions_refresh_from_disk_and_append_without_losing_messages(self) -> None:
        repository = self._build_repository()
        second_repository = InMemoryStateRepository()

        repository.create_chat_session({"id": "session-1", "research_job_id": "job-1", "owner_user_id": "user-1", "messages": []})

        visible_in_second = second_repository.get_chat_session("session-1")
        self.assertIsNotNone(visible_in_second)

        second_repository.append_chat_message(
            "session-1",
            {"id": "msg-1", "role": "assistant", "content": "first", "created_at": "2026-04-10T00:00:00+00:00"},
        )
        repository.append_chat_message(
            "session-1",
            {"id": "msg-2", "role": "user", "content": "second", "created_at": "2026-04-10T00:00:01+00:00"},
        )

        refreshed = second_repository.get_chat_session("session-1")
        self.assertIsNotNone(refreshed)
        self.assertEqual([message["id"] for message in refreshed["messages"]], ["msg-1", "msg-2"])

    def test_find_task_refreshes_job_from_disk_before_lookup(self) -> None:
        repository = self._build_repository()
        job = repository.get_job("job-1")
        assert job is not None
        job["tasks"] = [
            {
                "id": "task-1",
                "status": "running",
                "source_count": 0,
                "current_url": "https://old.example.com",
                "visited_sources": [{"url": "https://old.example.com"}],
            }
        ]
        repository.update_job("job-1", job)

        second_repository = InMemoryStateRepository()
        updated = second_repository.get_job("job-1")
        assert updated is not None
        updated["tasks"][0]["current_url"] = "https://new.example.com"
        updated["tasks"][0]["visited_sources"] = [{"url": "https://new.example.com"}]
        second_repository.update_job("job-1", updated)

        task = repository.find_task("job-1", "task-1")
        self.assertIsNotNone(task)
        self.assertEqual(task["current_url"], "https://new.example.com")

    def test_runtime_config_reads_latest_from_disk_across_repositories(self) -> None:
        repository = self._build_repository()
        second_repository = InMemoryStateRepository()

        second_repository.set_runtime_config({"provider": "openai_compatible", "model": "gpt-test"})
        self.assertEqual(repository.get_runtime_config(), {"provider": "openai_compatible", "model": "gpt-test"})

        repository.set_runtime_config({"provider": "minimax", "model": "abab-test"})
        self.assertEqual(second_repository.get_runtime_config(), {"provider": "minimax", "model": "abab-test"})

    def test_reconcile_job_counters_uses_task_truth_instead_of_stale_higher_values(self) -> None:
        repository = self._build_repository()
        job = repository.get_job("job-1")
        assert job is not None
        job["status"] = "researching"
        job["source_count"] = 9
        job["completed_task_count"] = 8
        job["running_task_count"] = 7
        job["failed_task_count"] = 6
        job["tasks"] = [
            {"id": "task-1", "status": "completed", "source_count": 2},
            {"id": "task-2", "status": "failed", "source_count": 1},
        ]
        repository.update_job("job-1", job)

        refreshed = repository.get_job("job-1")

        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed["source_count"], 3)
        self.assertEqual(refreshed["completed_task_count"], 1)
        self.assertEqual(refreshed["running_task_count"], 0)
        self.assertEqual(refreshed["failed_task_count"], 1)

    def test_recover_job_sets_failure_fields_consistently(self) -> None:
        repository = self._build_repository()
        job = repository.get_job("job-1")
        assert job is not None
        job["status"] = "researching"
        job["completion_mode"] = "formal"
        job["running_task_count"] = 2
        job["tasks"] = [
            {"id": "task-1", "status": "running", "source_count": 1},
            {"id": "task-2", "status": "queued", "source_count": 0},
        ]
        job["background_process"] = {"pid": 999999, "active": True}
        repository.update_job("job-1", job)

        reloaded = InMemoryStateRepository()
        refreshed = reloaded.get_job("job-1")

        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed["status"], "failed")
        self.assertEqual(refreshed["completion_mode"], "diagnostic")
        self.assertEqual(refreshed["running_task_count"], 0)
        self.assertTrue(refreshed["completed_at"])
        self.assertIn("后台 worker 不再存活", refreshed["latest_error"])
        self.assertEqual([task["status"] for task in refreshed["tasks"]], ["failed", "failed"])
        self.assertFalse(refreshed["background_process"]["active"])


if __name__ == "__main__":
    unittest.main()
