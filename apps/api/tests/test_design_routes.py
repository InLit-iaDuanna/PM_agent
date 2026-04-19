import base64
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


class FakeTrendService:
    def __init__(self) -> None:
        self.pool_payload = {
            "date": "2026-04-18",
            "pool_fetched_at": "2026-04-18T00:00:00+00:00",
            "pool": [
                {
                    "id": "trend-1",
                    "name": "静奢留白",
                    "name_en": "Quiet Luxury Minimal",
                    "category": "视觉风格",
                    "description": "用留白和低饱和层级营造高级感。",
                    "keywords": ["留白", "克制", "高级感"],
                    "color_palette": ["#F8FAFC", "#E2E8F0", "#CBD5E1", "#475569", "#0F172A"],
                    "mood_keywords": ["冷静", "精致"],
                    "source_urls": ["https://example.com/design-trends"],
                    "difficulty": 2,
                    "example_prompt": "做一版高级感首页 Hero。",
                    "fetched_at": "2026-04-18T00:00:00+00:00",
                }
            ],
        }

    async def get_today_trend_pool(self, force_refresh: bool = False):
        return self.pool_payload

    def roll_trend_for_user(self, user_id: str, pool_payload, target_date=None):
        return {
            "date": pool_payload["date"],
            "trend": pool_payload["pool"][0],
            "dice_face": 1,
            "dice_category": "视觉风格",
            "pool": pool_payload["pool"],
            "pool_fetched_at": pool_payload["pool_fetched_at"],
        }

    def get_user_history(self, user_id: str, days: int = 30):
        return [
            {
                "date": self.pool_payload["date"],
                "trend": self.pool_payload["pool"][0],
                "dice_face": 1,
                "dice_category": "视觉风格",
            }
        ]

    def force_refresh_today_sync(self):
        return self.pool_payload


class DesignRoutesTest(unittest.TestCase):
    def _build_client(self) -> TestClient:
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
        app = create_app(repository=repository)
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def _register_and_login(self, client: TestClient, email: str = "designer@example.com", password: str = "password123") -> dict:
        response = client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": password,
                "display_name": "Designer",
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["user"]

    def _trend_payload(self, trend_id: str, name: str) -> dict:
        return {
            "id": trend_id,
            "name": name,
            "name_en": f"{name} EN",
            "category": "视觉风格",
            "description": f"{name} 的描述",
            "keywords": ["极简", "留白", "品牌感"],
            "color_palette": ["#F8FAFC", "#E2E8F0", "#CBD5E1", "#475569", "#0F172A"],
            "mood_keywords": ["冷静", "精致"],
            "source_urls": ["https://example.com/design-trends"],
            "difficulty": 2,
            "example_prompt": f"围绕 {name} 做一个首页方案。",
            "fetched_at": "2026-04-18T00:00:00+00:00",
        }

    def test_design_trend_routes_return_roll_and_history(self) -> None:
        client = self._build_client()
        self._register_and_login(client)
        client.app.state.design_trend_service = FakeTrendService()

        today_response = client.get("/api/design/trends/today")
        history_response = client.get("/api/design/trends/history?days=7")

        self.assertEqual(today_response.status_code, 200)
        self.assertEqual(today_response.json()["trend"]["id"], "trend-1")
        self.assertEqual(today_response.json()["dice_category"], "视觉风格")

        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(len(history_response.json()), 1)
        self.assertEqual(history_response.json()[0]["date"], "2026-04-18")

    def test_design_material_routes_support_trend_save_network_and_image_proxy(self) -> None:
        client = self._build_client()
        self._register_and_login(client)

        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2pN6kAAAAASUVORK5CYII="
        )
        with patch(
            "pm_agent_api.services.design_material_service.DesignMaterialService._fetch_best_trend_source_image",
            return_value={
                "data": png_bytes,
                "mime_type": "image/png",
                "image_url": "https://cdn.example.com/trend.png",
                "page_url": "https://example.com/design-trends",
            },
        ):
            first_save = client.post("/api/design/materials/from-trend", json={"trend": self._trend_payload("trend-1", "静奢留白")})
            second_save = client.post("/api/design/materials/from-trend", json={"trend": self._trend_payload("trend-2", "柔和未来感")})
        self.assertEqual(first_save.status_code, 200)
        self.assertEqual(second_save.status_code, 200)

        first_material = first_save.json()
        second_material = second_save.json()
        self.assertEqual(first_material["source"], "trend")
        self.assertEqual(second_material["source"], "trend")
        self.assertEqual(first_material["original_url"], "https://example.com/design-trends")

        list_response = client.get("/api/design/materials")
        tags_response = client.get("/api/design/materials/tags/all")
        network_response = client.get("/api/design/materials/network")
        image_response = client.get(first_material["thumbnail_url"])
        patch_response = client.patch(
            f"/api/design/materials/{first_material['id']}/tags",
            json={"add": [{"name": "作品集", "category": "custom", "type": "manual"}], "remove": []},
        )
        delete_response = client.delete(f"/api/design/materials/{second_material['id']}")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["total"], 2)

        self.assertEqual(tags_response.status_code, 200)
        self.assertIn("极简", tags_response.json())

        self.assertEqual(network_response.status_code, 200)
        self.assertEqual(len(network_response.json()["nodes"]), 2)
        self.assertGreaterEqual(len(network_response.json()["links"]), 1)

        self.assertEqual(image_response.status_code, 200)
        self.assertTrue(image_response.headers["content-type"].startswith("image/"))

        self.assertEqual(patch_response.status_code, 200)
        patch_names = [item["name"] for item in patch_response.json()["tags"]]
        self.assertIn("作品集", patch_names)

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["ok"], True)

    def test_design_upload_url_rejects_private_addresses(self) -> None:
        client = self._build_client()
        self._register_and_login(client)

        response = client.post(
            "/api/design/materials/upload-url",
            json={"url": "http://127.0.0.1/internal.png", "tags": []},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("公网", response.json()["detail"])

    def test_design_upload_rejects_invalid_image_payload(self) -> None:
        client = self._build_client()
        self._register_and_login(client)

        response = client.post(
            "/api/design/materials/upload",
            files={"file": ("fake.png", b"this-is-not-a-real-image", "image/png")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("有效图片", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
