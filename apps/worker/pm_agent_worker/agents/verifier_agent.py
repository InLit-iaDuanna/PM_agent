import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

from pm_agent_worker.tools.minimax_client import MiniMaxChatClient
from pm_agent_worker.tools.prompt_loader import load_prompt_template
from pm_agent_worker.workflows.presentation_labels import market_step_label
from pm_agent_worker.workflows.research_models import iso_now


class VerifierAgent:
    def __init__(self, llm_client: Optional[MiniMaxChatClient] = None) -> None:
        self.llm_client = llm_client

    def _linked_support_ids(self, evidence_ids: List[str], counter_evidence_ids: List[str]) -> tuple[List[str], List[str]]:
        supporting = [str(item).strip() for item in evidence_ids if str(item).strip()]
        contradicting = [
            str(item).strip()
            for item in counter_evidence_ids
            if str(item).strip() and str(item).strip() not in supporting
        ]
        return supporting, contradicting

    def _decision_impact(self, market_step: str) -> str:
        normalized = str(market_step or "").strip()
        if normalized in {"recommendations", "pricing-and-growth", "business-and-channels"}:
            return "high"
        if normalized in {"user-research", "competitor-analysis", "experience-teardown"}:
            return "medium"
        return "low"

    def _verification_summary(
        self,
        support_evidence: List[Dict[str, Any]],
        contradicting_evidence_ids: List[str],
        average_confidence: float,
    ) -> tuple[str, str, str]:
        if contradicting_evidence_ids:
            return (
                "conflicted",
                "disputed",
                "存在相互冲突的证据，需要人工复核后才能进入稳定结论。",
            )
        if not support_evidence:
            return (
                "open_question",
                "inferred",
                "当前还没有绑定到可复核的支撑证据，只能保留为待验证问题。",
            )

        strong_support_count = sum(
            1
            for item in support_evidence
            if str(item.get("source_tier") or "").strip().lower() in {"t1", "t2"} or float(item.get("authority_score", 0) or 0) >= 0.72
        )
        if strong_support_count >= 2 or (strong_support_count >= 1 and average_confidence >= 0.74) or (
            len(support_evidence) >= 3 and average_confidence >= 0.72
        ):
            return (
                "supported",
                "verified",
                f"已有 {strong_support_count} 条高可信支撑证据，且平均置信度为 {average_confidence:.2f}。",
            )
        return (
            "inferred",
            "inferred",
            f"当前主要依赖 {len(support_evidence)} 条中等强度证据，平均置信度为 {average_confidence:.2f}，仍建议继续补证。",
        )

    def _build_fallback_claim_text(self, request: Dict[str, Any], market_step: str, evidence: List[Dict[str, Any]]) -> str:
        localized_step = market_step_label(market_step)
        strongest_evidence = sorted(evidence, key=lambda item: float(item.get("confidence", 0)), reverse=True)[:2]
        titles = [item.get("title", "") for item in strongest_evidence if item.get("title")]
        if titles:
            return f"{request['topic']} 在{localized_step}维度最值得优先验证的方向，集中体现为：{titles[0]}"
        return f"{request['topic']} 在{localized_step}维度存在可优先推进的产品机会。"

    def _infer_counter_evidence_ids(self, evidence: List[Dict[str, Any]]) -> List[str]:
        conflict_keywords = ("争议", "冲突", "相反", "不同", "however", "but", "conflict", "unclear")
        counter_ids: List[str] = []
        for item in evidence:
            text = " ".join(
                [
                    str(item.get("quote", "")),
                    str(item.get("summary", "")),
                    str(item.get("extracted_fact", "")),
                ]
            ).lower()
            if any(keyword in text for keyword in conflict_keywords):
                counter_ids.append(item["id"])
        return counter_ids[:2]

    def _build_delta_fallback_claim_text(self, question: str, evidence: List[Dict[str, Any]]) -> str:
        strongest = sorted(evidence, key=lambda item: float(item.get("confidence", 0)), reverse=True)[:2]
        if not strongest:
            return f"围绕“{question}”当前仍缺少足够证据，需要继续补充一手验证。"

        extracted_facts = [item.get("extracted_fact") or item.get("summary") or item.get("title", "") for item in strongest]
        condensed = "；".join(text.strip() for text in extracted_facts if text and text.strip())
        if condensed:
            return f"围绕“{question}”，补充研究显示：{condensed[:220]}"
        return f"围绕“{question}”，补充研究已获得新的外部证据，但仍需继续验证。"

    def build_claims(self, request: Dict[str, Any], evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in evidence:
            grouped[item["market_step"]].append(item)

        fallback_claims = []
        for index, (market_step, step_evidence) in enumerate(grouped.items(), start=1):
            sorted_step_evidence = sorted(step_evidence, key=lambda item: float(item.get("confidence", 0)), reverse=True)
            evidence_ids = [item["id"] for item in sorted_step_evidence[:4]]
            counter_evidence_ids = self._infer_counter_evidence_ids(step_evidence)
            supporting_evidence_ids, contradicting_evidence_ids = self._linked_support_ids(evidence_ids, counter_evidence_ids)
            average_confidence = round(
                sum(item["confidence"] for item in sorted_step_evidence[:4]) / max(1, len(sorted_step_evidence[:4])),
                2,
            )
            support_evidence = [item for item in sorted_step_evidence[:4] if item["id"] in supporting_evidence_ids]
            verification_state, status, confidence_reason = self._verification_summary(
                support_evidence,
                contradicting_evidence_ids,
                average_confidence,
            )
            fallback_claims.append(
                {
                    "id": f"{request['job_id']}-claim-{index}",
                    "claim_text": self._build_fallback_claim_text(request, market_step, sorted_step_evidence),
                    "market_step": market_step,
                    "evidence_ids": evidence_ids,
                    "counter_evidence_ids": counter_evidence_ids,
                    "supporting_evidence_ids": supporting_evidence_ids,
                    "contradicting_evidence_ids": contradicting_evidence_ids,
                    "confidence": average_confidence,
                    "status": status,
                    "verification_state": verification_state,
                    "confidence_reason": confidence_reason,
                    "decision_impact": self._decision_impact(market_step),
                    "caveats": (
                        ["需要在真实用户访谈中补充验证"]
                        if request["research_mode"] == "deep" and status != "verified"
                        else []
                    ),
                    "competitor_ids": sorted({item["competitor_name"] for item in step_evidence if item.get("competitor_name")})[:3],
                    "priority": "high" if index <= 3 else "medium",
                    "actionability_score": round(0.75 + min(index, 4) * 0.04, 2),
                    "last_verified_at": iso_now(),
                }
            )
        if not self.llm_client or not self.llm_client.is_enabled():
            return fallback_claims

        valid_evidence_ids = {item["id"] for item in evidence}
        valid_competitors = sorted({item.get("competitor_name") for item in evidence if item.get("competitor_name")})

        try:
            system_prompt = load_prompt_template("verifier")
            result = self.llm_client.complete_json(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "请基于以下 evidence 列表生成 JSON 数组 claims，字段必须包含 "
                            "id/claim_text/market_step/evidence_ids/counter_evidence_ids/confidence/status/caveats/"
                            "competitor_ids/priority/actionability_score/last_verified_at。"
                            f"\njob_id={request['job_id']}\n"
                            f"topic={request['topic']}\n"
                            f"research_mode={request['research_mode']}\n"
                            f"\nvalid_competitors={valid_competitors}\n"
                            f"evidence={json.dumps(evidence[:18], ensure_ascii=False)}\n"
                            "只返回 JSON。"
                        ),
                    },
                ],
                temperature=0.1,
                max_tokens=2200,
            )
            if isinstance(result, list) and result:
                sanitized = []
                for index, item in enumerate(result, start=1):
                    if not isinstance(item, dict):
                        continue
                    evidence_ids = [value for value in item.get("evidence_ids", []) if value in valid_evidence_ids][:5]
                    if not evidence_ids:
                        continue
                    counter_evidence_ids = [value for value in item.get("counter_evidence_ids", []) if value in valid_evidence_ids and value not in evidence_ids][:3]
                    supporting_evidence_ids, contradicting_evidence_ids = self._linked_support_ids(evidence_ids, counter_evidence_ids)
                    support_evidence = [record for record in evidence if record["id"] in supporting_evidence_ids]
                    average_confidence = round(max(0.2, min(0.98, float(item.get("confidence", 0.6)))), 2)
                    fallback_summary = self._verification_summary(
                        support_evidence,
                        contradicting_evidence_ids,
                        average_confidence,
                    )
                    explicit_verification_state = str(item.get("verification_state") or "").strip()
                    verification_state = (
                        explicit_verification_state
                        if explicit_verification_state in {"supported", "inferred", "conflicted", "open_question"}
                        else fallback_summary[0]
                    )
                    status = item.get("status") if item.get("status") in {"verified", "inferred", "disputed"} else fallback_summary[1]
                    sanitized.append(
                        {
                            "id": item.get("id") or f"{request['job_id']}-claim-{index}",
                            "claim_text": item.get("claim_text") or fallback_claims[min(index - 1, len(fallback_claims) - 1)]["claim_text"],
                            "market_step": item.get("market_step") or evidence[0]["market_step"],
                            "evidence_ids": evidence_ids,
                            "counter_evidence_ids": counter_evidence_ids,
                            "supporting_evidence_ids": supporting_evidence_ids,
                            "contradicting_evidence_ids": contradicting_evidence_ids,
                            "confidence": average_confidence,
                            "status": status,
                            "verification_state": verification_state,
                            "confidence_reason": item.get("confidence_reason") or fallback_summary[2],
                            "decision_impact": item.get("decision_impact") or self._decision_impact(item.get("market_step") or evidence[0]["market_step"]),
                            "caveats": item.get("caveats") if isinstance(item.get("caveats"), list) else [],
                            "competitor_ids": [value for value in item.get("competitor_ids", []) if value in valid_competitors][:4],
                            "priority": item.get("priority") if item.get("priority") in {"high", "medium", "low"} else "medium",
                            "actionability_score": round(max(0.2, min(0.99, float(item.get("actionability_score", 0.75)))), 2),
                            "last_verified_at": item.get("last_verified_at") or iso_now(),
                        }
                    )
                if sanitized:
                    return sanitized
        except Exception:
            return fallback_claims
        return fallback_claims

    def build_delta_claim(
        self,
        request: Dict[str, Any],
        question: str,
        market_step: str,
        evidence: List[Dict[str, Any]],
        claim_id: str,
    ) -> Dict[str, Any]:
        sorted_evidence = sorted(evidence, key=lambda item: float(item.get("confidence", 0)), reverse=True)
        strongest = sorted_evidence[:3]
        evidence_ids = [item["id"] for item in strongest]
        average_confidence = round(sum(float(item.get("confidence", 0)) for item in strongest) / max(1, len(strongest)), 2)
        competitor_ids = sorted({item["competitor_name"] for item in strongest if item.get("competitor_name")})[:4]
        counter_evidence_ids = self._infer_counter_evidence_ids(strongest)
        supporting_evidence_ids, contradicting_evidence_ids = self._linked_support_ids(evidence_ids, counter_evidence_ids)
        verification_state, status, confidence_reason = self._verification_summary(
            [item for item in strongest if item["id"] in supporting_evidence_ids],
            contradicting_evidence_ids,
            average_confidence,
        )

        fallback_claim = {
            "id": claim_id,
            "claim_text": self._build_delta_fallback_claim_text(question, strongest),
            "market_step": market_step,
            "evidence_ids": evidence_ids,
            "counter_evidence_ids": counter_evidence_ids,
            "supporting_evidence_ids": supporting_evidence_ids,
            "contradicting_evidence_ids": contradicting_evidence_ids,
            "confidence": average_confidence,
            "status": status,
            "verification_state": verification_state,
            "confidence_reason": confidence_reason,
            "decision_impact": self._decision_impact(market_step),
            "caveats": ["这是针对追问的定向补充研究，仍建议和主报告中的用户验证结果交叉确认。"] if status != "verified" else [],
            "competitor_ids": competitor_ids,
            "priority": "high",
            "actionability_score": round(min(0.95, 0.74 + average_confidence * 0.2), 2),
            "last_verified_at": iso_now(),
        }

        if not self.llm_client or not self.llm_client.is_enabled():
            return fallback_claim

        try:
            system_prompt = load_prompt_template("verifier")
            result = self.llm_client.complete_json(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "基于以下追问补充研究结果生成一个 JSON claim 对象。"
                            "字段必须包含 claim_text/confidence/status/caveats/competitor_ids/actionability_score。"
                            f"\nquestion={question}"
                            f"\ntopic={request['topic']}"
                            f"\nmarket_step={market_step}"
                            f"\nevidence={json.dumps(strongest, ensure_ascii=False)}"
                            f"\nvalid_competitors={competitor_ids}"
                            "\n只返回 JSON。"
                        ),
                    },
                ],
                temperature=0.15,
                max_tokens=900,
            )
            if isinstance(result, dict):
                explicit_verification_state = str(result.get("verification_state") or "").strip()
                next_verification_state = (
                    explicit_verification_state
                    if explicit_verification_state in {"supported", "inferred", "conflicted", "open_question"}
                    else fallback_claim["verification_state"]
                )
                return {
                    "id": claim_id,
                    "claim_text": result.get("claim_text") or fallback_claim["claim_text"],
                    "market_step": market_step,
                    "evidence_ids": evidence_ids,
                    "counter_evidence_ids": counter_evidence_ids,
                    "supporting_evidence_ids": supporting_evidence_ids,
                    "contradicting_evidence_ids": contradicting_evidence_ids,
                    "confidence": round(max(0.25, min(0.98, float(result.get("confidence", fallback_claim["confidence"])))), 2),
                    "status": result.get("status") if result.get("status") in {"verified", "inferred", "disputed"} else fallback_claim["status"],
                    "verification_state": next_verification_state,
                    "confidence_reason": result.get("confidence_reason") or fallback_claim["confidence_reason"],
                    "decision_impact": result.get("decision_impact") or fallback_claim["decision_impact"],
                    "caveats": result.get("caveats") if isinstance(result.get("caveats"), list) else fallback_claim["caveats"],
                    "competitor_ids": [value for value in result.get("competitor_ids", []) if value in competitor_ids][:4],
                    "priority": "high",
                    "actionability_score": round(
                        max(0.3, min(0.99, float(result.get("actionability_score", fallback_claim["actionability_score"])))),
                        2,
                    ),
                    "last_verified_at": iso_now(),
                }
        except Exception:
            return fallback_claim
        return fallback_claim
