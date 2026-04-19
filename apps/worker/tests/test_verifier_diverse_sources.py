import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
WORKER_SRC = ROOT / "apps" / "worker"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from pm_agent_worker.agents.verifier_agent import VerifierAgent


class VerifierDomainDiversityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = VerifierAgent()

    def test_extract_domain_handles_www_and_empty_values(self) -> None:
        self.assertEqual(self.verifier._extract_domain("https://www.example.com/path"), "example.com")
        self.assertEqual(self.verifier._extract_domain(None), "")
        self.assertEqual(self.verifier._extract_domain(""), "")

    def test_single_domain_cannot_reach_verified(self) -> None:
        evidence = [
            {
                "id": f"e{i}",
                "source_url": f"https://tomsguide.com/page{i}",
                "source_tier": "t2",
                "confidence": 0.80,
                "authority_score": 0.75,
                "market_step": "competitor-analysis",
            }
            for i in range(4)
        ]
        _, status, _ = self.verifier._verification_summary(evidence, [], 0.80)
        self.assertNotEqual(status, "verified")
        self.assertNotEqual(status, "confirmed")

    def test_two_domains_can_reach_verified(self) -> None:
        evidence = [
            {"id": "e1", "source_url": "https://tomsguide.com/review", "source_tier": "t2", "confidence": 0.80, "authority_score": 0.75},
            {"id": "e2", "source_url": "https://digitaltrends.com/review", "source_tier": "t2", "confidence": 0.78, "authority_score": 0.73},
        ]
        verification_state, status, reason = self.verifier._verification_summary(evidence, [], 0.79)
        self.assertEqual(verification_state, "supported")
        self.assertEqual(status, "verified")
        self.assertIn("2 个独立域名", reason)

    def test_three_domains_and_high_confidence_can_reach_confirmed(self) -> None:
        evidence = [
            {"id": "e1", "source_url": "https://tomsguide.com/review", "source_tier": "t2", "confidence": 0.88, "authority_score": 0.78},
            {"id": "e2", "source_url": "https://digitaltrends.com/review", "source_tier": "t2", "confidence": 0.86, "authority_score": 0.74},
            {"id": "e3", "source_url": "https://theverge.com/review", "source_tier": "t3", "confidence": 0.85, "authority_score": 0.73},
        ]
        verification_state, status, _ = self.verifier._verification_summary(evidence, [], 0.86)
        self.assertEqual(verification_state, "confirmed")
        self.assertEqual(status, "confirmed")

    def test_low_confidence_single_source_is_inferred(self) -> None:
        evidence = [
            {"id": "e1", "source_url": "https://example.com/post", "source_tier": "t3", "confidence": 0.42, "authority_score": 0.44},
        ]
        verification_state, status, _ = self.verifier._verification_summary(evidence, [], 0.42)
        self.assertEqual(verification_state, "inferred")
        self.assertEqual(status, "inferred")

    def test_medium_confidence_single_domain_is_directional(self) -> None:
        evidence = [
            {"id": "e1", "source_url": "https://example.com/post-1", "source_tier": "t2", "confidence": 0.62, "authority_score": 0.74},
            {"id": "e2", "source_url": "https://example.com/post-2", "source_tier": "t3", "confidence": 0.58, "authority_score": 0.55},
        ]
        verification_state, status, _ = self.verifier._verification_summary(evidence, [], 0.60)
        self.assertEqual(verification_state, "directional")
        self.assertEqual(status, "directional")

    def test_conflicting_evidence_is_disputed(self) -> None:
        evidence = [
            {"id": "e1", "source_url": "https://example.com/post", "source_tier": "t2", "confidence": 0.82, "authority_score": 0.77},
        ]
        verification_state, status, _ = self.verifier._verification_summary(evidence, ["e9"], 0.82)
        self.assertEqual(verification_state, "conflicted")
        self.assertEqual(status, "disputed")

    def test_select_diverse_evidence_caps_same_domain_and_fills_remaining_slots(self) -> None:
        evidence = [
            {"id": "e1", "source_url": "https://a.com/1", "confidence": 0.91},
            {"id": "e2", "source_url": "https://a.com/2", "confidence": 0.89},
            {"id": "e3", "source_url": "https://a.com/3", "confidence": 0.88},
            {"id": "e4", "source_url": "https://b.com/1", "confidence": 0.87},
            {"id": "e5", "source_url": "https://c.com/1", "confidence": 0.86},
        ]
        selected = self.verifier._select_diverse_evidence(evidence, limit=4)
        selected_ids = [item["id"] for item in selected]
        self.assertEqual(len(selected_ids), 4)
        self.assertIn("e1", selected_ids)
        self.assertIn("e2", selected_ids)
        self.assertNotIn("e3", selected_ids)
        self.assertIn("e4", selected_ids)
        self.assertIn("e5", selected_ids)

    def test_select_diverse_evidence_fills_when_domains_missing(self) -> None:
        evidence = [
            {"id": "e1", "source_url": "", "confidence": 0.9},
            {"id": "e2", "source_url": "", "confidence": 0.85},
            {"id": "e3", "source_url": "", "confidence": 0.8},
        ]
        selected = self.verifier._select_diverse_evidence(evidence, limit=4)
        self.assertEqual([item["id"] for item in selected], ["e1", "e2", "e3"])

    def test_build_claims_clamps_llm_overclaim_to_supported_evidence_tier(self) -> None:
        llm_client = Mock()
        llm_client.is_enabled.return_value = True
        llm_client.complete_json.return_value = [
            {
                "id": "job-1-claim-1",
                "claim_text": "Single-domain evidence is enough for a confirmed claim.",
                "market_step": "competitor-analysis",
                "evidence_ids": ["e1", "e2"],
                "counter_evidence_ids": [],
                "confidence": 0.95,
                "status": "confirmed",
                "verification_state": "confirmed",
                "caveats": [],
                "competitor_ids": [],
                "priority": "high",
                "actionability_score": 0.88,
                "last_verified_at": "2026-04-19T00:00:00+00:00",
            }
        ]
        verifier = VerifierAgent(llm_client=llm_client)
        evidence = [
            {
                "id": "e1",
                "source_url": "https://example.com/post-1",
                "source_tier": "t2",
                "confidence": 0.95,
                "authority_score": 0.8,
                "market_step": "competitor-analysis",
            },
            {
                "id": "e2",
                "source_url": "https://example.com/post-2",
                "source_tier": "t2",
                "confidence": 0.92,
                "authority_score": 0.78,
                "market_step": "competitor-analysis",
            },
        ]

        claims = verifier.build_claims({"job_id": "job-1", "topic": "AI眼镜", "research_mode": "standard"}, evidence)

        self.assertEqual(claims[0]["status"], "directional")
        self.assertEqual(claims[0]["verification_state"], "directional")


if __name__ == "__main__":
    unittest.main()
