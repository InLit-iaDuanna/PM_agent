import json
from collections import defaultdict
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pm_agent_worker.tools.minimax_client import MiniMaxChatClient
from pm_agent_worker.tools.prompt_loader import load_prompt_template
from pm_agent_worker.workflows.presentation_labels import market_step_label
from pm_agent_worker.workflows.research_models import iso_now


class VerifierAgent:
    def __init__(self, llm_client: Optional[MiniMaxChatClient] = None) -> None:
        self.llm_client = llm_client

    def _extract_domain(self, url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        domain = (parsed.netloc or "").strip().lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

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

    def _clamp_status_to_support(self, proposed_status: Any, fallback_status: str) -> str:
        normalized_fallback = str(fallback_status or "").strip().lower()
        normalized_proposed = str(proposed_status or "").strip().lower()
        if normalized_fallback == "disputed":
            return "disputed"
        if normalized_proposed == "disputed":
            return normalized_fallback or "inferred"

        confidence_order = {
            "inferred": 0,
            "directional": 1,
            "verified": 2,
            "confirmed": 3,
        }
        if normalized_fallback not in confidence_order:
            normalized_fallback = "inferred"
        if normalized_proposed not in confidence_order:
            return normalized_fallback
        if confidence_order[normalized_proposed] > confidence_order[normalized_fallback]:
            return normalized_fallback
        return normalized_proposed

    def _verification_state_from_status(self, status: str, fallback_verification_state: str) -> str:
        normalized_status = str(status or "").strip().lower()
        normalized_fallback = str(fallback_verification_state or "").strip().lower()
        if normalized_status == "disputed":
            return "conflicted"
        if normalized_status == "confirmed":
            return "confirmed"
        if normalized_status == "verified":
            return "supported"
        if normalized_status == "directional":
            return "directional"
        if normalized_fallback == "open_question":
            return "open_question"
        return "inferred"

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

        unique_domains = {
            self._extract_domain(item.get("source_url", ""))
            for item in support_evidence
            if self._extract_domain(item.get("source_url", ""))
        }
        independent_source_count = len(unique_domains)
        strong_support_count = sum(
            1
            for item in support_evidence
            if str(item.get("source_tier") or "").strip().lower() in {"t1", "t2"} or float(item.get("authority_score", 0) or 0) >= 0.72
        )
        if average_confidence >= 0.85 and independent_source_count >= 3 and strong_support_count >= 2:
            return (
                "confirmed",
                "confirmed",
                f"已有 {strong_support_count} 条高可信支撑，来自 {independent_source_count} 个独立域名，置信度 {average_confidence:.2f}。",
            )
        if average_confidence >= 0.70 and independent_source_count >= 2 and strong_support_count >= 1:
            return (
                "supported",
                "verified",
                f"已有 {strong_support_count} 条高可信支撑，来自 {independent_source_count} 个独立域名，置信度 {average_confidence:.2f}。",
            )
        if average_confidence >= 0.50 and (strong_support_count >= 1 or len(support_evidence) >= 2):
            return (
                "directional",
                "directional",
                f"当前依赖 {len(support_evidence)} 条证据（{independent_source_count} 个独立域名），置信度 {average_confidence:.2f}，方向性参考。",
            )
        return (
            "inferred",
            "inferred",
            f"仅有 {len(support_evidence)} 条中等强度证据，{independent_source_count} 个独立域名，置信度 {average_confidence:.2f}，需继续补证。",
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

    def _select_diverse_evidence(self, evidence: List[Dict[str, Any]], limit: int = 4) -> List[Dict[str, Any]]:
        domain_counts: Dict[str, int] = {}
        selected: List[Dict[str, Any]] = []
        ranked = sorted(
            evidence,
            key=lambda item: float(item.get("confidence", 0) or 0),
            reverse=True,
        )
        for item in ranked:
            domain = self._extract_domain(item.get("source_url", "")) or "__unknown__"
            if domain_counts.get(domain, 0) >= 2:
                continue
            selected.append(item)
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            if len(selected) >= limit:
                break
        if len(selected) < min(limit, len(ranked)):
            for item in ranked:
                if item in selected:
                    continue
                selected.append(item)
                if len(selected) >= limit:
                    break
        return selected

    def _select_llm_claim_evidence(
        self,
        evidence: List[Dict[str, Any]],
        max_total: int = 24,
        per_step: int = 4,
    ) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in evidence:
            step = str(item.get("market_step") or "unknown").strip() or "unknown"
            grouped[step].append(item)

        sampled: List[Dict[str, Any]] = []
        for step_items in grouped.values():
            ranked_step_items = sorted(
                step_items,
                key=lambda item: (
                    float(item.get("confidence", 0) or 0),
                    float(item.get("authority_score", 0) or 0),
                    float(item.get("freshness_score", 0) or 0),
                ),
                reverse=True,
            )
            sampled.extend(self._select_diverse_evidence(ranked_step_items, limit=max(1, per_step)))

        sampled = sorted(
            sampled,
            key=lambda item: (
                float(item.get("confidence", 0) or 0),
                float(item.get("authority_score", 0) or 0),
                float(item.get("freshness_score", 0) or 0),
            ),
            reverse=True,
        )

        deduped: List[Dict[str, Any]] = []
        seen_ids = set()
        for item in sampled:
            item_id = str(item.get("id") or "").strip()
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            deduped.append(item)
            if len(deduped) >= max_total:
                break

        if not deduped:
            return evidence[:max_total]
        return deduped

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
            diverse_evidence = self._select_diverse_evidence(step_evidence, limit=4)
            evidence_ids = [item["id"] for item in diverse_evidence]
            counter_evidence_ids = self._infer_counter_evidence_ids(step_evidence)
            supporting_evidence_ids, contradicting_evidence_ids = self._linked_support_ids(evidence_ids, counter_evidence_ids)
            average_confidence = round(
                sum(float(item.get("confidence", 0) or 0) for item in diverse_evidence) / max(1, len(diverse_evidence)),
                2,
            )
            support_evidence = [item for item in diverse_evidence if item["id"] in supporting_evidence_ids]
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
                        if request["research_mode"] == "deep" and status not in {"verified", "confirmed"}
                        else []
                    ),
                    "competitor_ids": sorted({item["competitor_name"] for item in step_evidence if item.get("competitor_name")})[:3],
                    "priority": "high" if index <= 3 else "medium",
                    "independent_source_count": len(
                        {
                            self._extract_domain(item.get("source_url", ""))
                            for item in diverse_evidence
                            if self._extract_domain(item.get("source_url", ""))
                        }
                    ),
                    "actionability_score": round(0.75 + min(index, 4) * 0.04, 2),
                    "last_verified_at": iso_now(),
                }
            )
        if not self.llm_client or not self.llm_client.is_enabled():
            return fallback_claims

        valid_evidence_ids = {item["id"] for item in evidence}
        evidence_by_id = {item["id"]: item for item in evidence}
        valid_competitors = sorted({item.get("competitor_name") for item in evidence if item.get("competitor_name")})
        llm_evidence_context = self._select_llm_claim_evidence(evidence, max_total=24, per_step=4)

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
                            f"evidence={json.dumps(llm_evidence_context, ensure_ascii=False)}\n"
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
                    status = self._clamp_status_to_support(item.get("status"), fallback_summary[1])
                    verification_state = self._verification_state_from_status(status, fallback_summary[0])
                    independent_source_count = len(
                        {
                            self._extract_domain(record.get("source_url", ""))
                            for record in (evidence_by_id.get(value) for value in evidence_ids)
                            if record and self._extract_domain(record.get("source_url", ""))
                        }
                    )
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
                            "independent_source_count": independent_source_count,
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
        strongest = self._select_diverse_evidence(sorted_evidence, limit=3)
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
            "caveats": ["这是针对追问的定向补充研究，仍建议和主报告中的用户验证结果交叉确认。"] if status not in {"verified", "confirmed"} else [],
            "competitor_ids": competitor_ids,
            "priority": "high",
            "independent_source_count": len(
                {
                    self._extract_domain(item.get("source_url", ""))
                    for item in strongest
                    if self._extract_domain(item.get("source_url", ""))
                }
            ),
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
                next_status = self._clamp_status_to_support(result.get("status"), fallback_claim["status"])
                next_verification_state = self._verification_state_from_status(
                    next_status,
                    fallback_claim["verification_state"],
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
                    "status": next_status,
                    "verification_state": next_verification_state,
                    "confidence_reason": result.get("confidence_reason") or fallback_claim["confidence_reason"],
                    "decision_impact": result.get("decision_impact") or fallback_claim["decision_impact"],
                    "caveats": result.get("caveats") if isinstance(result.get("caveats"), list) else fallback_claim["caveats"],
                    "competitor_ids": [value for value in result.get("competitor_ids", []) if value in competitor_ids][:4],
                    "priority": "high",
                    "independent_source_count": fallback_claim["independent_source_count"],
                    "actionability_score": round(
                        max(0.3, min(0.99, float(result.get("actionability_score", fallback_claim["actionability_score"])))),
                        2,
                    ),
                    "last_verified_at": iso_now(),
                }
        except Exception:
            return fallback_claim
        return fallback_claim
