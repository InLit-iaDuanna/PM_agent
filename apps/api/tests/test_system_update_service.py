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

from pm_agent_api.services.system_update_service import SystemUpdateService


class SystemUpdateServiceTest(unittest.TestCase):
    def test_build_metadata_mode_still_reports_current_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "PM_AGENT_BUILD_COMMIT": "abc1234",
                    "PM_AGENT_BUILD_TAG": "v1.0.1",
                    "PM_AGENT_BUILD_BRANCH": "main",
                    "PM_AGENT_BUILD_TIME": "2026-04-14T00:00:00Z",
                },
                clear=False,
            ):
                service = SystemUpdateService(repo_root=Path(temp_dir))
                with patch.object(service, "_is_git_checkout", return_value=False), patch.object(service, "_git_available", return_value=False):
                    status = service.get_status()

        self.assertTrue(status["supported"])
        self.assertFalse(status["can_execute"])
        self.assertEqual(status["current_commit"], "abc1234")
        self.assertEqual(status["current_tag"], "v1.0.1")
        self.assertEqual(status["current_branch"], "main")
        self.assertEqual(status["build_time"], "2026-04-14T00:00:00Z")

    def test_trigger_update_is_blocked_in_build_metadata_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "PM_AGENT_BUILD_COMMIT": "abc1234",
                    "PM_AGENT_BUILD_TAG": "v1.0.1",
                },
                clear=False,
            ):
                service = SystemUpdateService(repo_root=Path(temp_dir))
                with patch.object(service, "_is_git_checkout", return_value=False), patch.object(service, "_git_available", return_value=False):
                    with self.assertRaisesRegex(ValueError, "宿主机"):
                        service.trigger_update({"ref": "main"})


if __name__ == "__main__":
    unittest.main()
