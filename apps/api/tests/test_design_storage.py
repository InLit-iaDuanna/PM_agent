import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
API_SRC = ROOT / "apps" / "api"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from pm_agent_api.repositories.flagship_store import ObjectStorageSettings, S3ObjectStore


class _FakeS3Client:
    def __init__(self) -> None:
        self.calls = []

    def generate_presigned_url(self, operation_name, Params=None, ExpiresIn=None):
        self.calls.append(
            {
                "operation_name": operation_name,
                "params": Params or {},
                "expires_in": ExpiresIn,
            }
        )
        return "https://example.com/presigned"


class DesignStorageTest(unittest.TestCase):
    def test_generate_presigned_url_does_not_duplicate_existing_prefix(self) -> None:
        client = _FakeS3Client()
        store = object.__new__(S3ObjectStore)
        store.settings = ObjectStorageSettings(bucket="pm-agent-bucket", key_prefix="pm-agent")
        store.client = client

        result = store.generate_presigned_url("pm-agent/design/materials/demo/full.png", expires_in=123)

        self.assertEqual(result, "https://example.com/presigned")
        self.assertEqual(client.calls[0]["operation_name"], "get_object")
        self.assertEqual(client.calls[0]["params"]["Bucket"], "pm-agent-bucket")
        self.assertEqual(client.calls[0]["params"]["Key"], "pm-agent/design/materials/demo/full.png")
        self.assertEqual(client.calls[0]["expires_in"], 123)


if __name__ == "__main__":
    unittest.main()
