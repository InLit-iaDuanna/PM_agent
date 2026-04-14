import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
API_SRC = ROOT / "apps" / "api"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from pm_agent_api.main import create_app
from pm_agent_api.repositories.in_memory_store import InMemoryStateRepository
from pm_agent_api.services.chat_service import ChatService


class ApiRoutesTest(unittest.TestCase):
    def _build_client(self, extra_env: dict[str, str] | None = None) -> TestClient:
        state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(state_dir.cleanup)
        env = {
            "PM_AGENT_STATE_DIR": state_dir.name,
            "PM_AGENT_RUNTIME_CONFIG_PATH": str(Path(state_dir.name) / "runtime-config.json"),
        }
        if extra_env:
            env.update(extra_env)
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        repository = InMemoryStateRepository()
        app = create_app(repository=repository)
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def _register_and_login(
        self,
        client: TestClient,
        email: str = "owner@example.com",
        password: str = "password123",
        display_name: str = "Owner",
        invite_code: str | None = None,
    ) -> dict:
        payload = {
            "email": email,
            "password": password,
            "display_name": display_name,
        }
        if invite_code is not None:
            payload["invite_code"] = invite_code
        response = client.post(
            "/api/auth/register",
            json=payload,
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["user"]

    def _update_registration_policy(self, client: TestClient, registration_mode: str):
        response = client.post(
            "/api/admin/registration-policy",
            json={"registration_mode": registration_mode},
        )
        return response

    def _job_payload(self, job_id: str, owner_user_id: str, **overrides) -> dict:
        payload = {
            "id": job_id,
            "owner_user_id": owner_user_id,
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
        payload.update(overrides)
        return payload

    def test_root_health_endpoint_returns_ok(self) -> None:
        client = self._build_client()

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"name": "pm-research-agent-api", "status": "ok"})

    def test_api_health_endpoint_returns_runtime_and_worker_summary(self) -> None:
        client = self._build_client()

        response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["active_job_count"], 0)
        self.assertEqual(response.json()["active_detached_worker_count"], 0)
        self.assertFalse(response.json()["runtime_configured"])
        self.assertIn("timestamp", response.json())

    def test_runtime_route_maps_validation_errors_to_bad_request(self) -> None:
        client = self._build_client()
        self._register_and_login(client)

        response = client.post(
            "/api/runtime",
            json={
                "runtime_config": {
                    "provider": "openai_compatible",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-5.4",
                    "timeout_seconds": 3,
                }
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("5 到 180", response.json()["detail"])

    def test_runtime_settings_are_isolated_per_user(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="owner@example.com", password="ownerpass123")

        owner_save = client.post(
            "/api/runtime",
            json={
                "runtime_config": {
                    "provider": "openai_compatible",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-5.4",
                    "api_key": "owner-secret-key",
                    "timeout_seconds": 45,
                }
            },
        )
        self.assertEqual(owner_save.status_code, 200)
        self.assertEqual(owner_save.json()["source"], "saved")
        client.post("/api/auth/logout")

        self._register_and_login(client, email="member@example.com", password="memberpass123")
        member_initial_status = client.get("/api/runtime")
        self.assertEqual(member_initial_status.status_code, 200)
        self.assertNotEqual(member_initial_status.json()["source"], "saved")

        member_save = client.post(
            "/api/runtime",
            json={
                "runtime_config": {
                    "provider": "openai_compatible",
                    "base_url": "https://api.deepseek.com/v1",
                    "model": "deepseek-chat",
                    "api_key": "member-secret-key",
                    "timeout_seconds": 30,
                }
            },
        )
        self.assertEqual(member_save.status_code, 200)
        self.assertEqual(member_save.json()["source"], "saved")
        client.post("/api/auth/logout")

        relogin_owner = client.post(
            "/api/auth/login",
            json={
                "email": "owner@example.com",
                "password": "ownerpass123",
            },
        )
        self.assertEqual(relogin_owner.status_code, 200)
        owner_status = client.get("/api/runtime")
        self.assertEqual(owner_status.status_code, 200)
        self.assertEqual(owner_status.json()["source"], "saved")
        self.assertEqual(owner_status.json()["base_url"], "https://api.openai.com/v1")
        self.assertEqual(owner_status.json()["model"], "gpt-5.4")
        self.assertEqual(owner_status.json()["timeout_seconds"], 45.0)
        client.post("/api/auth/logout")

        relogin_member = client.post(
            "/api/auth/login",
            json={
                "email": "member@example.com",
                "password": "memberpass123",
            },
        )
        self.assertEqual(relogin_member.status_code, 200)
        member_status = client.get("/api/runtime")
        self.assertEqual(member_status.status_code, 200)
        self.assertEqual(member_status.json()["source"], "saved")
        self.assertEqual(member_status.json()["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(member_status.json()["model"], "deepseek-chat")
        self.assertEqual(member_status.json()["timeout_seconds"], 30.0)

    def test_start_research_job_records_background_worker_log_path(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client)

        with patch("pm_agent_api.services.research_job_service.ResearchJobService._spawn_job_process") as spawn_job_process:
            process = type("Process", (), {"pid": 45678})()
            log_path = Path(os.environ["PM_AGENT_STATE_DIR"]) / "worker_logs" / "job-start.log"
            spawn_job_process.return_value = (process, log_path)

            response = client.post(
                "/api/research-jobs",
                json={
                    "topic": "AI PM",
                    "industry_template": "ai_product",
                    "research_mode": "standard",
                    "depth_preset": "light",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["background_process"]["pid"], 45678)
        self.assertEqual(payload["background_process"]["log_path"], str(log_path))
        self.assertEqual(payload["owner_user_id"], user["id"])
        self.assertIsInstance(payload["quality_score_summary"], dict)

    def test_start_research_job_inherits_runtime_profile_metadata(self) -> None:
        client = self._build_client()
        self._register_and_login(client)

        save_response = client.post(
            "/api/runtime",
            json={
                "runtime_config": {
                    "profile_id": "premium_default",
                    "provider": "openai_compatible",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-5.4",
                    "api_key": "owner-secret-key",
                    "timeout_seconds": 60,
                    "retrieval_profile": {
                        "profile_id": "premium_default",
                    },
                    "quality_policy": {
                        "profile_id": "premium_default",
                    },
                }
            },
        )
        self.assertEqual(save_response.status_code, 200)

        with patch("pm_agent_api.services.research_job_service.ResearchJobService._spawn_job_process") as spawn_job_process:
            process = type("Process", (), {"pid": 56789})()
            log_path = Path(os.environ["PM_AGENT_STATE_DIR"]) / "worker_logs" / "job-profile.log"
            spawn_job_process.return_value = (process, log_path)

            response = client.post(
                "/api/research-jobs",
                json={
                    "topic": "Runtime profile propagation",
                    "industry_template": "ai_product",
                    "research_mode": "standard",
                    "depth_preset": "light",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["retrieval_profile_id"], "premium_default")
        self.assertEqual(payload["quality_score_summary"]["profile_id"], "premium_default")
        self.assertEqual(payload["quality_score_summary"]["retrieval_profile_id"], "premium_default")
        self.assertEqual(payload["quality_score_summary"]["quality_policy_id"], "premium_default")

    def test_research_job_route_returns_not_found_for_missing_job(self) -> None:
        client = self._build_client()
        self._register_and_login(client)

        response = client.get("/api/research-jobs/missing-job")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Research job not found")

    def test_cancel_research_job_route_marks_job_cancelled_and_publishes_event(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client)
        repository = client.app.state.repository
        repository.create_job(
            self._job_payload(
                "job-cancel",
                user["id"],
                status="researching",
                overall_progress=42,
                current_phase="collecting",
                eta_seconds=600,
                source_count=2,
                running_task_count=1,
                cancel_requested=False,
                cancellation_reason=None,
                latest_error=None,
                execution_mode="subprocess",
                background_process={"pid": 43210, "active": True},
            )
        )
        repository.set_assets(
            "job-cancel",
            {
                "claims": [],
                "evidence": [],
                "report": {"markdown": "", "generated_at": "2026-04-06T00:00:00+00:00"},
                "competitors": [],
                "market_map": {},
                "progress_snapshot": {},
            },
        )

        with patch.object(repository, "_is_detached_worker_running", return_value=True):
            response = client.post("/api/research-jobs/job-cancel/cancel", json={"reason": "手动停止"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertTrue(response.json()["cancel_requested"])
        self.assertEqual(response.json()["cancellation_reason"], "手动停止")
        event = repository.get_job_queue("job-cancel").get_nowait()
        self.assertEqual(event["event"], "job.cancelled")
        self.assertEqual(event["payload"]["job"]["status"], "cancelled")

    def test_stream_route_returns_not_found_for_missing_job(self) -> None:
        client = self._build_client()
        self._register_and_login(client)

        response = client.get("/api/stream/jobs/missing-job")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Research job not found")

    def test_chat_sessions_route_can_list_sessions_for_existing_job(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client)
        client.app.state.repository.create_job(self._job_payload("job-1", user["id"]))

        response = client.get("/api/chat/sessions", params={"research_job_id": "job-1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_cors_allows_loopback_origins_by_default(self) -> None:
        client = self._build_client()

        response = client.options(
            "/api/runtime",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:3000")
        self.assertEqual(response.headers.get("access-control-allow-credentials"), "true")

    def test_cors_blocks_unlisted_cross_site_origins(self) -> None:
        client = self._build_client()

        response = client.options(
            "/api/runtime",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_cors_accepts_explicit_custom_origin_from_env(self) -> None:
        client = self._build_client({"PM_AGENT_CORS_ORIGINS": "https://pm.internal.example"})

        response = client.options(
            "/api/runtime",
            headers={
                "Origin": "https://pm.internal.example",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "https://pm.internal.example")

    def test_send_message_persists_delta_placeholder_before_background_thread_runs(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client)
        repository = client.app.state.repository
        repository.create_job(
            self._job_payload(
                "job-1",
                user["id"],
                source_count=1,
                completed_task_count=1,
                claims_count=1,
                report_version_id="job-1-report-v1",
            )
        )
        repository.set_assets(
            "job-1",
            {
                "claims": [],
                "evidence": [],
                "report": {"markdown": "## Executive Summary\n- Initial report", "generated_at": "2026-03-30T00:00:00+00:00"},
                "competitors": [],
                "market_map": {},
                "progress_snapshot": {},
            },
        )
        repository.create_chat_session({"id": "session-1", "research_job_id": "job-1", "owner_user_id": user["id"], "messages": []})

        service = ChatService(repository)
        observed_sessions: list[dict] = []

        class DummyDialogue:
            @staticmethod
            def build_response(*args, **kwargs):
                return {
                    "content": "需要补充研究。",
                    "cited_claim_ids": [],
                    "needs_delta_research": True,
                }

        class DummyWorkflow:
            dialogue = DummyDialogue()

        class ImmediateThread:
            def __init__(self, target, args=(), daemon=None):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        with patch.object(service, "_build_workflow_for_job", return_value=DummyWorkflow()):
            with patch("pm_agent_api.services.chat_service.threading.Thread", ImmediateThread):
                with patch.object(
                    service,
                    "_finish_delta_research_sync",
                    side_effect=lambda session_id, *_args: observed_sessions.append(repository.get_chat_session(session_id) or {}),
                ):
                    asyncio.run(service.send_message("session-1", "下一步怎么办？", user["id"]))

        self.assertEqual(len(observed_sessions), 1)
        self.assertEqual([message["role"] for message in observed_sessions[0]["messages"]], ["user", "assistant"])
        self.assertTrue(observed_sessions[0]["messages"][-1]["triggered_delta_job_id"])
        event = repository.get_job_queue("job-1").get_nowait()
        self.assertEqual(event["event"], "chat.session.updated")
        self.assertEqual(event["payload"]["session"]["messages"][-1]["triggered_delta_job_id"], observed_sessions[0]["messages"][-1]["triggered_delta_job_id"])

    def test_send_message_publishes_chat_session_update_without_delta_research(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client)
        repository = client.app.state.repository
        repository.create_job(
            self._job_payload(
                "job-plain",
                user["id"],
                source_count=1,
                completed_task_count=1,
                claims_count=1,
                report_version_id="job-plain-report-v1",
            )
        )
        repository.set_assets(
            "job-plain",
            {
                "claims": [],
                "evidence": [],
                "report": {"markdown": "## Executive Summary\n- Initial report", "generated_at": "2026-03-30T00:00:00+00:00"},
                "competitors": [],
                "market_map": {},
                "progress_snapshot": {},
            },
        )
        repository.create_chat_session({"id": "session-plain", "research_job_id": "job-plain", "owner_user_id": user["id"], "messages": []})

        service = ChatService(repository)

        class DummyDialogue:
            @staticmethod
            def build_response(*args, **kwargs):
                return {
                    "content": "这里是直接回复。",
                    "cited_claim_ids": [],
                    "needs_delta_research": False,
                }

        class DummyWorkflow:
            dialogue = DummyDialogue()

        with patch.object(service, "_build_workflow_for_job", return_value=DummyWorkflow()):
            asyncio.run(service.send_message("session-plain", "给我一个结论", user["id"]))

        event = repository.get_job_queue("job-plain").get_nowait()
        self.assertEqual(event["event"], "chat.session.updated")
        self.assertEqual(event["payload"]["session_id"], "session-plain")
        self.assertEqual([message["role"] for message in event["payload"]["session"]["messages"]], ["user", "assistant"])
        self.assertEqual(event["payload"]["session"]["messages"][-1]["content"], "这里是直接回复。")

    def test_send_message_route_returns_report_pending_metadata_before_report_exists(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client)
        repository = client.app.state.repository
        repository.create_job(
            self._job_payload(
                "job-pending",
                user["id"],
                report_version_id="job-pending-report-v1",
                active_report_version_id="job-pending-report-v1",
                stable_report_version_id=None,
            )
        )
        repository.set_assets(
            "job-pending",
            {
                "claims": [],
                "evidence": [],
                "report": {"markdown": "", "generated_at": "2026-03-30T00:00:00+00:00"},
                "competitors": [],
                "market_map": {},
                "progress_snapshot": {},
            },
        )
        repository.create_chat_session({"id": "session-pending", "research_job_id": "job-pending", "owner_user_id": user["id"], "messages": []})

        response = client.post("/api/chat/sessions/session-pending/messages", json={"content": "可以回答了吗？"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["answer_mode"], "report_pending")
        self.assertEqual(payload["draft_version_id"], "job-pending-report-v1")
        self.assertTrue(payload["requires_finalize"])
        self.assertEqual(payload["message"]["answer_mode"], "report_pending")

    def test_send_message_route_returns_answer_metadata(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client)
        repository = client.app.state.repository
        repository.create_job(
            self._job_payload(
                "job-meta",
                user["id"],
                source_count=1,
                completed_task_count=1,
                claims_count=1,
                report_version_id="job-meta-report-v2",
                active_report_version_id="job-meta-report-v3",
                stable_report_version_id="job-meta-report-v2",
            )
        )
        repository.set_assets(
            "job-meta",
            {
                "claims": [],
                "evidence": [],
                "report": {"markdown": "## Executive Summary\n- Initial report", "generated_at": "2026-03-30T00:00:00+00:00"},
                "competitors": [],
                "market_map": {},
                "progress_snapshot": {},
                "report_versions": [],
            },
        )
        repository.create_chat_session({"id": "session-meta", "research_job_id": "job-meta", "owner_user_id": user["id"], "messages": []})

        class DummyDialogue:
            @staticmethod
            def build_response(*args, **kwargs):
                return {
                    "content": "这里是直接回复。",
                    "cited_claim_ids": ["claim-1"],
                    "needs_delta_research": False,
                }

        class DummyWorkflow:
            dialogue = DummyDialogue()

        with patch.object(client.app.state.chat_service, "_build_workflow_for_job", return_value=DummyWorkflow()):
            response = client.post("/api/chat/sessions/session-meta/messages", json={"content": "给我一个结论"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["answer_mode"], "report_context")
        self.assertEqual(payload["draft_version_id"], "job-meta-report-v3")
        self.assertTrue(payload["requires_finalize"])
        self.assertEqual(payload["message"]["answer_mode"], "report_context")
        self.assertEqual(payload["message"]["draft_version_id"], "job-meta-report-v3")
        self.assertTrue(payload["message"]["requires_finalize"])

    def test_finalize_report_from_source_version_and_fetch_diff_route(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client)
        repository = client.app.state.repository
        repository.create_job(
            self._job_payload(
                "job-finalize",
                user["id"],
                source_count=3,
                completed_task_count=1,
                claims_count=1,
                report_version_id="job-finalize-report-v1",
                active_report_version_id="job-finalize-report-v1",
                stable_report_version_id=None,
            )
        )
        repository.set_assets(
            "job-finalize",
            {
                "claims": [
                    {
                        "id": "claim-1",
                        "claim_text": "应先验证核心转化路径。",
                        "market_step": "recommendations",
                        "confidence": 0.8,
                        "status": "verified",
                        "priority": "high",
                        "actionability_score": 0.9,
                        "caveats": [],
                        "evidence_ids": ["e1", "e2"],
                    }
                ],
                "evidence": [
                    {
                        "id": "e1",
                        "task_id": "task-1",
                        "market_step": "recommendations",
                        "confidence": 0.74,
                        "authority_score": 0.72,
                        "freshness_score": 0.8,
                        "source_url": "https://example.com/research",
                        "source_domain": "example.com",
                        "source_type": "article",
                        "title": "Research summary",
                        "summary": "验证核心转化更重要。",
                        "quote": "validate conversion path first",
                        "captured_at": "2026-03-30T00:00:00+00:00",
                        "extracted_fact": "先验证转化路径。",
                        "injection_risk": 0.0,
                        "tags": ["recommendations"],
                        "competitor_name": None,
                    },
                    {
                        "id": "e2",
                        "task_id": "task-1",
                        "market_step": "recommendations",
                        "confidence": 0.71,
                        "authority_score": 0.76,
                        "freshness_score": 0.74,
                        "source_url": "https://insights.example.org/pm-notes",
                        "source_domain": "insights.example.org",
                        "source_type": "analysis",
                        "title": "PM execution notes",
                        "summary": "先验证付费意愿更稳妥。",
                        "quote": "validate willingness to pay",
                        "captured_at": "2026-03-30T00:00:00+00:00",
                        "extracted_fact": "先验证付费意愿。",
                        "injection_risk": 0.0,
                        "tags": ["recommendations"],
                        "competitor_name": None,
                    },
                    {
                        "id": "e3",
                        "task_id": "task-1",
                        "market_step": "user-research",
                        "confidence": 0.67,
                        "authority_score": 0.69,
                        "freshness_score": 0.7,
                        "source_url": "https://signals.example.net/interviews",
                        "source_domain": "signals.example.net",
                        "source_type": "report",
                        "title": "Interview summary",
                        "summary": "用户更关注可衡量闭环。",
                        "quote": "users want measurable loops",
                        "captured_at": "2026-03-30T00:00:00+00:00",
                        "extracted_fact": "用户重视可衡量闭环。",
                        "injection_risk": 0.0,
                        "tags": ["user-research"],
                        "competitor_name": None,
                    },
                ],
                "report": {
                    "markdown": "## Executive Summary\n- Draft report",
                    "generated_at": "2026-03-30T00:00:00+00:00",
                    "updated_at": "2026-03-30T00:00:00+00:00",
                    "stage": "feedback_pending",
                    "feedback_count": 1,
                    "feedback_notes": [
                        {
                            "question": "请把重点放在先验证付费意愿",
                            "response": "已记录",
                            "action": "等待显式最终成文",
                            "created_at": "2026-03-30T00:01:00+00:00",
                        }
                    ],
                },
                "competitors": [],
                "market_map": {},
                "progress_snapshot": {},
                "report_versions": [
                    {
                        "version_id": "job-finalize-report-v1",
                        "version_number": 1,
                        "label": "初稿",
                        "stage": "feedback_pending",
                        "kind": "draft",
                        "markdown": "## Executive Summary\n- Draft report",
                        "generated_at": "2026-03-30T00:00:00+00:00",
                        "updated_at": "2026-03-30T00:00:00+00:00",
                        "claim_ids": ["claim-1"],
                        "evidence_ids": ["e1", "e2", "e3"],
                        "source_domains": ["example.com", "insights.example.org", "signals.example.net"],
                    }
                ],
            },
        )

        finalize_response = client.post(
            "/api/research-jobs/job-finalize/finalize-report",
            json={"source_version_id": "job-finalize-report-v1"},
        )

        self.assertEqual(finalize_response.status_code, 200)
        finalize_payload = finalize_response.json()
        self.assertEqual(finalize_payload["report"]["stage"], "final")
        self.assertEqual(finalize_payload["report_versions"][-1]["parent_version_id"], "job-finalize-report-v1")
        self.assertEqual(finalize_payload["report_versions"][-1]["kind"], "final")
        self.assertEqual(finalize_payload["report_versions"][-1]["quality_gate"]["passed"], True)
        job = repository.get_job("job-finalize")
        self.assertEqual(job["active_report_version_id"], "job-finalize-report-v2")
        self.assertEqual(job["stable_report_version_id"], "job-finalize-report-v2")

        diff_response = client.get(
            "/api/research-jobs/job-finalize/report-versions/job-finalize-report-v2/diff/job-finalize-report-v1"
        )

        self.assertEqual(diff_response.status_code, 200)
        diff_payload = diff_response.json()
        self.assertEqual(diff_payload["job_id"], "job-finalize")
        self.assertEqual(diff_payload["version_id"], "job-finalize-report-v2")
        self.assertEqual(diff_payload["base_version_id"], "job-finalize-report-v1")
        self.assertIn("新增结论", diff_payload["summary"])
        self.assertIn("diff_markdown", diff_payload)

        missing_diff_response = client.get(
            "/api/research-jobs/job-finalize/report-versions/job-finalize-report-v2/diff/missing-version"
        )
        self.assertEqual(missing_diff_response.status_code, 404)

    def test_get_assets_route_backfills_legacy_competitors(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client)
        repository = client.app.state.repository
        repository.create_job(
            self._job_payload(
                "job-legacy-competitors",
                user["id"],
                topic="AI眼镜",
                source_count=3,
                max_competitors=6,
            )
        )
        repository.set_assets(
            "job-legacy-competitors",
            {
                "claims": [],
                "evidence": [
                    {
                        "id": "legacy-e1",
                        "task_id": "task-1",
                        "market_step": "market-trends",
                        "confidence": 0.82,
                        "authority_score": 0.91,
                        "freshness_score": 0.79,
                        "source_url": "https://www.meta.com/ai-glasses",
                        "source_domain": "meta.com",
                        "source_type": "web",
                        "source_tier": "t1",
                        "title": "Ray-Ban Meta 官方产品页",
                        "summary": "Ray-Ban Meta 主打拍照与语音助手。",
                        "quote": "Ray-Ban Meta focuses on capture and AI assistance.",
                        "captured_at": "2026-04-11T00:00:00+00:00",
                        "extracted_fact": "Ray-Ban Meta 已形成日常佩戴型 AI 眼镜路线。",
                        "injection_risk": 0.0,
                        "tags": ["official"],
                        "competitor_name": None,
                    },
                    {
                        "id": "legacy-e2",
                        "task_id": "task-1",
                        "market_step": "user-research",
                        "confidence": 0.79,
                        "authority_score": 0.85,
                        "freshness_score": 0.76,
                        "source_url": "https://global.rokid.com/",
                        "source_domain": "rokid.com",
                        "source_type": "web",
                        "source_tier": "t1",
                        "title": "Rokid AI Glasses - Redefining Reality",
                        "summary": "Rokid 主打轻量化、翻译与拍摄功能。",
                        "quote": "Rokid introduces a lighter AI glasses line.",
                        "captured_at": "2026-04-11T00:00:00+00:00",
                        "extracted_fact": "Rokid 正在用轻量 AI 眼镜切入市场。",
                        "injection_risk": 0.0,
                        "tags": ["official"],
                        "competitor_name": None,
                    },
                    {
                        "id": "legacy-e3",
                        "task_id": "task-1",
                        "market_step": "pricing",
                        "confidence": 0.76,
                        "authority_score": 0.83,
                        "freshness_score": 0.77,
                        "source_url": "https://www.mi.com/prod/xiaomi-ai-glasses",
                        "source_domain": "mi.com",
                        "source_type": "pricing",
                        "source_tier": "t1",
                        "title": "小米AI眼镜",
                        "summary": "小米AI眼镜售价 1999 元起。",
                        "quote": "小米AI眼镜售价 1999 元起。",
                        "captured_at": "2026-04-11T00:00:00+00:00",
                        "extracted_fact": "小米把 AI 眼镜作为下一代个人智能设备切入。",
                        "injection_risk": 0.0,
                        "tags": ["pricing"],
                        "competitor_name": None,
                    },
                ],
                "report": {
                    "markdown": "## Executive Summary\n- Draft report",
                    "generated_at": "2026-04-11T00:00:00+00:00",
                    "updated_at": "2026-04-11T00:00:00+00:00",
                    "stage": "draft",
                    "feedback_count": 0,
                    "feedback_notes": [],
                },
                "competitors": [],
                "market_map": {},
                "progress_snapshot": {},
            },
        )

        response = client.get("/api/research-jobs/job-legacy-competitors/assets")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        competitor_names = [item["name"] for item in payload["competitors"]]
        self.assertIn("Ray-Ban Meta", competitor_names)
        self.assertIn("Rokid", competitor_names)
        self.assertIn("小米", competitor_names)
        self.assertEqual(payload["evidence"][0]["competitor_name"], "Ray-Ban Meta")
        self.assertEqual(payload["evidence"][1]["competitor_name"], "Rokid")
        self.assertEqual(payload["evidence"][2]["competitor_name"], "小米")

        persisted_assets = repository.get_assets("job-legacy-competitors")
        persisted_job = repository.get_job("job-legacy-competitors")
        self.assertTrue(persisted_assets["competitors"])
        self.assertEqual(persisted_assets["evidence"][0]["competitor_name"], "Ray-Ban Meta")
        self.assertGreaterEqual(int(persisted_job["competitor_count"]), 3)

    def test_delta_failure_event_includes_latest_session_payload(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client)
        repository = client.app.state.repository
        repository.create_job(
            self._job_payload(
                "job-1",
                user["id"],
                report_version_id="job-1-report-v1",
            )
        )
        repository.set_assets(
            "job-1",
            {
                "claims": [],
                "evidence": [],
                "report": {"markdown": "## Executive Summary\n- Initial report", "generated_at": "2026-03-30T00:00:00+00:00"},
                "competitors": [],
                "market_map": {},
                "progress_snapshot": {},
            },
        )
        repository.create_chat_session({"id": "session-1", "research_job_id": "job-1", "owner_user_id": user["id"], "messages": []})

        service = ChatService(repository)
        service._handle_delta_research_failure("session-1", "job-1", "delta-1", "下一步怎么办？", RuntimeError("delta exploded"))

        queue = repository.get_job_queue("job-1")
        event = queue.get_nowait()
        if event["event"] == "chat.session.updated":
            event = queue.get_nowait()

        self.assertEqual(event["event"], "delta_research.failed")
        self.assertEqual(event["payload"]["session_id"], "session-1")
        self.assertEqual(event["payload"]["session"]["id"], "session-1")
        self.assertEqual(event["payload"]["session"]["messages"][-1]["triggered_delta_job_id"], "delta-1")

    def test_auth_register_me_logout_cycle(self) -> None:
        client = self._build_client()

        register_response = client.post(
            "/api/auth/register",
            json={
                "email": "pm@example.com",
                "password": "password123",
                "display_name": "PM Team",
            },
        )

        self.assertEqual(register_response.status_code, 200)
        self.assertEqual(register_response.json()["user"]["email"], "pm@example.com")
        self.assertEqual(register_response.json()["user"]["role"], "admin")
        self.assertIn("pm_agent_session", client.cookies)

        me_response = client.get("/api/auth/me")
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["display_name"], "PM Team")

        logout_response = client.post("/api/auth/logout")
        self.assertEqual(logout_response.status_code, 200)
        self.assertEqual(logout_response.json()["ok"], True)

        me_after_logout = client.get("/api/auth/me")
        self.assertEqual(me_after_logout.status_code, 401)

    def test_auth_public_config_reports_registration_policy(self) -> None:
        client = self._build_client({"PM_AGENT_ALLOW_PUBLIC_REGISTRATION": "false", "PM_AGENT_REGISTRATION_INVITE_CODE": "hello-invite"})

        response = client.get("/api/auth/public-config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["registration_enabled"], True)
        self.assertEqual(response.json()["invite_code_required"], True)
        self.assertEqual(response.json()["first_user_will_be_admin"], True)
        self.assertEqual(response.json()["registration_mode"], "bootstrap")

    def test_registration_requires_invite_code_when_configured(self) -> None:
        client = self._build_client({"PM_AGENT_REGISTRATION_INVITE_CODE": "hello-invite"})

        invalid_response = client.post(
            "/api/auth/register",
            json={
                "email": "pm@example.com",
                "password": "password123",
                "display_name": "PM",
                "invite_code": "wrong",
            },
        )
        self.assertEqual(invalid_response.status_code, 403)
        self.assertEqual(invalid_response.json()["detail"], "邀请码不正确。")

        valid_response = client.post(
            "/api/auth/register",
            json={
                "email": "pm@example.com",
                "password": "password123",
                "display_name": "PM",
                "invite_code": "hello-invite",
            },
        )
        self.assertEqual(valid_response.status_code, 200)
        self.assertEqual(valid_response.json()["user"]["role"], "admin")

    def test_registration_can_be_closed_after_first_user(self) -> None:
        client = self._build_client({"PM_AGENT_ALLOW_PUBLIC_REGISTRATION": "false"})

        first_user = self._register_and_login(client, email="admin@example.com")
        self.assertEqual(first_user["role"], "admin")
        client.post("/api/auth/logout")

        response = client.post(
            "/api/auth/register",
            json={
                "email": "member@example.com",
                "password": "password123",
                "display_name": "Member",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "当前已关闭公开注册，请联系管理员。")

    def test_admin_can_list_users(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com")
        client.post("/api/auth/logout")
        self._register_and_login(client, email="member@example.com")
        login_response = client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.com",
                "password": "password123",
            },
        )
        self.assertEqual(login_response.status_code, 200)

        response = client.get("/api/admin/users")

        self.assertEqual(response.status_code, 200)
        emails = {user["email"] for user in response.json()}
        self.assertIn("admin@example.com", emails)
        self.assertIn("member@example.com", emails)

    def test_non_admin_cannot_list_users(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com")
        client.post("/api/auth/logout")
        self._register_and_login(client, email="member@example.com")

        response = client.get("/api/admin/users")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "只有管理员可以执行这个操作。")

    def test_admin_can_create_invite_and_registration_requires_code(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com")

        create_response = client.post("/api/admin/invites", json={"note": "invite test"})
        self.assertEqual(create_response.status_code, 200)
        invite = create_response.json()
        self.assertTrue(invite["active"])
        self.assertEqual(invite["note"], "invite test")
        self.assertEqual(invite["issued_by_email"], "admin@example.com")

        client.post("/api/auth/logout")
        missing_response = client.post(
            "/api/auth/register",
            json={
                "email": "member@example.com",
                "password": "password123",
                "display_name": "Member",
            },
        )
        self.assertEqual(missing_response.status_code, 403)
        self.assertEqual(missing_response.json()["detail"], "邀请码不正确。")

        valid_response = client.post(
            "/api/auth/register",
            json={
                "email": "member@example.com",
                "password": "password123",
                "display_name": "Member",
                "invite_code": invite["code"],
            },
        )
        self.assertEqual(valid_response.status_code, 200)
        self.assertEqual(valid_response.json()["user"]["email"], "member@example.com")

    def test_admin_can_disable_invite_and_prevents_registration(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com")

        client.post("/api/admin/invites", json={"note": "keep"}).json()
        invite = client.post("/api/admin/invites", json={"note": "revoke"}).json()
        disable_response = client.post(f"/api/admin/invites/{invite['id']}/disable")
        self.assertEqual(disable_response.status_code, 200)
        self.assertFalse(disable_response.json()["active"])

        client.post("/api/auth/logout")
        invalid_response = client.post(
            "/api/auth/register",
            json={
                "email": "member@example.com",
                "password": "password123",
                "display_name": "Member",
                "invite_code": invite["code"],
            },
        )
        self.assertEqual(invalid_response.status_code, 403)
        self.assertEqual(invalid_response.json()["detail"], "邀请码不正确。")

    def test_admin_can_switch_registration_policy_to_closed_and_block_new_signup(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com", password="adminpass123")

        update_response = self._update_registration_policy(client, "closed")
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["registration_mode"], "closed")
        self.assertEqual(update_response.json()["configured_registration_mode"], "closed")

        public_config_response = client.get("/api/auth/public-config")
        self.assertEqual(public_config_response.status_code, 200)
        self.assertEqual(public_config_response.json()["registration_mode"], "closed")
        self.assertEqual(public_config_response.json()["registration_mode_source"], "admin_override")

        client.post("/api/auth/logout")
        register_response = client.post(
            "/api/auth/register",
            json={
                "email": "member@example.com",
                "password": "memberpass123",
                "display_name": "Member",
            },
        )

        self.assertEqual(register_response.status_code, 403)
        self.assertEqual(register_response.json()["detail"], "当前已关闭公开注册，请联系管理员。")

    def test_admin_can_switch_registration_policy_to_open_even_when_public_default_is_closed(self) -> None:
        client = self._build_client({"PM_AGENT_ALLOW_PUBLIC_REGISTRATION": "false"})
        self._register_and_login(client, email="admin@example.com", password="adminpass123")

        update_response = self._update_registration_policy(client, "open")
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["registration_mode"], "open")
        self.assertEqual(update_response.json()["configured_registration_mode"], "open")

        public_config_response = client.get("/api/auth/public-config")
        self.assertEqual(public_config_response.status_code, 200)
        self.assertEqual(public_config_response.json()["registration_enabled"], True)
        self.assertEqual(public_config_response.json()["registration_mode"], "open")
        self.assertEqual(public_config_response.json()["registration_mode_source"], "admin_override")

        client.post("/api/auth/logout")
        register_response = client.post(
            "/api/auth/register",
            json={
                "email": "member@example.com",
                "password": "memberpass123",
                "display_name": "Member",
            },
        )

        self.assertEqual(register_response.status_code, 200)
        self.assertEqual(register_response.json()["user"]["email"], "member@example.com")
        self.assertEqual(register_response.json()["user"]["role"], "member")

    def test_admin_can_switch_registration_policy_to_invite_only_and_invite_is_required(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com", password="adminpass123")

        update_response = self._update_registration_policy(client, "invite_only")
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["registration_mode"], "invite_only")
        self.assertEqual(update_response.json()["configured_registration_mode"], "invite_only")
        self.assertEqual(update_response.json()["invite_code_required"], True)

        client.post("/api/auth/logout")
        missing_invite_response = client.post(
            "/api/auth/register",
            json={
                "email": "member@example.com",
                "password": "memberpass123",
                "display_name": "Member",
            },
        )
        self.assertEqual(missing_invite_response.status_code, 403)
        self.assertEqual(missing_invite_response.json()["detail"], "邀请码不正确。")

        admin_login_response = client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.com",
                "password": "adminpass123",
            },
        )
        self.assertEqual(admin_login_response.status_code, 200)
        invite_response = client.post("/api/admin/invites", json={"note": "invite only signup"})
        self.assertEqual(invite_response.status_code, 200)

        client.post("/api/auth/logout")
        register_response = client.post(
            "/api/auth/register",
            json={
                "email": "member@example.com",
                "password": "memberpass123",
                "display_name": "Member",
                "invite_code": invite_response.json()["code"],
            },
        )

        self.assertEqual(register_response.status_code, 200)
        self.assertEqual(register_response.json()["user"]["email"], "member@example.com")

    def test_non_admin_cannot_update_registration_policy(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com", password="adminpass123")
        client.post("/api/auth/logout")
        self._register_and_login(client, email="member@example.com", password="memberpass123")

        update_response = self._update_registration_policy(client, "closed")

        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(update_response.json()["detail"], "只有管理员可以执行这个操作。")

    def test_admin_can_promote_member_to_admin(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com")
        client.post("/api/auth/logout")
        member = self._register_and_login(client, email="member@example.com")
        login_response = client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.com",
                "password": "password123",
            },
        )
        self.assertEqual(login_response.status_code, 200)

        promote_response = client.post(
            f"/api/admin/users/{member['id']}/role",
            json={"role": "admin"},
        )
        self.assertEqual(promote_response.status_code, 200)
        self.assertEqual(promote_response.json()["role"], "admin")

    def test_admin_cannot_downgrade_last_admin(self) -> None:
        client = self._build_client()
        admin = self._register_and_login(client, email="solo@example.com")

        demote_response = client.post(
            f"/api/admin/users/{admin['id']}/role",
            json={"role": "member"},
        )
        self.assertEqual(demote_response.status_code, 400)
        self.assertEqual(demote_response.json()["detail"], "至少需要保留一个管理员。")

    def test_admin_can_disable_user_and_revokes_member_access(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com", password="adminpass123")
        client.post("/api/auth/logout")
        member = self._register_and_login(client, email="member@example.com", password="memberpass123")
        member_session = client.cookies.get("pm_agent_session")
        self.assertIsNotNone(member_session)
        client.post("/api/auth/logout")

        admin_login = client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.com",
                "password": "adminpass123",
            },
        )
        self.assertEqual(admin_login.status_code, 200)
        disable_response = client.post(f"/api/admin/users/{member['id']}/disable", json={})
        self.assertEqual(disable_response.status_code, 200)

        client.cookies.set("pm_agent_session", str(member_session))
        me_response = client.get("/api/auth/me")
        self.assertIn(me_response.status_code, {401, 403})
        client.post("/api/auth/logout")

        member_login = client.post(
            "/api/auth/login",
            json={
                "email": "member@example.com",
                "password": "memberpass123",
            },
        )
        self.assertIn(member_login.status_code, {401, 403})

    def test_admin_can_reenable_user_and_member_can_login_again(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com", password="adminpass123")
        client.post("/api/auth/logout")
        member = self._register_and_login(client, email="member@example.com", password="memberpass123")
        client.post("/api/auth/logout")

        admin_login = client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.com",
                "password": "adminpass123",
            },
        )
        self.assertEqual(admin_login.status_code, 200)
        disable_response = client.post(f"/api/admin/users/{member['id']}/disable", json={})
        self.assertEqual(disable_response.status_code, 200)

        enable_response = client.post(f"/api/admin/users/{member['id']}/enable")
        self.assertEqual(enable_response.status_code, 200)
        client.post("/api/auth/logout")

        member_login = client.post(
            "/api/auth/login",
            json={
                "email": "member@example.com",
                "password": "memberpass123",
            },
        )
        self.assertEqual(member_login.status_code, 200)
        me_response = client.get("/api/auth/me")
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["email"], "member@example.com")

    def test_admin_can_reset_member_password_and_old_password_stops_working(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com", password="adminpass123")
        client.post("/api/auth/logout")
        member = self._register_and_login(client, email="member@example.com", password="memberpass123")
        client.post("/api/auth/logout")

        admin_login = client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.com",
                "password": "adminpass123",
            },
        )
        self.assertEqual(admin_login.status_code, 200)
        reset_response = client.post(
            f"/api/admin/users/{member['id']}/reset-password",
            json={"new_password": "memberpass456"},
        )
        self.assertEqual(reset_response.status_code, 200)
        client.post("/api/auth/logout")

        old_login = client.post(
            "/api/auth/login",
            json={
                "email": "member@example.com",
                "password": "memberpass123",
            },
        )
        self.assertIn(old_login.status_code, {401, 403})

        new_login = client.post(
            "/api/auth/login",
            json={
                "email": "member@example.com",
                "password": "memberpass456",
            },
        )
        self.assertEqual(new_login.status_code, 200)

    def test_admin_cannot_disable_last_admin(self) -> None:
        client = self._build_client()
        admin = self._register_and_login(client, email="solo@example.com", password="adminpass123")

        disable_response = client.post(f"/api/admin/users/{admin['id']}/disable", json={})
        self.assertEqual(disable_response.status_code, 400)
        self.assertIn("管理员", disable_response.json()["detail"])

    def test_change_password_rotates_session_and_invalidates_old_password(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client, email="pm@example.com", password="password123")
        self.assertEqual(user["role"], "admin")

        change_response = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "password456",
            },
        )

        self.assertEqual(change_response.status_code, 200)
        self.assertEqual(change_response.json()["user"]["email"], "pm@example.com")
        client.post("/api/auth/logout")

        old_login = client.post(
            "/api/auth/login",
            json={
                "email": "pm@example.com",
                "password": "password123",
            },
        )
        self.assertEqual(old_login.status_code, 401)

        new_login = client.post(
            "/api/auth/login",
            json={
                "email": "pm@example.com",
                "password": "password456",
            },
        )
        self.assertEqual(new_login.status_code, 200)

    def test_change_password_rejects_wrong_current_password(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="pm@example.com", password="password123")

        response = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "wrongpass1",
                "new_password": "password456",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "当前密码不正确。")

    def test_delete_account_removes_user_owned_state_and_revokes_login(self) -> None:
        client = self._build_client()
        user = self._register_and_login(client, email="pm@example.com", password="password123")
        repository = client.app.state.repository

        repository.set_runtime_config(
            {
                "provider": "openai_compatible",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-5.4",
                "api_key": "pm-secret-key",
                "timeout_seconds": 45,
            },
            user["id"],
        )
        repository.create_job(self._job_payload("job-delete-me", user["id"]))
        repository.set_assets("job-delete-me", {"claims": [], "evidence": [], "report": {"markdown": "delete me"}})
        repository.create_chat_session(
            {
                "id": "session-delete-me",
                "research_job_id": "job-delete-me",
                "owner_user_id": user["id"],
                "messages": [],
            }
        )

        response = client.post(
            "/api/auth/delete-account",
            json={
                "current_password": "password123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertIsNone(repository.get_user(user["id"]))
        self.assertIsNone(repository.get_runtime_config(user["id"]))
        self.assertIsNone(repository.get_job("job-delete-me"))
        self.assertIsNone(repository.get_assets("job-delete-me"))
        self.assertIsNone(repository.get_chat_session("session-delete-me"))

        me_response = client.get("/api/auth/me")
        self.assertEqual(me_response.status_code, 401)

        login_response = client.post(
            "/api/auth/login",
            json={
                "email": "pm@example.com",
                "password": "password123",
            },
        )
        self.assertEqual(login_response.status_code, 401)

    def test_delete_account_rejects_wrong_password(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="pm@example.com", password="password123")

        response = client.post(
            "/api/auth/delete-account",
            json={
                "current_password": "wrongpass1",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "当前密码不正确。")

    def test_last_active_admin_cannot_delete_self_when_other_users_exist(self) -> None:
        client = self._build_client()
        self._register_and_login(client, email="admin@example.com", password="adminpass123")
        client.post("/api/auth/logout")
        self._register_and_login(client, email="member@example.com", password="memberpass123")
        client.post("/api/auth/logout")

        relogin_admin = client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.com",
                "password": "adminpass123",
            },
        )
        self.assertEqual(relogin_admin.status_code, 200)

        response = client.post(
            "/api/auth/delete-account",
            json={
                "current_password": "adminpass123",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "当前仅剩最后一个可用管理员，不能删除账号。")

    def test_protected_routes_require_login(self) -> None:
        client = self._build_client()

        response = client.get("/api/research-jobs")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "请先登录。")

    def test_job_route_returns_not_found_for_other_user(self) -> None:
        client = self._build_client()
        owner = self._register_and_login(client, email="owner@example.com")
        client.app.state.repository.create_job(self._job_payload("job-owned", owner["id"]))
        client.post("/api/auth/logout")
        self._register_and_login(client, email="intruder@example.com")

        response = client.get("/api/research-jobs/job-owned")

        self.assertEqual(response.status_code, 404)

if __name__ == "__main__":
    unittest.main()
