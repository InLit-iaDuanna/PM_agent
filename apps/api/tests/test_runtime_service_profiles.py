import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
API_SRC = ROOT / "apps" / "api"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from pm_agent_api.repositories.in_memory_store import InMemoryStateRepository
from pm_agent_api.services.runtime_service import RuntimeService


class RuntimeServiceProfilesTest(unittest.TestCase):
    def test_save_settings_exposes_profile_and_backup_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False), patch(
                "pm_agent_api.services.runtime_service.socket.getaddrinfo",
                return_value=[(0, 0, 0, "", ("127.0.0.1", 443))],
            ):
                repository = InMemoryStateRepository()
                service = RuntimeService(repository)

                status = service.save_settings(
                    {
                        "profile_id": "premium_default",
                        "provider": "openai_compatible",
                        "base_url": "https://api.openai.com/v1",
                        "model": "gpt-5.4",
                        "api_key": "sk-test-1234567890abcdef",
                        "timeout_seconds": 60,
                        "backup_configs": [
                            {
                                "label": "备用直连",
                                "base_url": "https://backup.example.com/v1",
                            }
                        ],
                    }
                )

                self.assertEqual(status["selected_profile_id"], "premium_default")
                self.assertEqual(status["runtime_config"]["profile_id"], "premium_default")
                self.assertEqual(status["resolved_runtime_config"]["retrieval_profile"]["profile_id"], "premium_default")
                self.assertEqual(status["quality_policy"]["profile_id"], "premium_default")
                self.assertEqual(status["debug_policy"]["auto_open_mode"], "off")
                self.assertEqual(status["backup_count"], 1)
                self.assertEqual(status["backup_configs"][0]["label"], "备用直连")
                self.assertGreaterEqual(len(status["available_profiles"]), 2)

    def test_replace_api_key_clears_saved_secret(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False), patch(
                "pm_agent_api.services.runtime_service.socket.getaddrinfo",
                return_value=[(0, 0, 0, "", ("127.0.0.1", 443))],
            ):
                repository = InMemoryStateRepository()
                service = RuntimeService(repository)

                service.save_settings(
                    {
                        "profile_id": "dev_fallback",
                        "provider": "openai_compatible",
                        "base_url": "https://api.openai.com/v1",
                        "model": "gpt-5.4-mini",
                        "api_key": "sk-test-1234567890abcdef",
                        "timeout_seconds": 30,
                    }
                )
                cleared_status = service.save_settings(
                    {
                        "profile_id": "dev_fallback",
                        "provider": "openai_compatible",
                        "base_url": "https://api.openai.com/v1",
                        "model": "gpt-5.4-mini",
                        "timeout_seconds": 30,
                    },
                    replace_api_key=True,
                )

                saved_config = repository.get_runtime_config()
                self.assertFalse(saved_config.get("api_key"))
                self.assertFalse(cleared_status["api_key_configured"])

    def test_validate_returns_selected_profile_and_browser_summary(self) -> None:
        class DummyWorkflow:
            def __init__(self, runtime_config=None):
                self.runtime_config = runtime_config or {}
                self.llm_client = SimpleNamespace(
                    settings=SimpleNamespace(model="gpt-5.4"),
                    complete=lambda *_args, **_kwargs: "OK",
                    active_base_url=None,
                )

            def _build_runtime_summary(self):
                return {
                    "provider": "openai_compatible",
                    "model": "gpt-5.4",
                    "validation_status": "valid",
                    "validation_message": "ok",
                    "browser_mode": "debug_only",
                    "browser_available": True,
                }

        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"PM_AGENT_STATE_DIR": state_dir}, clear=False), patch(
                "pm_agent_api.services.runtime_service.socket.getaddrinfo",
                return_value=[(0, 0, 0, "", ("127.0.0.1", 443))],
            ), patch("pm_agent_api.services.runtime_service.ResearchWorkflowEngine", DummyWorkflow):
                repository = InMemoryStateRepository()
                service = RuntimeService(repository)

                result = service.validate(
                    {
                        "profile_id": "premium_default",
                        "provider": "openai_compatible",
                        "base_url": "https://api.openai.com/v1",
                        "model": "gpt-5.4",
                        "api_key": "sk-test-1234567890abcdef",
                        "timeout_seconds": 60,
                    }
                )

                self.assertTrue(result["ok"])
                self.assertEqual(result["selected_profile_id"], "premium_default")
                self.assertEqual(result["browser_mode"], "debug_only")
                self.assertTrue(result["browser_available"])


if __name__ == "__main__":
    unittest.main()
