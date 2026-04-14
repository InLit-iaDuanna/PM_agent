import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
API_SRC = ROOT / "apps" / "api"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from pm_agent_api.repositories.in_memory_store import InMemoryStateRepository
from pm_agent_api.services.chat_service import ChatService


class _FakeDeltaResult:
    def __init__(self) -> None:
        self.claim = {
            "id": "claim-delta-1",
            "claim_text": "delta claim",
            "market_step": "validation",
            "caveats": [],
        }
        self.evidence = []
        self.follow_up_message = "补研已完成。"


class _FakeBrowser:
    def is_available(self) -> bool:
        return True

    def mode(self) -> str:
        return "fake-browser"


class _FakeSynthesizer:
    def extract_competitors(self, _request_context, _evidence):
        return []


class _FakeDialogue:
    def run_delta_research(self, _job_id, _user_message, _delta_job_id):
        return _FakeDeltaResult()


class _FakeWorkflow:
    def __init__(self) -> None:
        self.browser = _FakeBrowser()
        self.synthesizer = _FakeSynthesizer()
        self.dialogue = _FakeDialogue()

    async def run_delta_research(self, _request_context, _user_message, _delta_job_id, _existing_competitor_names):
        return _FakeDeltaResult()

    def _build_progress_snapshot(self, _job, _assets, _competitor_names):
        return {"status": "ok"}

    def _build_runtime_summary(self):
        return {"engine": "fake"}


def _job_payload(job_id: str) -> dict:
    return {
        "id": job_id,
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


class ChatServiceDeltaEventsTest(unittest.TestCase):
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
        return InMemoryStateRepository()

    def test_delta_research_failed_event_includes_latest_session_payload(self) -> None:
        repository = self._build_repository()
        service = ChatService(repository)
        job_id = "job-failed"
        session_id = "session-failed"
        delta_job_id = "delta-failed-1"

        repository.create_job(_job_payload(job_id))
        repository.set_assets(
            job_id,
            {"claims": [], "evidence": [], "report": {"markdown": "ready"}, "competitors": [], "market_map": {}, "progress_snapshot": {}},
        )
        repository.create_chat_session({"id": session_id, "research_job_id": job_id, "owner_user_id": "user-1", "messages": []})

        service._handle_delta_research_failure(session_id, job_id, delta_job_id, "where is the risk", RuntimeError("boom"))

        queue = repository.get_job_queue(job_id)
        event = queue.get_nowait()
        if event["event"] == "chat.session.updated":
            event = queue.get_nowait()
        payload = event["payload"]
        self.assertEqual(event["event"], "delta_research.failed")
        self.assertEqual(payload["session_id"], session_id)
        self.assertEqual(payload["delta_job_id"], delta_job_id)
        self.assertIn("session", payload)
        self.assertEqual(payload["session"]["id"], session_id)
        self.assertEqual(payload["session"]["messages"][-1]["triggered_delta_job_id"], delta_job_id)
        self.assertEqual(payload["session"]["messages"][-1]["answer_mode"], "delta_failed")
        self.assertIn("失败", payload["message"])
        self.assertIn("boom", payload["error"])

    def test_delta_research_started_and_completed_events_include_session_payload(self) -> None:
        repository = self._build_repository()
        service = ChatService(repository)
        job_id = "job-completed"
        session_id = "session-completed"
        delta_job_id = "delta-completed-1"

        repository.create_job(_job_payload(job_id))
        repository.set_assets(
            job_id,
            {"claims": [], "evidence": [], "report": {"markdown": "ready"}, "competitors": [], "market_map": {}, "progress_snapshot": {}},
        )
        repository.create_chat_session({"id": session_id, "research_job_id": job_id, "owner_user_id": "user-1", "messages": []})
        service._build_workflow_for_job = lambda _job_id: _FakeWorkflow()  # type: ignore[method-assign]

        asyncio.run(service._finish_delta_research(session_id, job_id, delta_job_id, "what changed"))

        queue = repository.get_job_queue(job_id)
        started_event = queue.get_nowait()
        completed_event = queue.get_nowait()
        if completed_event["event"] == "chat.session.updated":
            completed_event = queue.get_nowait()

        self.assertEqual(started_event["event"], "delta_research.started")
        self.assertEqual(started_event["payload"]["session_id"], session_id)
        self.assertEqual(started_event["payload"]["session"]["id"], session_id)
        self.assertEqual(started_event["payload"]["delta_job_id"], delta_job_id)

        payload = completed_event["payload"]
        self.assertEqual(completed_event["event"], "delta_research.completed")
        self.assertEqual(payload["session_id"], session_id)
        self.assertEqual(payload["session"]["id"], session_id)
        self.assertEqual(payload["delta_job_id"], delta_job_id)
        self.assertEqual(payload["claim_id"], "claim-delta-1")
        self.assertEqual(payload["session"]["messages"][-1]["triggered_delta_job_id"], delta_job_id)
        self.assertEqual(payload["session"]["messages"][-1]["answer_mode"], "delta_draft")
        self.assertEqual(payload["draft_version_id"], "job-completed-report-v2")


if __name__ == "__main__":
    unittest.main()
