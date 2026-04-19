import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
API_SRC = ROOT / "apps" / "api"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from pm_agent_api.repositories.in_memory_store import InMemoryStateRepository
from pm_agent_api.services.design_material_service import DesignMaterialService


class DesignMaterialServiceTest(unittest.TestCase):
    def _build_service(self) -> DesignMaterialService:
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
        return DesignMaterialService(repository)

    def test_decode_google_news_source_url_parses_nested_batch_payload(self) -> None:
        service = self._build_service()
        google_url = "https://news.google.com/rss/articles/CBMiVkFVX3lxTE15SGdJak5IcDg0dnpEZWhUUFI0TXQyNDF2Vnp5WVhwRVZEc1dGUXVGOXlyQXRrR2FhNE03NnNvNEJhRnNFSm8yVDJFdUluLXNFcUpMeHdB?oc=5"
        article_html = (
            '<html><body><c-wiz><div data-n-a-sg="sig-123" data-n-a-ts="1776576052"></div></c-wiz></body></html>'
        )
        batch_response = Mock()
        batch_response.raise_for_status = Mock()
        batch_response.text = (
            ")]}'\n\n"
            '[["wrb.fr","Fbv4je","[\\"garturlres\\",\\"https://designmodo.com/email-design-trends/\\",1]",null,null,null,"generic"],["di",14],["af.httprm",14,"123",3]]\n'
        )

        with patch.object(service, "_fetch_remote_html", return_value=(article_html, google_url)):
            with patch.object(service, "_validate_trend_fetch_url", side_effect=lambda url: url):
                with patch("pm_agent_api.services.design_material_service.httpx.post", return_value=batch_response):
                    decoded = service._decode_google_news_source_url(google_url)

        self.assertEqual(decoded, "https://designmodo.com/email-design-trends/")

    def test_resolve_trend_source_page_url_uses_trend_fetch_validator_for_direct_urls(self) -> None:
        service = self._build_service()
        with patch.object(service, "_validate_trend_fetch_url", return_value="https://example.com/article") as validate_trend:
            with patch.object(service, "_validate_remote_image_url", side_effect=AssertionError("strict validator should not be used")):
                resolved = service._resolve_trend_source_page_url("https://example.com/article")

        self.assertEqual(resolved, "https://example.com/article")
        validate_trend.assert_called_once_with("https://example.com/article")

    def test_validate_trend_fetch_url_rejects_hostnames_resolving_to_private_ips(self) -> None:
        service = self._build_service()
        with patch(
            "pm_agent_api.services.design_material_service.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))],
        ):
            with self.assertRaisesRegex(ValueError, "公网"):
                service._validate_trend_fetch_url("https://cdn.example.com/trend.png")


if __name__ == "__main__":
    unittest.main()
