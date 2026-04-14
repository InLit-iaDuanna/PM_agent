import sys
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

from pm_agent_api.repositories import InMemoryStateRepository, create_state_repository


class RepositoryFactoryTest(unittest.TestCase):
    def test_create_state_repository_defaults_to_json_backend(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            repository = create_state_repository()

        self.assertIsInstance(repository, InMemoryStateRepository)

    def test_create_state_repository_uses_flagship_backend_when_requested(self) -> None:
        sentinel = object()
        with patch.dict(
            "os.environ",
            {
                "PM_AGENT_STORAGE_BACKEND": "flagship",
                "PM_AGENT_POSTGRES_DSN": "postgresql://pmagent:pmagent@localhost:5432/pmagent",
            },
            clear=False,
        ), patch("pm_agent_api.repositories.FlagshipStateRepository.from_env", return_value=sentinel) as mocked_factory:
            repository = create_state_repository()

        self.assertIs(repository, sentinel)
        mocked_factory.assert_called_once_with()

    def test_create_state_repository_rejects_unknown_backend(self) -> None:
        with patch.dict("os.environ", {"PM_AGENT_STORAGE_BACKEND": "mystery"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "Unsupported PM_AGENT_STORAGE_BACKEND"):
                create_state_repository()


if __name__ == "__main__":
    unittest.main()
