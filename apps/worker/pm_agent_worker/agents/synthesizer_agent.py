import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pm_agent_worker.tools.minimax_client import MiniMaxChatClient
from pm_agent_worker.tools.prompt_loader import load_prompt_template
from pm_agent_worker.workflows.presentation_labels import (
    depth_preset_label,
    industry_template_label,
    market_step_label,
    research_mode_label,
    source_type_label,
    workflow_command_label,
)
from pm_agent_worker.workflows.research_models import iso_now


REPORT_SECTIONS = [
    "核心结论摘要",
    "研究范围与方法",
    "市场结构与趋势",
    "目标用户与关键任务",
    "竞争格局",
    "重点竞品拆解",
    "定价、商业模式与渠道",
    "产品体验与关键流程",
    "用户声音与情绪反馈",
    "机会地图",
    "风险与约束",
    "建议动作",
    "待验证问题",
]

REPORT_SECTION_STEP_MAP = {
    "市场结构与趋势": ["market-definition", "market-trends"],
    "目标用户与关键任务": ["user-research"],
    "竞争格局": ["competitor-analysis"],
    "重点竞品拆解": ["competitor-analysis"],
    "定价、商业模式与渠道": ["business-and-channels", "competitor-analysis"],
    "产品体验与关键流程": ["experience-teardown"],
    "用户声音与情绪反馈": ["reviews-and-sentiment"],
    "机会地图": ["opportunities-and-risks", "recommendations"],
    "风险与约束": ["opportunities-and-risks"],
    "建议动作": ["recommendations", "opportunities-and-risks", "user-research", "competitor-analysis"],
}

SECTION_HEADING_ALIASES = {
    "核心结论摘要": ["Executive Summary"],
    "决策快照": ["Decision Snapshot"],
    "研究范围与方法": ["Research Scope & Configuration"],
    "市场结构与趋势": ["Market Structure & Trends"],
    "目标用户与关键任务": ["Target Users & JTBD"],
    "竞争格局": ["Competitive Landscape"],
    "重点竞品拆解": ["Competitor Deep Dives"],
    "定价、商业模式与渠道": ["Pricing / Business Model / Channel"],
    "产品体验与关键流程": ["Product Experience Findings"],
    "用户声音与情绪反馈": ["Sentiment & Voice of Customer"],
    "机会地图": ["Opportunity Matrix"],
    "风险与约束": ["Risks & Constraints"],
    "建议动作": ["Recommended Actions"],
    "待验证问题": ["Open Questions"],
    "证据冲突与使用边界": ["Evidence Conflicts & Validation Boundary"],
    "关键证据摘录": ["Evidence Highlights"],
    "PM 反馈整合": ["PM Feedback Integration"],
    "一句话判断": ["Bottom Line"],
    "立刻推进的动作": ["Immediate Actions"],
    "使用边界": ["Boundaries"],
    "后续验证清单": ["Outstanding Validation Questions"],
    "研究步骤覆盖": ["Market Step Coverage"],
    "反馈记录": ["Feedback Log"],
}

STEP_IMPLICATIONS = {
    "market-definition": "帮助判断市场边界是否清晰，以及后续研究应如何切分赛道。",
    "market-trends": "帮助判断市场窗口、进入节奏和资源投入优先级。",
    "user-research": "帮助校准目标用户、核心场景和真实痛点。",
    "competitor-analysis": "帮助建立竞品基准，并识别差异化切入点。",
    "business-and-channels": "帮助判断定价、渠道和商业模式的可行性。",
    "experience-teardown": "帮助明确产品体验短板与能力建设方向。",
    "reviews-and-sentiment": "帮助识别高频好评/差评点和品牌心智。",
    "opportunities-and-risks": "帮助识别机会窗口、执行约束和潜在误判风险。",
    "recommendations": "帮助把研究结论转成可执行的 PM 动作。",
}

STATUS_LABELS = {
    "confirmed": "高置信已确认",
    "verified": "已验证",
    "directional": "方向性参考",
    "inferred": "推断",
    "disputed": "有争议",
    "unknown": "待确认",
}

PRIORITY_LABELS = {
    "critical": "P0",
    "high": "P1",
    "medium": "P2",
    "low": "P3",
}


class SynthesizerAgent:
    def __init__(self, llm_client: Optional[MiniMaxChatClient] = None) -> None:
        self.llm_client = llm_client

    def _competitor_detector(self):
        detector = getattr(self, "_competitor_detector_cache", None)
        if detector is None:
            from pm_agent_worker.agents.research_worker_agent import ResearchWorkerAgent

            detector = ResearchWorkerAgent()
            self._competitor_detector_cache = detector
        return detector

    def _prefers_chinese_locale(self, request: Dict[str, Any]) -> bool:
        locale = str(request.get("output_locale") or request.get("language") or "").lower()
        topic = str(request.get("topic") or "")
        return locale.startswith("zh") or bool(re.search(r"[\u4e00-\u9fff]", topic))

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _claim_text(self, claim: Dict[str, Any]) -> str:
        claim_text = str(claim.get("claim_text") or "").strip()
        if claim_text:
            return claim_text.rstrip("。；;，, ")
        caveats = claim.get("caveats") or []
        if isinstance(caveats, list):
            for item in caveats:
                text = str(item or "").strip()
                if text:
                    return text.rstrip("。；;，, ")
        return "待补充结构化结论"

    def _stage_label(self, request: Dict[str, Any], stage: str) -> str:
        if self._prefers_chinese_locale(request):
            return "终稿" if stage == "final" else "初稿"
        return "Final" if stage == "final" else "Draft"

    def _status_label(self, status: str) -> str:
        return STATUS_LABELS.get(str(status or "").strip(), "待确认")

    def _priority_label(self, priority: str, actionability_score: Any = None) -> str:
        normalized = str(priority or "").strip().lower()
        if normalized in PRIORITY_LABELS:
            return PRIORITY_LABELS[normalized]
        actionability = self._safe_float(actionability_score)
        if actionability >= 0.85:
            return "P1"
        if actionability >= 0.65:
            return "P2"
        return "P3"

    def _confidence_label(self, value: Any) -> str:
        ratio = self._safe_float(value)
        if ratio <= 1:
            ratio *= 100
        return f"{max(0.0, min(100.0, ratio)):.0f}%"

    def _short_text(self, text: Any, limit: int = 120) -> str:
        normalized = " ".join(str(text or "").replace("|", "/").split())
        if len(normalized) <= limit:
            return normalized or "待补充"
        return normalized[: limit - 3].rstrip() + "..."

    def _market_step_implication(self, market_step: str) -> str:
        return STEP_IMPLICATIONS.get(str(market_step or "").strip(), "帮助把零散信息整理成可讨论的 PM 判断。")

    def _market_step_label(self, market_step: Any) -> str:
        return market_step_label(str(market_step or ""))

    def _source_type_label(self, source_type: Any) -> str:
        return source_type_label(str(source_type or ""))

    def _render_table(self, headers: List[str], rows: List[List[Any]]) -> str:
        if not rows:
            return ""
        cleaned_headers = [self._short_text(header, limit=30) for header in headers]
        lines = [
            "| " + " | ".join(cleaned_headers) + " |",
            "| " + " | ".join(["---"] * len(cleaned_headers)) + " |",
        ]
        for row in rows:
            cleaned_row = [self._short_text(cell, limit=160) for cell in row]
            if len(cleaned_row) < len(cleaned_headers):
                cleaned_row.extend(["待补充"] * (len(cleaned_headers) - len(cleaned_row)))
            lines.append("| " + " | ".join(cleaned_row[: len(cleaned_headers)]) + " |")
        return "\n".join(lines)

    def _report_title(self, request: Dict[str, Any], stage: str) -> str:
        title = str(request.get("topic") or "研究主题").strip()
        return f"# {title} 市场研究报告（{self._stage_label(request, stage)}）"

    def _decision_readiness(self, claims: List[Dict[str, Any]], evidence: List[Dict[str, Any]]) -> str:
        if not claims or len(evidence) < 3:
            return "偏低"
        avg_confidence = sum(self._safe_float(item.get("confidence"), 0.5) for item in claims[:6]) / max(1, min(len(claims), 6))
        if len(claims) >= 5 and len(evidence) >= 10 and avg_confidence >= 0.72:
            return "较高"
        if len(claims) >= 3 and len(evidence) >= 6 and avg_confidence >= 0.62:
            return "中等"
        return "偏低"

    def _strip_code_fences(self, markdown: str) -> str:
        stripped = str(markdown or "").strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n", "", stripped, count=1)
            stripped = re.sub(r"\n```$", "", stripped)
        return stripped.strip()

    def _normalize_markdown(self, markdown: str) -> str:
        normalized = str(markdown or "").replace("\r\n", "\n").strip()
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    def _heading_aliases(self, heading: str) -> List[str]:
        normalized = str(heading or "").strip().lstrip("#").strip()
        if not normalized:
            return []

        aliases = {normalized}
        if normalized in SECTION_HEADING_ALIASES:
            aliases.update(SECTION_HEADING_ALIASES[normalized])
        for canonical, legacy_aliases in SECTION_HEADING_ALIASES.items():
            if normalized == canonical or normalized in legacy_aliases:
                aliases.add(canonical)
                aliases.update(legacy_aliases)
        return list(aliases)

    def _line_heading_text(self, line: str) -> str:
        return str(line or "").strip().lstrip("#").strip()

    def _heading_matches(self, line: str, heading: str) -> bool:
        line_heading = self._line_heading_text(line)
        return bool(line_heading) and line_heading in self._heading_aliases(heading)

    def _has_heading(self, markdown: str, heading: str) -> bool:
        return any(self._heading_matches(line, heading) for line in markdown.splitlines() if line.strip().startswith("## "))

    def _extract_section_block(self, markdown: str, heading: str) -> str:
        lines = markdown.splitlines()
        start_index = None
        for index, line in enumerate(lines):
            if self._heading_matches(line, heading):
                start_index = index
                break
        if start_index is None:
            return ""
        end_index = len(lines)
        for index in range(start_index + 1, len(lines)):
            if lines[index].startswith("## "):
                end_index = index
                break
        return "\n".join(lines[start_index:end_index]).strip()

    def _polish_generated_markdown(
        self,
        markdown: str,
        request: Dict[str, Any],
        stage: str,
        fallback_markdown: str,
        feedback_notes: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        polished = self._normalize_markdown(self._strip_code_fences(markdown))
        if not polished:
            return fallback_markdown
        if not any(line.startswith("# ") for line in polished.splitlines()):
            polished = f"{self._report_title(request, stage)}\n\n{polished}"

        required_sections = [
            "核心结论摘要",
            "决策快照",
            "研究范围与方法",
            "竞争格局",
            "证据冲突与使用边界",
            "建议动作",
            "待验证问题",
            "关键证据摘录",
        ]
        missing_blocks = []
        for heading in required_sections:
            if self._has_heading(polished, heading):
                continue
            block = self._extract_section_block(fallback_markdown, heading)
            if block:
                missing_blocks.append(block)
        if feedback_notes and not self._has_heading(polished, "PM 反馈整合"):
            block = self._extract_section_block(fallback_markdown, "PM 反馈整合")
            if block:
                missing_blocks.append(block)
        if missing_blocks:
            polished = f"{polished.rstrip()}\n\n" + "\n\n".join(missing_blocks)
        if feedback_notes and "## 补充问答" not in polished:
            polished = f"{polished.rstrip()}\n\n{self._build_feedback_addendum(feedback_notes)}"
        return self._normalize_markdown(polished)

    def _build_feedback_addendum(self, feedback_notes: List[Dict[str, Any]]) -> str:
        lines = ["## 补充问答", ""]
        for item in feedback_notes[-4:]:
            question = item.get("feedback") or item.get("question") or "补充问题"
            response = item.get("response") or item.get("action") or "已纳入报告修订。"
            lines.append(f"### {question}")
            lines.append(f"- 回答：{response}")
            if item.get("action") and item.get("action") != response:
                lines.append(f"- 处理：{item['action']}")
            lines.append("")
        return "\n".join(lines).strip()

    def _group_by_market_step(self, items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in items:
            grouped[item.get("market_step", "unknown")].append(item)
        return grouped

    def _top_claims(self, claims: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
        ranked = sorted(
            claims,
            key=lambda claim: (
                float(claim.get("actionability_score", 0)),
                float(claim.get("confidence", 0)),
            ),
            reverse=True,
        )
        return ranked[:limit]

    def _top_evidence(self, evidence: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
        ranked = sorted(
            evidence,
            key=lambda item: (
                float(item.get("confidence", 0)),
                float(item.get("authority_score", 0)),
                float(item.get("freshness_score", 0)),
            ),
            reverse=True,
        )
        return ranked[:limit]

    def _section_evidence_sufficiency(self, section: str, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        related_steps = REPORT_SECTION_STEP_MAP.get(section, [])
        if not related_steps:
            return {
                "section": section,
                "related_steps": [],
                "evidence_count": 0,
                "unique_domains": 0,
                "sufficient": True,
            }

        relevant_evidence = [
            item
            for item in evidence
            if str(item.get("market_step") or "").strip() in related_steps and not self._is_context_only_evidence(item)
        ]
        unique_domains = {
            domain
            for domain in (
                self._source_domain(item.get("source_url")) or str(item.get("source_domain") or "").strip().lower()
                for item in relevant_evidence
            )
            if domain
        }
        return {
            "section": section,
            "related_steps": related_steps,
            "evidence_count": len(relevant_evidence),
            "unique_domains": len(unique_domains),
            "sufficient": len(relevant_evidence) >= 3 and len(unique_domains) >= 2,
        }

    def _dedupe_text(self, items: List[str], limit: int = 8) -> List[str]:
        deduped: List[str] = []
        for item in items:
            cleaned = str(item or "").strip()
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned)
            if len(deduped) >= limit:
                break
        return deduped

    def _extract_report_outline(self, markdown: str, limit: int = 12) -> List[str]:
        outline: List[str] = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                outline.append(stripped.lstrip("#").strip())
            if len(outline) >= limit:
                break
        return outline

    def _normalize_lookup_text(self, text: Any) -> str:
        lowered = str(text or "").lower()
        lowered = re.sub(r"\s+", " ", lowered)
        return lowered.strip()

    def _canonical_competitor_name(self, value: Any) -> str:
        detector = self._competitor_detector()
        candidate = detector._normalize_competitor_name(value)
        if not candidate:
            return ""

        candidate = re.sub(r"[\(\[][^)\]]*[\)\]]", " ", candidate)
        candidate = re.sub(r"(?i)^(?:the|latest)\s+", "", candidate).strip()
        candidate = re.sub(r"(?i)^(?:glasses?|eyewear|smart)\s*", "", candidate)
        candidate = re.sub(
            r"(?i)\b(?:official|store|stores|pricing|review|reviews|camera|audio|assistant|translation|caption|record(?:ing)?|voice(?:-controlled)?|display(?:-free)?|screen|redefining|reality|introduces?|discover|explore|available|innovative|light|without|productivity|travel|shop|summary)\b",
            " ",
            candidate,
        )
        candidate = re.sub(r"(?i)\b(?:smart|full-function|built-in|open-ear)\b", " ", candidate)
        candidate = re.sub(r"(?i)\b(?:glasses?|eyewear|smartglasses|headset|headsets|earbuds?)\b", " ", candidate)
        candidate = re.sub(r"(?i)(?:\s+(?:AI|AR|XR))+$", "", candidate)
        candidate = re.sub(r"(?i)(?:AI|AR|XR)$", "", candidate)
        candidate = re.sub(r"(?:\s*(?:智能|官方|官网|商城|产品|品牌|平台|系统|眼镜|耳机|手机))+$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+", " ", candidate).strip(" -|/,:;")
        candidate = re.sub(r"(?i)(?:\s+(?:AI|AR|XR))+$", "", candidate).strip(" -|/,:;")
        candidate = re.sub(r"\b20\d{2}\b", "", candidate).strip(" -|/,:;")
        candidate = detector._normalize_competitor_name(candidate)
        if not candidate:
            return ""

        lowered = candidate.lower()
        lowered_tokens = [token for token in re.split(r"[\s\-_/&]+", lowered) if token]
        noise_tokens = {
            "available",
            "camera",
            "caption",
            "discover",
            "explore",
            "innovative",
            "introduces",
            "latest",
            "light",
            "productivity",
            "reality",
            "record",
            "recording",
            "redefining",
            "screen",
            "shop",
            "summary",
            "support",
            "supported",
            "translation",
            "travel",
            "voice",
            "without",
        }
        if any(token in noise_tokens for token in lowered_tokens):
            return ""
        if re.search(r"\d", candidate) and not re.search(r"[A-Za-z]{2,}\d", candidate):
            return ""
        if re.fullmatch(r"[\u4e00-\u9fff]{5,}", candidate) and not re.search(r"[A-Za-z0-9]", candidate):
            return ""
        if any(
            phrase in candidate
            for phrase in (
                "期待已久",
                "概括起来",
                "开发社区",
                "本文",
                "由于",
                "或成",
                "主打",
                "售价",
                "价格",
                "美元",
                "语音助手",
                "一窥",
                "无疑是",
                "这些",
                "高清巨幕观影",
                "翻译拍照录像",
            )
        ):
            return ""
        return candidate

    def _topic_competitor_seed_names(self, request: Optional[Dict[str, Any]]) -> List[str]:
        detector = self._competitor_detector()
        request_context = request or {}
        topic_signal = self._normalize_lookup_text(request_context.get("topic"))
        seeds: List[str] = list(detector._topic_exemplar_entities(request_context))
        if any(
            token in topic_signal
            for token in ("眼镜", "glasses", "rokid", "xreal", "ray-ban", "ray ban", "meta", "xiaomi", "小米", "雷鸟", "闪极")
        ):
            seeds.extend(["Ray-Ban Meta", "Oakley Meta", "Rokid", "小米", "XREAL", "雷鸟", "闪极", "李未可"])
        return detector._merge_competitor_names(seeds, limit=12)

    def _resolve_competitor_alias(self, request: Optional[Dict[str, Any]], text: str, value: Any) -> str:
        candidate = self._canonical_competitor_name(value)
        if not candidate:
            return ""
        normalized_text = self._normalize_lookup_text(text)
        lowered = self._normalize_lookup_text(candidate)
        candidate = re.sub(r"\b20\d{2}\b", "", candidate).strip(" -|/,:;")
        lowered = self._normalize_lookup_text(candidate)
        alias_map = {
            "xiaomi": "小米",
            "meta ray-bans": "Ray-Ban Meta",
            "ray bans": "Ray-Ban Meta",
            "乐奇": "Rokid",
        }
        resolved = alias_map.get(lowered, candidate)
        if lowered in {"ray ban", "ray-ban"} and "meta" in normalized_text:
            resolved = "Ray-Ban Meta"
        if lowered == "oakley" and "meta" in normalized_text:
            resolved = "Oakley Meta"
        resolved = self._canonical_competitor_name(resolved) or resolved
        resolved_lowered = self._normalize_lookup_text(resolved)
        if resolved.upper() in {"AI", "AR", "XR"}:
            return ""
        if resolved_lowered in {
            "amazon",
            "android",
            "android developers",
            "developers",
            "ofweek",
            "lenscrafters",
            "pcmag",
            "kickstarter",
            "知乎",
        }:
            return ""
        if resolved_lowered.endswith(" developers") or resolved_lowered.endswith(" store"):
            return ""
        return resolved

    def _extract_structured_competitor_candidates(self, text: str) -> List[str]:
        if not text:
            return []
        candidates: List[str] = []

        def append_candidate(raw: Any) -> None:
            cleaned = str(raw or "").strip()
            if cleaned and cleaned not in candidates:
                candidates.append(cleaned)

        for match in re.findall(r"\b([A-Z][A-Za-z0-9-]+(?:-[A-Z][A-Za-z0-9-]+)?\s+Meta)\b", text):
            append_candidate(match)

        for match in re.findall(
            r"(?i)([A-Z][A-Za-z0-9-]+(?:[- ][A-Z0-9][A-Za-z0-9-]+){0,2}(?:\s*(?:,|&|and)\s*[A-Z][A-Za-z0-9-]+(?:[- ][A-Z0-9][A-Za-z0-9-]+){0,2}){0,4})\s+(?:AI|AR|XR|smart\s+)?(?:glasses|eyewear|smartglasses)\b",
            text,
        ):
            for part in re.split(r"(?i)\s*(?:,|&|and)\s*", match):
                append_candidate(part)

        for match in re.findall(
            r"([\u4e00-\u9fffA-Za-z0-9-]{2,16}(?:[、，,/&和及与][\u4e00-\u9fffA-Za-z0-9-]{2,16}){0,4})等?\d*款?(?:AI|AR|XR|智能)?眼镜",
            text,
        ):
            for part in re.split(r"[、，,/&和及与]", match):
                append_candidate(part)

        for match in re.findall(r"([\u4e00-\u9fffA-Za-z0-9-]{2,16})(?:\s*(?:AI|AR|XR|智能))?眼镜", text):
            append_candidate(match)

        return candidates[:12]

    def _text_mentions_competitor(self, text: Any, competitor_name: Any) -> bool:
        normalized_text = self._normalize_lookup_text(text)
        normalized_name = self._normalize_lookup_text(competitor_name)
        if not normalized_text or not normalized_name:
            return False
        if re.search(r"[\u4e00-\u9fff]", normalized_name) or " " in normalized_name or "-" in normalized_name:
            return normalized_name in normalized_text
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized_name)}(?![a-z0-9])", normalized_text) is not None

    def _competitor_signal_text(self, item: Dict[str, Any]) -> str:
        return " ".join(
            str(item.get(field) or "").strip()
            for field in ("title", "summary", "extracted_fact", "quote", "source_url")
            if str(item.get(field) or "").strip()
        ).strip()

    def _sorted_competitor_evidence(self, evidence: List[Dict[str, Any]], competitor_name: str) -> List[Dict[str, Any]]:
        direct_matches = [item for item in evidence if str(item.get("competitor_name") or "").strip() == competitor_name]
        related = direct_matches or [
            item for item in evidence if self._text_mentions_competitor(self._competitor_signal_text(item), competitor_name)
        ]
        return sorted(
            related,
            key=lambda item: (
                self._safe_float(item.get("confidence")),
                self._safe_float(item.get("authority_score")),
                self._safe_float(item.get("freshness_score")),
            ),
            reverse=True,
        )

    def _rank_evidence_competitor_candidates(
        self,
        request: Optional[Dict[str, Any]],
        item: Dict[str, Any],
        preferred_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        detector = self._competitor_detector()
        request_context = request or {}
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        extracted_fact = str(item.get("extracted_fact") or "").strip()
        quote = str(item.get("quote") or "").strip()
        signal_text = " ".join(part for part in (title, summary, extracted_fact, quote) if part)
        if not signal_text:
            return []

        preferred_pool = detector._merge_competitor_names(
            preferred_names or [],
            self._topic_competitor_seed_names(request_context),
            limit=12,
        )

        explicit_name = self._canonical_competitor_name(item.get("competitor_name"))
        raw_candidates: List[tuple[str, str, str]] = []
        if explicit_name:
            raw_candidates.append((explicit_name, "explicit", explicit_name))
        for name in preferred_pool:
            cleaned_name = self._canonical_competitor_name(name)
            if cleaned_name and self._text_mentions_competitor(signal_text, cleaned_name):
                raw_candidates.append((cleaned_name, "preferred", cleaned_name))
        structured_candidates = self._extract_structured_competitor_candidates(signal_text)
        extracted_candidates = structured_candidates or detector._extract_competitor_candidates_from_text(signal_text)
        for raw in extracted_candidates:
            cleaned_name = self._resolve_competitor_alias(request_context, signal_text, raw)
            if cleaned_name:
                raw_candidates.append((cleaned_name, "text", str(raw or "")))
        domain_candidate = self._resolve_competitor_alias(
            request_context,
            signal_text,
            detector._extract_domain_competitor_candidate(str(item.get("source_url") or "").strip())
        )
        if domain_candidate:
            raw_candidates.append((domain_candidate, "domain", domain_candidate))

        title_signal = detector._normalize_phrase_signal(title)
        summary_signal = detector._normalize_phrase_signal(summary)
        quote_signal = detector._normalize_phrase_signal(quote)
        fact_signal = detector._normalize_phrase_signal(extracted_fact)
        url_signal = detector._normalize_phrase_signal(item.get("source_url"))
        explicit_signal = detector._normalize_phrase_signal(explicit_name)
        domain_signal = detector._normalize_phrase_signal(domain_candidate)
        valid_names: Dict[str, str] = {}
        for candidate, _origin, _match_text in raw_candidates:
            signal = detector._normalize_phrase_signal(candidate)
            if not signal:
                continue
            if request_context and detector._candidate_matches_topic(request_context, candidate):
                continue
            valid_names.setdefault(signal, candidate)
        if not valid_names:
            return []

        scored: Dict[str, Dict[str, Any]] = {}
        combined_signal = detector._normalize_phrase_signal(signal_text)
        for candidate, origin, match_text in raw_candidates:
            signal = detector._normalize_phrase_signal(candidate)
            if signal not in valid_names:
                continue
            match_signal = detector._normalize_phrase_signal(match_text)
            signals_to_match = {signal, match_signal}
            score = 0.0
            if explicit_signal and signal == explicit_signal:
                score += 4.5
            if any(match and match in title_signal for match in signals_to_match):
                score += 2.4
            if any(match and match in summary_signal for match in signals_to_match):
                score += 1.4
            if any(match and match in quote_signal for match in signals_to_match):
                score += 0.9
            if any(match and match in fact_signal for match in signals_to_match):
                score += 0.7
            if origin == "preferred":
                score += 1.1
            if origin == "domain":
                score += 0.5
            if str(item.get("market_step") or "").strip() in {"competitor-analysis", "business-and-channels", "experience-teardown"}:
                score += 0.6
            if url_signal and any(match and match.replace(" ", "") in url_signal for match in signals_to_match):
                score += 0.3
            candidate_position = min(
                (
                    combined_signal.find(match)
                    for match in signals_to_match
                    if match and combined_signal.find(match) >= 0
                ),
                default=-1,
            )
            if candidate_position >= 0:
                score += max(0.0, 0.5 - min(candidate_position, 120) / 320.0)
            if re.search(r"[\u4e00-\u9fff]", candidate) or len(signal.split()) >= 2:
                score += 0.3
            if domain_signal and signal == domain_signal and any(
                other_signal != signal and (other_signal.startswith(signal + " ") or other_signal.endswith(" " + signal))
                for other_signal in valid_names
            ):
                score -= 1.6
            if " " not in signal and not re.search(r"[\u4e00-\u9fff]", candidate) and any(
                other_signal != signal and other_signal.endswith(" " + signal)
                for other_signal in valid_names
            ):
                score -= 1.0
            if score < 2.2:
                continue
            current = scored.get(signal)
            if not current or score > float(current.get("score") or 0.0):
                scored[signal] = {"name": valid_names[signal], "score": score}

        return sorted(
            scored.values(),
            key=lambda entry: (-float(entry.get("score") or 0.0), len(str(entry.get("name") or ""))),
        )

    def _candidate_competitor_names(
        self,
        evidence: List[Dict[str, Any]],
        limit: int = 8,
        request: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        detector = self._competitor_detector()
        scores: Dict[str, Dict[str, Any]] = {}
        for index, item in enumerate(evidence):
            ranked_candidates = self._rank_evidence_competitor_candidates(request, item)
            for rank, entry in enumerate(ranked_candidates[:2]):
                name = str(entry.get("name") or "").strip()
                signal = detector._normalize_phrase_signal(name)
                if not signal:
                    continue
                record = scores.setdefault(
                    signal,
                    {
                        "name": name,
                        "score": 0.0,
                        "count": 0,
                        "first_seen": index,
                    },
                )
                record["score"] += max(0.0, float(entry.get("score") or 0.0) - (rank * 0.25))
                record["count"] += 1
                record["first_seen"] = min(int(record.get("first_seen") or index), index)
                if len(name) > len(str(record.get("name") or "")):
                    record["name"] = name

        if not scores:
            return []

        merged_scores = dict(scores)
        for signal, record in list(scores.items()):
            for other_signal, other_record in list(merged_scores.items()):
                if signal == other_signal:
                    continue
                if other_signal.startswith(signal + " "):
                    other_record["score"] = float(other_record.get("score") or 0.0) + float(record.get("score") or 0.0) * 0.65
                    other_record["count"] = int(other_record.get("count") or 0) + int(record.get("count") or 0)
                    other_record["first_seen"] = min(int(other_record.get("first_seen") or 0), int(record.get("first_seen") or 0))
                    merged_scores.pop(signal, None)
                    break

        ranked_names: List[str] = []
        ranked_records = sorted(
            merged_scores.values(),
            key=lambda entry: (
                -float(entry.get("score") or 0.0),
                -int(entry.get("count") or 0),
                int(entry.get("first_seen") or 0),
                str(entry.get("name") or ""),
            ),
        )
        all_signals = {
            detector._normalize_phrase_signal(str(record.get("name") or "").strip())
            for record in ranked_records
            if str(record.get("name") or "").strip()
        }
        seed_signals = {
            detector._normalize_phrase_signal(name)
            for name in self._topic_competitor_seed_names(request)
            if detector._normalize_phrase_signal(name)
        }
        for record in ranked_records:
            name = str(record.get("name") or "").strip()
            signal = detector._normalize_phrase_signal(name)
            if not name:
                continue
            if float(record.get("score") or 0.0) < 3.0 and int(record.get("count") or 0) < 2:
                continue
            if seed_signals and signal not in seed_signals:
                continue
            if " " not in signal and not re.search(r"[\u4e00-\u9fff]", name) and any(
                other_signal != signal and other_signal.endswith(" " + signal)
                for other_signal in all_signals
            ):
                continue
            ranked_names.append(name)
        return ranked_names[:limit]

    def backfill_evidence_competitors(
        self,
        request: Dict[str, Any],
        evidence: List[Dict[str, Any]],
        competitor_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        detector = self._competitor_detector()
        preferred_names = list(competitor_names or [])
        if not preferred_names:
            preferred_names = self._candidate_competitor_names(evidence, limit=10, request=request)
        allowed_signals = {
            detector._normalize_phrase_signal(name)
            for name in [*preferred_names, *self._topic_competitor_seed_names(request)]
            if detector._normalize_phrase_signal(name)
        }

        normalized_evidence: List[Dict[str, Any]] = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            normalized_item = dict(item)
            if not str(normalized_item.get("competitor_name") or "").strip():
                ranked_candidates = self._rank_evidence_competitor_candidates(request, normalized_item, preferred_names)
                for candidate in ranked_candidates:
                    candidate_name = str(candidate.get("name") or "").strip()
                    candidate_signal = detector._normalize_phrase_signal(candidate_name)
                    if candidate_name and candidate_signal in allowed_signals:
                        normalized_item["competitor_name"] = candidate_name
                        break
            normalized_evidence.append(normalized_item)
        return normalized_evidence

    def _looks_like_placeholder(self, text: Any) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return True
        return normalized.startswith("待补充") or normalized.startswith("未见明确") or normalized in {"待确认", "未知"}

    def _pricing_signal(self, text: Any) -> bool:
        normalized = self._normalize_lookup_text(text)
        if not normalized:
            return False
        pricing_tokens = (
            "pricing",
            "price",
            "plan",
            "plans",
            "billing",
            "subscription",
            "seat",
            "quote",
            "free",
            "enterprise",
            "starter",
            "定价",
            "价格",
            "套餐",
            "计费",
            "报价",
            "免费",
            "付费",
            "元/月",
            "元/年",
        )
        if any(token in normalized for token in pricing_tokens):
            return True
        return bool(
            re.search(r"(?:[$€¥￥]\s?\d[\d,]*(?:\.\d+)?)|(?:\d[\d,]*(?:\.\d+)?\s*(?:元|美元|usd|cny))", normalized)
        )

    def _pick_competitor_signal(
        self,
        related_evidence: List[Dict[str, Any]],
        preferred_steps: List[str],
        keyword_hints: List[str],
        exclude_texts: Optional[List[str]] = None,
        fallback: str = "待补充",
    ) -> str:
        excluded = {str(item or "").strip() for item in (exclude_texts or []) if str(item or "").strip()}
        preferred_step_set = set(preferred_steps)
        keyword_set = {self._normalize_lookup_text(item) for item in keyword_hints if self._normalize_lookup_text(item)}
        best_with_keywords = ""
        best_preferred_step = ""
        best_any = ""
        for item in related_evidence:
            candidates = [
                self._short_text(item.get("summary"), limit=120),
                self._short_text(item.get("extracted_fact"), limit=120),
                self._short_text(item.get("quote"), limit=120),
            ]
            for candidate in candidates:
                if not candidate or candidate in excluded:
                    continue
                if not best_any:
                    best_any = candidate
                normalized = self._normalize_lookup_text(candidate)
                if keyword_set and any(keyword in normalized for keyword in keyword_set):
                    return candidate
                if not best_with_keywords and keyword_set and any(token in normalized for token in keyword_set):
                    best_with_keywords = candidate
                if not best_preferred_step and str(item.get("market_step") or "") in preferred_step_set:
                    best_preferred_step = candidate
        return best_with_keywords or best_preferred_step or best_any or fallback

    def _competitor_category(self, related_evidence: List[Dict[str, Any]]) -> str:
        combined = self._normalize_lookup_text(" ".join(self._competitor_signal_text(item) for item in related_evidence[:6]))
        indirect_tokens = ("间接", "替代", "替代品", "替代方案", "alternative", "alternatives", "adjacent")
        direct_tokens = ("直接", "竞品", "竞争", "competitor", "head-to-head", "vs", "对标", "comparison")
        indirect_hits = sum(1 for token in indirect_tokens if token in combined)
        direct_hits = sum(1 for token in direct_tokens if token in combined)
        if indirect_hits > direct_hits:
            return "indirect"
        if direct_hits > 0:
            return "direct"
        if any(str(item.get("market_step") or "") == "competitor-analysis" for item in related_evidence):
            return "direct"
        return "indirect" if any("alternative" in self._normalize_lookup_text(self._competitor_signal_text(item)) for item in related_evidence) else "direct"

    def _competitor_pricing(self, related_evidence: List[Dict[str, Any]]) -> str:
        prioritized = sorted(
            related_evidence,
            key=lambda item: (
                str(item.get("market_step") or "") == "business-and-channels",
                str(item.get("source_type") or "") == "pricing",
                self._safe_float(item.get("confidence")),
            ),
            reverse=True,
        )
        for item in prioritized:
            for field in ("summary", "extracted_fact", "quote", "title"):
                candidate = self._short_text(item.get(field), limit=100)
                if candidate and self._pricing_signal(candidate):
                    return candidate
        return "未见明确公开定价，需补充价格页或渠道报价。"

    def _competitor_coverage_gap(self, related_evidence: List[Dict[str, Any]], pricing: str) -> str:
        gaps: List[str] = []
        source_domains = {self._source_domain(item.get("source_url")) for item in related_evidence if self._source_domain(item.get("source_url"))}
        source_types = {str(item.get("source_type") or "").strip().lower() for item in related_evidence if str(item.get("source_type") or "").strip()}
        if len(source_domains) < 2:
            gaps.append("来源交叉验证不足")
        if self._looks_like_placeholder(pricing):
            gaps.append("缺少统一价格口径")
        if "documentation" not in source_types and "pricing" not in source_types and "web" not in source_types:
            gaps.append("缺少官网或定价页")
        if "review" not in source_types and "community" not in source_types:
            gaps.append("缺少用户侧反馈")
        return "；".join(gaps[:2]) or "下一轮可补充功能矩阵、价格与渠道差异。"

    def _build_competitor_profiles(
        self,
        evidence: List[Dict[str, Any]],
        competitor_names: Optional[List[str]] = None,
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        ordered_names = list(competitor_names or [])
        if not ordered_names:
            for name in self._candidate_competitor_names(evidence, limit=max(limit, 8)):
                if name not in ordered_names:
                    ordered_names.append(name)

        profiles: List[Dict[str, Any]] = []
        for name in ordered_names[:limit]:
            cleaned_name = str(name or "").strip()
            if not cleaned_name:
                continue
            related_evidence = self._sorted_competitor_evidence(evidence, cleaned_name)
            positioning = self._pick_competitor_signal(
                related_evidence,
                preferred_steps=["competitor-analysis", "experience-teardown", "business-and-channels"],
                keyword_hints=["定位", "主打", "面向", "focus", "position", "feature", "场景", "workflow"],
                fallback="当前已识别该竞品，但定位描述仍需补充。",
            )
            pricing = self._competitor_pricing(related_evidence)
            differentiation = self._pick_competitor_signal(
                related_evidence,
                preferred_steps=["competitor-analysis", "reviews-and-sentiment", "user-research", "experience-teardown"],
                keyword_hints=["差异", "区别", "versus", "different", "优势", "shortcoming", "体验", "痛点", "续航", "渠道"],
                exclude_texts=[positioning],
                fallback="当前主要差异仍需补充更多对比证据。",
            )
            source_domains = self._dedupe_text(
                [self._source_domain(item.get("source_url")) for item in related_evidence if self._source_domain(item.get("source_url"))],
                limit=4,
            )
            source_types = self._dedupe_text(
                [self._source_type_label(item.get("source_type")) for item in related_evidence if item.get("source_type")],
                limit=4,
            )
            highlights = [
                {
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "source_url": item.get("source_url"),
                    "source_type": item.get("source_type"),
                    "source_type_label": self._source_type_label(item.get("source_type")),
                    "source_domain": self._source_domain(item.get("source_url")) or item.get("source_domain"),
                    "source_tier_label": self._source_tier_label(item),
                    "citation_label": self._citation_label(item, index),
                    "market_step": item.get("market_step"),
                }
                for index, item in enumerate(related_evidence[:3])
            ]
            profiles.append(
                {
                    "name": cleaned_name,
                    "category": self._competitor_category(related_evidence),
                    "positioning": positioning,
                    "pricing": pricing,
                    "differentiation": differentiation,
                    "coverage_gap": self._competitor_coverage_gap(related_evidence, pricing),
                    "evidence_count": len(related_evidence),
                    "source_count": len(source_domains),
                    "source_domains": source_domains,
                    "source_types": source_types,
                    "key_sources": [
                        self._short_text(
                            f"{highlight.get('citation_label') or ''} {highlight.get('source_domain') or ''} {highlight.get('source_type_label') or ''}".strip(),
                            limit=80,
                        )
                        for highlight in highlights[:2]
                    ],
                    "highlights": highlights,
                }
            )
        return profiles

    def _build_competitor_snapshot(self, competitor_names: List[str], evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self._build_competitor_profiles(evidence, competitor_names=competitor_names, limit=8)

    def _build_market_step_dossier(self, claims: List[Dict[str, Any]], evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        claims_by_step = self._group_by_market_step(claims)
        evidence_by_step = self._group_by_market_step(evidence)
        ordered_steps = list(dict.fromkeys([*claims_by_step.keys(), *evidence_by_step.keys()]))
        dossier: List[Dict[str, Any]] = []
        for step in ordered_steps:
            step_claims = sorted(
                claims_by_step.get(step, []),
                key=lambda item: (float(item.get("actionability_score", 0)), float(item.get("confidence", 0))),
                reverse=True,
            )[:3]
            step_evidence = sorted(
                evidence_by_step.get(step, []),
                key=lambda item: (float(item.get("confidence", 0)), float(item.get("authority_score", 0))),
                reverse=True,
            )[:3]
            dossier.append(
                {
                    "market_step": step,
                    "claims": [
                        {
                            "id": claim.get("id"),
                            "claim_text": claim.get("claim_text"),
                            "status": claim.get("status"),
                            "confidence": claim.get("confidence"),
                            "priority": claim.get("priority"),
                            "caveats": claim.get("caveats", [])[:3],
                        }
                        for claim in step_claims
                    ],
                    "evidence": [
                        {
                            "title": item.get("title"),
                            "summary": item.get("summary"),
                            "source_url": item.get("source_url"),
                            "source_type": item.get("source_type"),
                            "confidence": item.get("confidence"),
                        }
                        for item in step_evidence
                    ],
                }
            )
        return dossier

    def _build_report_dossier(
        self,
        request: Dict[str, Any],
        claims: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        competitor_names: List[str],
        feedback_notes: Optional[List[Dict[str, Any]]] = None,
        conversation_excerpt: Optional[List[Dict[str, str]]] = None,
        current_report: Optional[Dict[str, Any]] = None,
        stage: str = "draft",
        include_current_report_excerpt: bool = False,
    ) -> Dict[str, Any]:
        feedback_notes = feedback_notes or []
        current_report = current_report or {}
        top_claims = self._top_claims(claims, limit=5)
        top_evidence = self._top_evidence(evidence, limit=6)
        open_questions = self._dedupe_text(
            [caveat for claim in claims for caveat in claim.get("caveats", [])],
            limit=8,
        )
        return {
            "request": {
                "topic": request.get("topic"),
                "industry_template": request.get("industry_template"),
                "research_mode": request.get("research_mode"),
                "depth_preset": request.get("depth_preset"),
                "workflow_command": request.get("workflow_command"),
                "workflow_label": request.get("workflow_label"),
                "project_memory": request.get("project_memory"),
                "geo_scope": request.get("geo_scope", []),
                "language": request.get("language", "zh-CN"),
                "output_locale": request.get("output_locale", "zh-CN"),
            },
            "report_stage": stage,
            "counts": {
                "claim_count": len(claims),
                "evidence_count": len(evidence),
                "competitor_count": len(competitor_names),
                "feedback_count": len(feedback_notes),
            },
            "source_footprint": {
                "unique_domains": self._unique_domain_count(evidence),
                "source_type_mix": self._source_type_mix(evidence),
                "source_tier_mix": self._source_tier_mix(evidence),
                "confirmed_claims": sum(1 for claim in claims if str(claim.get("status") or "").strip() == "confirmed"),
                "verified_claims": sum(
                    1 for claim in claims if str(claim.get("status") or "").strip() in {"verified", "confirmed"}
                ),
                "directional_claims": sum(1 for claim in claims if str(claim.get("status") or "").strip() == "directional"),
                "inferred_claims": sum(1 for claim in claims if str(claim.get("status") or "").strip() == "inferred"),
                "disputed_claims": sum(1 for claim in claims if str(claim.get("status") or "").strip() == "disputed"),
            },
            "top_claims": [
                {
                    "id": claim.get("id"),
                    "claim_text": claim.get("claim_text"),
                    "market_step": claim.get("market_step"),
                    "status": claim.get("status"),
                    "confidence": claim.get("confidence"),
                    "priority": claim.get("priority"),
                    "actionability_score": claim.get("actionability_score"),
                    "caveats": claim.get("caveats", [])[:3],
                }
                for claim in top_claims
            ],
            "top_evidence": [
                {
                    "citation_label": self._citation_label(item, index),
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "source_url": item.get("source_url"),
                    "source_domain": self._source_domain(item.get("source_url")) or item.get("source_domain"),
                    "source_type": item.get("source_type"),
                    "source_tier": self._source_tier(item),
                    "source_tier_label": self._source_tier_label(item),
                    "market_step": item.get("market_step"),
                    "confidence": item.get("confidence"),
                    "competitor_name": item.get("competitor_name"),
                }
                for index, item in enumerate(top_evidence)
            ],
            "market_steps": self._build_market_step_dossier(claims, evidence),
            "competitors": self._build_competitor_snapshot(competitor_names, evidence),
            "argument_chains": self._build_argument_chains(claims, evidence),
            "section_sufficiency": {
                section: self._section_evidence_sufficiency(section, evidence) for section in REPORT_SECTIONS
            },
            "citation_registry": self._build_citation_registry(evidence),
            "open_questions": open_questions,
            "pm_feedback": [
                {
                    "question": item.get("question") or item.get("feedback"),
                    "response": item.get("response"),
                    "action": item.get("action"),
                    "claim_id": item.get("claim_id"),
                    "created_at": item.get("created_at"),
                }
                for item in feedback_notes[-6:]
            ],
            "conversation_excerpt": (conversation_excerpt or [])[-8:],
            "current_report_outline": self._extract_report_outline(str(current_report.get("markdown") or "")),
            "current_report_excerpt": str(current_report.get("markdown") or "")[:2400] if include_current_report_excerpt else "",
        }

    def _source_domain(self, url: Any) -> str:
        parsed = urlparse(str(url or "").strip())
        domain = (parsed.netloc or parsed.path or "").strip().lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def _is_context_only_evidence(self, item: Dict[str, Any]) -> bool:
        source_url = str(item.get("source_url") or "").strip().lower()
        source_type = str(item.get("source_type") or "").strip().lower()
        evidence_role = str(item.get("evidence_role") or "").strip().lower()
        tags = {str(tag or "").strip().lower() for tag in (item.get("tags") or []) if str(tag or "").strip()}
        if source_url.startswith("internal://delta-context/"):
            return True
        if source_type == "internal":
            return True
        if evidence_role in {"context_only", "internal_context"}:
            return True
        return "delta-context-fallback" in tags or "context-only" in tags

    def _is_non_finalizable_evidence(self, item: Dict[str, Any]) -> bool:
        if self._is_context_only_evidence(item):
            return True
        source_tier = self._source_tier(item)
        if source_tier == "t4":
            return True
        final_eligibility = str(item.get("final_eligibility") or "").strip().lower()
        if final_eligibility in {"requires_external_evidence", "not_finalizable", "context_only"}:
            return True
        return False

    def _filter_finalizable_material(
        self,
        claims: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
        formal_evidence = [item for item in evidence if not self._is_non_finalizable_evidence(item)]
        formal_evidence_ids = {str(item.get("id") or "").strip() for item in formal_evidence if str(item.get("id") or "").strip()}
        formal_steps = {str(item.get("market_step") or "").strip() for item in formal_evidence if str(item.get("market_step") or "").strip()}
        formal_claims: List[Dict[str, Any]] = []
        for claim in claims:
            evidence_ids = {str(item).strip() for item in (claim.get("evidence_ids") or []) if str(item).strip()}
            if evidence_ids:
                if evidence_ids & formal_evidence_ids:
                    formal_claims.append(claim)
                continue
            market_step = str(claim.get("market_step") or "").strip()
            if market_step and market_step in formal_steps:
                formal_claims.append(claim)
        return (
            formal_claims,
            formal_evidence,
            {
                "excluded_context_only_claims": max(0, len(claims) - len(formal_claims)),
                "excluded_context_only_evidence": max(0, len(evidence) - len(formal_evidence)),
                "excluded_non_finalizable_evidence": max(0, len(evidence) - len(formal_evidence)),
            },
        )

    def _source_tier(self, item: Dict[str, Any]) -> str:
        if self._is_context_only_evidence(item):
            return "t4"
        explicit = str(item.get("source_tier") or "").strip().lower()
        if explicit:
            return explicit
        source_type = str(item.get("source_type") or "").strip().lower()
        authority = self._safe_float(item.get("authority_score"), 0.0)
        freshness = self._safe_float(item.get("freshness_score"), 0.0)
        confidence = self._safe_float(item.get("confidence"), 0.0)
        tags = {str(tag or "").strip().lower() for tag in (item.get("tags") or []) if str(tag or "").strip()}
        if "search-snippet" in tags or confidence < 0.48:
            return "t4"
        if source_type in {"documentation", "pricing"} and authority >= 0.72 and confidence >= 0.66:
            return "t1"
        if authority >= 0.84 and freshness >= 0.68 and confidence >= 0.72:
            return "t1"
        if authority >= 0.68 and confidence >= 0.62:
            return "t2"
        if source_type in {"community", "review"} or confidence >= 0.54:
            return "t3"
        return "t4"

    def _source_tier_label(self, item: Dict[str, Any]) -> str:
        if self._is_context_only_evidence(item) and not str(item.get("source_tier_label") or "").strip():
            return "T4 内部上下文线索（不可单独成稿）"
        tier = self._source_tier(item)
        default_labels = {
            "t1": "T1 一手/高权威",
            "t2": "T2 高可信交叉来源",
            "t3": "T3 补充佐证",
            "t4": "T4 待核验线索",
        }
        return str(item.get("source_tier_label") or default_labels.get(tier) or default_labels["t4"]).strip()

    def _citation_label(self, item: Dict[str, Any], fallback_index: int = 0) -> str:
        existing = str(item.get("citation_label") or "").strip()
        if existing:
            return existing
        return f"[S{max(1, fallback_index + 1)}]"

    def _tier_priority(self, item: Dict[str, Any]) -> int:
        return {
            "t1": 4,
            "t2": 3,
            "t3": 2,
            "t4": 1,
        }.get(self._source_tier(item), 1)

    def _source_reference_text(self, item: Dict[str, Any], fallback_index: int = 0, include_tier: bool = True) -> str:
        citation = self._citation_label(item, fallback_index)
        domain = self._source_domain(item.get("source_url")) or str(item.get("source_domain") or "未知来源")
        if include_tier:
            return f"{citation} {domain} / {self._source_tier_label(item)}"
        return f"{citation} {domain}"

    def _source_tier_mix(self, evidence: List[Dict[str, Any]]) -> Dict[str, int]:
        mix: Dict[str, int] = defaultdict(int)
        for item in evidence:
            mix[self._source_tier_label(item)] += 1
        return dict(sorted(mix.items(), key=lambda pair: (-pair[1], pair[0])))

    def _build_citation_registry(self, evidence: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
        evidence = [item for item in evidence if not self._is_context_only_evidence(item)]
        ranked = sorted(
            evidence,
            key=lambda item: (
                self._tier_priority(item),
                self._safe_float(item.get("confidence"), 0),
                self._safe_float(item.get("authority_score"), 0),
                self._safe_float(item.get("freshness_score"), 0),
            ),
            reverse=True,
        )
        registry: List[Dict[str, Any]] = []
        seen = set()
        for index, item in enumerate(ranked):
            citation = self._citation_label(item, index)
            if citation in seen:
                continue
            seen.add(citation)
            registry.append(
                {
                    "citation_label": citation,
                    "title": item.get("title"),
                    "domain": self._source_domain(item.get("source_url")) or item.get("source_domain"),
                    "source_type": item.get("source_type"),
                    "source_tier": self._source_tier(item),
                    "source_tier_label": self._source_tier_label(item),
                    "summary": item.get("summary") or item.get("extracted_fact"),
                    "source_url": item.get("source_url"),
                    "confidence": item.get("confidence"),
                }
            )
            if len(registry) >= limit:
                break
        return registry

    def _supporting_evidence_for_claim(self, claim: Dict[str, Any], evidence: List[Dict[str, Any]], limit: int = 2) -> List[Dict[str, Any]]:
        evidence = [item for item in evidence if not self._is_context_only_evidence(item)]
        evidence_ids = [str(item) for item in (claim.get("evidence_ids") or []) if str(item).strip()]
        matched = [item for item in evidence if str(item.get("id") or "") in evidence_ids]

        def select_diverse(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            ranked = sorted(
                items,
                key=lambda item: (
                    self._safe_float(item.get("confidence"), 0),
                    self._safe_float(item.get("authority_score"), 0),
                    self._safe_float(item.get("freshness_score"), 0),
                ),
                reverse=True,
            )
            selected: List[Dict[str, Any]] = []
            selected_domains = set()
            for item in ranked:
                domain = self._source_domain(item.get("source_url")) or str(item.get("source_domain") or "").strip().lower()
                if domain and domain in selected_domains:
                    continue
                selected.append(item)
                if domain:
                    selected_domains.add(domain)
                if len(selected) >= limit:
                    return selected
            for item in ranked:
                if item in selected:
                    continue
                selected.append(item)
                if len(selected) >= limit:
                    break
            return selected

        if matched:
            return select_diverse(matched)

        market_step = str(claim.get("market_step") or "").strip()
        related = [item for item in evidence if str(item.get("market_step") or "").strip() == market_step]
        return select_diverse(related)

    def _claim_boundary_text(self, claim: Dict[str, Any]) -> str:
        caveats = self._dedupe_text([str(item) for item in claim.get("caveats", []) if str(item).strip()], limit=2)
        if caveats:
            return "；".join(caveats)
        status = str(claim.get("status") or "").strip()
        if status == "disputed":
            return "存在冲突证据，使用时需谨慎。"
        if status in {"inferred", "directional"}:
            return "当前更偏方向性推断，仍需补充直接证据。"
        return "当前未见明显结构化边界，但仍应结合证据覆盖范围理解。"

    def _claim_citation_note(self, claim: Dict[str, Any], evidence: List[Dict[str, Any]], limit: int = 2) -> str:
        support = self._supporting_evidence_for_claim(claim, evidence, limit=limit)
        labels = [self._citation_label(item, index) for index, item in enumerate(support)]
        if not labels:
            return ""
        return f"（见 {'、'.join(labels)}）"

    def _section_argument_paragraphs(
        self,
        dossier: Dict[str, Any],
        related_steps: List[str],
        limit: int = 2,
    ) -> List[str]:
        if not related_steps:
            return []
        paragraphs: List[str] = []
        for chain in dossier.get("argument_chains", []):
            market_step = str(chain.get("market_step") or "").strip()
            if market_step not in related_steps:
                continue
            support = chain.get("support") or []
            support_refs = "、".join(
                [
                    f"{item.get('citation_label')} {item.get('domain')}"
                    for item in support[:2]
                    if item.get("citation_label") and item.get("domain")
                ]
            )
            support_text = "；".join(
                [
                    self._short_text(item.get("summary") or item.get("title"), 80)
                    for item in support[:2]
                    if item.get("summary") or item.get("title")
                ]
            )
            paragraph = (
                f"当前判断是“{chain.get('claim_text')}”。之所以形成这一判断，主要因为 {support_text or '当前已出现相对一致的支持线索'}"
                f"{f'（见 {support_refs}）' if support_refs else ''}。"
                f"这对 PM 的直接含义是：{chain.get('pm_implication') or '可作为下一轮动作设计输入'}。"
                f"同时仍需保留的边界是：{chain.get('boundary') or '当前证据边界仍需继续核验'}。"
            )
            paragraphs.append(paragraph)
            if len(paragraphs) >= limit:
                break
        return paragraphs

    def _build_argument_chains(self, claims: List[Dict[str, Any]], evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        chains: List[Dict[str, Any]] = []
        for claim in self._top_claims(claims, limit=6):
            support = self._supporting_evidence_for_claim(claim, evidence, limit=2)
            chains.append(
                {
                    "claim_text": self._claim_text(claim),
                    "market_step": claim.get("market_step"),
                    "status": claim.get("status"),
                    "confidence": claim.get("confidence"),
                    "pm_implication": self._market_step_implication(str(claim.get("market_step") or "")),
                    "boundary": self._claim_boundary_text(claim),
                    "independent_source_count": len(
                        {
                            domain
                            for domain in (
                                self._source_domain(item.get("source_url")) or str(item.get("source_domain") or "").strip().lower()
                                for item in support
                            )
                            if domain
                        }
                    ),
                    "support": [
                        {
                            "citation_label": self._citation_label(item, index),
                            "title": item.get("title"),
                            "summary": item.get("summary"),
                            "source_type": item.get("source_type"),
                            "source_url": item.get("source_url"),
                            "domain": self._source_domain(item.get("source_url")),
                            "source_tier_label": self._source_tier_label(item),
                            "confidence": item.get("confidence"),
                        }
                        for index, item in enumerate(support)
                    ],
                }
            )
        return chains

    def _section_support_lines(self, evidence: List[Dict[str, Any]], limit: int = 2) -> List[str]:
        if not evidence:
            return []
        lines = ["判断依据："]
        ranked = sorted(
            evidence,
            key=lambda item: (
                self._safe_float(item.get("confidence"), 0),
                self._safe_float(item.get("authority_score"), 0),
                self._safe_float(item.get("freshness_score"), 0),
            ),
            reverse=True,
        )
        for item in ranked[:limit]:
            domain = self._source_domain(item.get("source_url")) or "未知来源"
            citation = self._citation_label(item)
            tier_label = self._source_tier_label(item)
            lines.append(
                f"- {citation} {item.get('title') or domain}（{domain} / {tier_label} / {self._source_type_label(item.get('source_type'))}）：{self._short_text(item.get('summary') or item.get('extracted_fact'), 140)}"
            )
        return lines

    def _unique_domain_count(self, evidence: List[Dict[str, Any]]) -> int:
        return len({domain for domain in (self._source_domain(item.get("source_url")) for item in evidence) if domain})

    def _source_type_mix(self, evidence: List[Dict[str, Any]]) -> Dict[str, int]:
        mix: Dict[str, int] = defaultdict(int)
        for item in evidence:
            source_type = str(item.get("source_type") or "unknown").strip() or "unknown"
            mix[source_type] += 1
        return dict(sorted(mix.items(), key=lambda pair: (-pair[1], pair[0])))

    def _build_conflict_dossier(self, claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        conflicts: List[Dict[str, Any]] = []
        for claim in claims:
            status = str(claim.get("status") or "unknown").strip()
            confidence = self._safe_float(claim.get("confidence"), 0.0)
            caveats = self._dedupe_text([str(item) for item in claim.get("caveats", []) if str(item).strip()], limit=3)
            evidence_count = len(claim.get("evidence_ids") or [])
            counter_evidence_count = len(claim.get("counter_evidence_ids") or [])

            issue_type = ""
            issue_summary = ""
            recommended_validation = ""
            severity = 0

            if status == "disputed":
                issue_type = "conflict"
                issue_summary = "存在互相冲突的证据或解读，当前不适合直接视作确定结论。"
                recommended_validation = "回到原始来源核对口径，并补充一类不同来源的交叉验证证据。"
                severity = 4
            elif status in {"inferred", "directional"} and confidence < 0.7:
                issue_type = "weak_signal"
                issue_summary = "当前更像方向性推断，直接证据密度仍偏低。"
                recommended_validation = "补充官方、一手或更高权威来源，再决定是否升级为稳定判断。"
                severity = 3
            elif caveats:
                issue_type = "boundary"
                issue_summary = "该判断附带明显适用边界或样本限制，使用时需要保留前提。"
                recommended_validation = "优先验证 caveat 涉及的假设，避免把局部观察误当成全局结论。"
                severity = 2
            elif confidence < 0.6 or evidence_count == 0:
                issue_type = "coverage_gap"
                issue_summary = "当前证据覆盖不足，结论稳固性偏弱。"
                recommended_validation = "先补足直接相关来源，再进入动作设计或资源承诺。"
                severity = 1

            if not issue_type:
                continue

            conflicts.append(
                {
                    "claim_text": self._claim_text(claim),
                    "market_step": claim.get("market_step"),
                    "status": status,
                    "confidence": confidence,
                    "evidence_count": evidence_count,
                    "counter_evidence_count": counter_evidence_count,
                    "caveats": caveats,
                    "issue_type": issue_type,
                    "issue_summary": issue_summary,
                    "recommended_validation": recommended_validation,
                    "severity": severity,
                }
            )

        conflicts.sort(
            key=lambda item: (
                int(item.get("severity", 0)),
                self._safe_float(item.get("confidence"), 0.0) * -1,
            ),
            reverse=True,
        )
        return conflicts[:6]

    def _build_decision_snapshot(
        self,
        claims: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        dossier: Dict[str, Any],
        conflict_dossier: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        readiness = self._decision_readiness(claims, evidence)
        high_confidence_claims = sum(
            1
            for claim in claims
            if str(claim.get("status") or "").strip() in {"verified", "confirmed"}
            and self._safe_float(claim.get("confidence"), 0.0) >= 0.75
        )
        directional_claims = sum(1 for claim in claims if str(claim.get("status") or "").strip() == "directional")
        inferred_claims = sum(1 for claim in claims if str(claim.get("status") or "").strip() in {"inferred", "directional"})
        disputed_claims = sum(1 for claim in claims if str(claim.get("status") or "").strip() == "disputed")
        open_questions = len(dossier.get("open_questions") or [])
        unique_domains = self._unique_domain_count(evidence)
        next_step_claims = sorted(
            claims,
            key=lambda item: (
                self._safe_float(item.get("actionability_score"), 0.0),
                self._safe_float(item.get("confidence"), 0.0),
            ),
            reverse=True,
        )
        next_step = self._claim_text(next_step_claims[0]) if next_step_claims else "优先补足直接证据，再决定下一步动作。"

        if readiness == "较高":
            readiness_reason = (
                f"已有 {high_confidence_claims} 条高置信判断、{len(evidence)} 条来源线索和 {unique_domains} 个独立域名支撑，"
                "可用于方向讨论和优先级排序。"
            )
        elif readiness == "中等":
            readiness_reason = (
                f"已形成可讨论的判断骨架，但仍有 {open_questions} 个待验证问题和 {len(conflict_dossier)} 个边界项，"
                "适合作为评审输入，不宜直接视为定案。"
            )
        else:
            readiness_reason = (
                f"当前高置信判断偏少，且仍有 {open_questions} 个关键问题待验证，"
                "建议先补足核心证据后再推进重决策。"
            )

        return {
            "readiness": readiness,
            "readiness_reason": readiness_reason,
            "high_confidence_claims": high_confidence_claims,
            "directional_claims": directional_claims,
            "inferred_claims": inferred_claims,
            "disputed_claims": disputed_claims,
            "open_questions": open_questions,
            "unique_domains": unique_domains,
            "next_step": next_step,
        }

    def _build_executive_memo_markdown(
        self,
        request: Dict[str, Any],
        report_markdown: str,
        decision_snapshot: Dict[str, Any],
        conflict_dossier: List[Dict[str, Any]],
        stage: str,
    ) -> str:
        title = str(request.get("topic") or "研究主题").strip()
        summary_block = self._extract_section_block(report_markdown, "核心结论摘要")
        decision_block = self._extract_section_block(report_markdown, "决策快照")
        actions_block = self._extract_section_block(report_markdown, "建议动作")
        conflict_block = self._extract_section_block(report_markdown, "证据冲突与使用边界")

        lines = [
            f"# {title} 管理摘要（{self._stage_label(request, stage)}）",
            "",
            (
                f"> 面向评审会快速阅读的摘要视图。当前决策成熟度为“{decision_snapshot.get('readiness', '待判断')}”，"
                f"建议优先动作：{decision_snapshot.get('next_step', '待补充')}。"
            ),
            "",
        ]

        if summary_block:
            lines.extend([summary_block, ""])
        if decision_block:
            lines.extend([decision_block, ""])
        else:
            lines.extend(
                [
                    "## 决策快照",
                    "",
                    self._render_table(
                        ["维度", "当前状态"],
                        [
                            ["决策成熟度", decision_snapshot.get("readiness")],
                            ["成熟度说明", decision_snapshot.get("readiness_reason")],
                            ["高置信判断", decision_snapshot.get("high_confidence_claims")],
                            ["推断判断", decision_snapshot.get("inferred_claims")],
                            ["争议判断", decision_snapshot.get("disputed_claims")],
                            ["待验证问题", decision_snapshot.get("open_questions")],
                            ["来源域名数", decision_snapshot.get("unique_domains")],
                            ["建议下一步", decision_snapshot.get("next_step")],
                        ],
                    ),
                    "",
                ]
            )

        if actions_block:
            lines.extend([actions_block, ""])
        if conflict_block:
            lines.extend([conflict_block, ""])
        elif conflict_dossier:
            lines.extend(
                [
                    "## 证据冲突与使用边界",
                    "",
                    self._render_table(
                        ["判断", "当前状态", "为什么要谨慎", "建议处理"],
                        [
                            [
                                item.get("claim_text"),
                                f"{self._status_label(item.get('status'))} / {self._confidence_label(item.get('confidence'))}",
                                item.get("issue_summary"),
                                item.get("recommended_validation"),
                            ]
                            for item in conflict_dossier[:4]
                        ],
                    ),
                    "",
                ]
            )

        return self._normalize_markdown("\n".join(lines))

    def _build_board_brief_markdown(
        self,
        request: Dict[str, Any],
        claims: List[Dict[str, Any]],
        dossier: Dict[str, Any],
        decision_snapshot: Dict[str, Any],
        conflict_dossier: List[Dict[str, Any]],
        stage: str,
    ) -> str:
        title = str(request.get("topic") or "研究主题").strip()
        top_claims = self._top_claims(claims, limit=4)
        open_questions = dossier.get("open_questions") or []
        lines = [
            f"# {title} 决策简报（{self._stage_label(request, stage)}）",
            "",
            f"> 一页式评审视图。当前建议把这份研究用于“{decision_snapshot.get('readiness', '待判断')}”级别的方向讨论，优先动作是：{decision_snapshot.get('next_step', '待补充')}。",
            "",
            "## 一句话判断",
            "",
        ]
        if top_claims:
            for claim in top_claims[:3]:
                lines.append(
                    f"- 结论：{self._claim_text(claim)}"
                    f"；状态：{self._status_label(claim.get('status'))}"
                    f"；置信度：{self._confidence_label(claim.get('confidence'))}"
                )
        else:
            lines.append("- 当前仍缺少足够高置信判断，建议先补足核心证据。")

        lines.extend(
            [
                "",
                "## 决策框架",
                "",
                self._render_table(
                    ["问题", "当前回答"],
                    [
                        ["这份报告现在适合做什么", decision_snapshot.get("readiness_reason")],
                        ["最应该先做什么", decision_snapshot.get("next_step")],
                        ["高置信判断数", decision_snapshot.get("high_confidence_claims")],
                        ["争议 / 推断", f"{decision_snapshot.get('disputed_claims', 0)} / {decision_snapshot.get('inferred_claims', 0)}"],
                        ["待验证问题", decision_snapshot.get("open_questions")],
                    ],
                ),
                "",
                "## 为什么重要",
                "",
            ]
        )
        if top_claims:
            for claim in top_claims[:3]:
                lines.append(f"- {self._market_step_implication(str(claim.get('market_step') or ''))}")
        else:
            lines.append("- 目前更适合作为研究方向盘，而不是直接进入资源承诺。")

        lines.extend(["", "## 立刻推进的动作", ""])
        action_claims = sorted(
            claims,
            key=lambda item: (
                self._safe_float(item.get("actionability_score"), 0.0),
                self._safe_float(item.get("confidence"), 0.0),
            ),
            reverse=True,
        )[:4]
        if action_claims:
            lines.append(
                self._render_table(
                    ["优先级", "动作", "为什么现在做", "证据状态"],
                    [
                        [
                            self._priority_label(claim.get("priority"), claim.get("actionability_score")),
                            self._claim_text(claim),
                            self._market_step_implication(str(claim.get("market_step") or "")),
                            f"{self._status_label(claim.get('status'))} / {self._confidence_label(claim.get('confidence'))}",
                        ]
                        for claim in action_claims
                    ],
                )
            )
        else:
            lines.append("当前没有足够稳定的动作建议，优先任务仍是补证。")

        lines.extend(["", "## 使用边界", ""])
        if conflict_dossier:
            lines.append(
                self._render_table(
                    ["需要谨慎的点", "原因", "建议处理"],
                    [
                        [
                            item.get("claim_text"),
                            "; ".join(item.get("caveats") or []) or item.get("issue_summary"),
                            item.get("recommended_validation"),
                        ]
                        for item in conflict_dossier[:4]
                    ],
                )
            )
        elif open_questions:
            for question in open_questions[:4]:
                lines.append(f"- 待验证：{question}")
        else:
            lines.append("- 当前没有显式结构化冲突项，但仍建议结合正文中的证据边界使用。")

        return self._normalize_markdown("\n".join(lines))

    def _build_conflict_summary_markdown(
        self,
        request: Dict[str, Any],
        conflict_dossier: List[Dict[str, Any]],
        decision_snapshot: Dict[str, Any],
        dossier: Dict[str, Any],
        stage: str,
    ) -> str:
        title = str(request.get("topic") or "研究主题").strip()
        lines = [
            f"# {title} 冲突与验证边界（{self._stage_label(request, stage)}）",
            "",
            (
                f"> 该视图聚焦争议项、弱信号和使用边界。当前共有 {len(conflict_dossier)} 个需要在决策时显式保留的风险点，"
                f"另有 {decision_snapshot.get('open_questions', 0)} 个待验证问题。"
            ),
            "",
        ]

        if conflict_dossier:
            lines.extend(
                [
                    "## 证据冲突与使用边界",
                    "",
                    self._render_table(
                        ["判断", "阶段", "当前状态", "边界 / 风险", "建议验证动作"],
                        [
                            [
                                item.get("claim_text"),
                                self._market_step_label(item.get("market_step")),
                                f"{self._status_label(item.get('status'))} / {self._confidence_label(item.get('confidence'))}",
                                "; ".join(item.get("caveats") or []) or item.get("issue_summary"),
                                item.get("recommended_validation"),
                            ]
                            for item in conflict_dossier
                        ],
                    ),
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "## 证据冲突与使用边界",
                    "",
                    "当前没有显式的结构化冲突项，但这不代表研究已经完全闭合，仍应结合待验证问题判断使用边界。",
                    "",
                ]
            )

        open_questions = dossier.get("open_questions") or []
        lines.append("## 后续验证清单")
        lines.append("")
        if open_questions:
            for question in open_questions[:8]:
                lines.append(f"- {question}")
        else:
            lines.append("当前没有显式待验证问题，可继续围绕付费意愿、渠道效率和竞品差异补充验证。")

        return self._normalize_markdown("\n".join(lines))

    def _build_appendix_markdown(
        self,
        request: Dict[str, Any],
        dossier: Dict[str, Any],
        evidence: List[Dict[str, Any]],
        competitor_names: List[str],
        feedback_notes: List[Dict[str, Any]],
        stage: str,
    ) -> str:
        title = str(request.get("topic") or "研究主题").strip()
        geo_scope = "、".join(request.get("geo_scope") or ["未指定"])
        source_footprint = dossier.get("source_footprint") or {}
        source_tier_mix = source_footprint.get("source_tier_mix") or {}
        source_tier_mix_text = " / ".join(f"{key}:{value}" for key, value in list(source_tier_mix.items())[:4]) or "待补充"
        lines = [
            f"# {title} 附录（{self._stage_label(request, stage)}）",
            "",
            "> 附录用于补充方法、覆盖范围、关键证据与版本变化记录，方便回溯研究过程。",
            "",
            "## 方法与覆盖",
            "",
            self._render_table(
                ["维度", "内容"],
                [
                    ["研究主题", request.get("topic")],
                    ["研究模式", research_mode_label(str(request.get("research_mode") or ""))],
                    ["深度预设", depth_preset_label(str(request.get("depth_preset") or ""))],
                    ["地域范围", geo_scope],
                    ["结构化判断数", dossier.get("counts", {}).get("claim_count")],
                    ["来源数量", dossier.get("counts", {}).get("evidence_count")],
                    ["竞品样本数", len(competitor_names)],
                    ["来源可信度分层", source_tier_mix_text],
                    ["PM 反馈数", len(feedback_notes)],
                    ["报告阶段", self._stage_label(request, stage)],
                ],
            ),
            "",
            "## 研究步骤覆盖",
            "",
        ]

        market_step_rows = []
        for item in dossier.get("market_steps", [])[:10]:
            claims = item.get("claims") or []
            top_evidence = item.get("evidence") or []
            market_step_rows.append(
                [
                    self._market_step_label(item.get("market_step")),
                    len(claims),
                    len(top_evidence),
                    (claims[0].get("claim_text") if claims else "") or (top_evidence[0].get("summary") if top_evidence else "待补充"),
                ]
            )
        if market_step_rows:
            lines.append(self._render_table(["研究步骤", "结构化判断", "高优先级证据", "当前最强线索"], market_step_rows))
        else:
            lines.append("当前没有可展示的研究步骤覆盖情况。")
        lines.extend(["", "## 证据附录", ""])

        top_evidence = dossier.get("top_evidence") or []
        if top_evidence:
            lines.append(
                self._render_table(
                    ["引用", "来源", "层级", "类型", "研究步骤", "关键提炼", "链接"],
                    [
                        [
                            item.get("citation_label"),
                            item.get("title"),
                            item.get("source_tier_label"),
                            self._source_type_label(item.get("source_type")),
                            self._market_step_label(item.get("market_step")),
                            item.get("summary"),
                            item.get("source_url"),
                        ]
                        for item in top_evidence[:8]
                    ],
                )
            )
        else:
            lines.append("当前没有可展示的核心证据。")

        lines.extend(["", "## 竞品观察名单", ""])
        if dossier.get("competitors"):
            lines.append(
                self._render_table(
                    ["竞品", "角色", "当前定位", "定价线索", "主要缺口"],
                    [
                        [
                            item.get("name"),
                            "直接竞争" if item.get("category") == "direct" else "替代/间接",
                            item.get("positioning"),
                            item.get("pricing"),
                            item.get("coverage_gap"),
                        ]
                        for item in dossier.get("competitors", [])[:8]
                    ],
                )
            )
        else:
            lines.append("当前尚未形成稳定的竞品样本池。")

        lines.extend(["", "## 反馈记录", ""])
        if feedback_notes:
            lines.append(
                self._render_table(
                    ["时间", "PM 反馈", "当前回应", "处理方式"],
                    [
                        [
                            item.get("created_at"),
                            item.get("feedback") or item.get("question") or "补充问题",
                            item.get("response") or "已纳入后续成文",
                            item.get("action") or "已同步到相关章节",
                        ]
                        for item in feedback_notes[-8:]
                    ],
                )
            )
        else:
            lines.append("当前没有新增反馈记录。")

        return self._normalize_markdown("\n".join(lines))

    def _compose_report_asset(
        self,
        markdown: str,
        evidence_count: int,
        stage: str,
        previous_report: Optional[Dict[str, Any]] = None,
        feedback_notes: Optional[List[Dict[str, Any]]] = None,
        section_count: Optional[int] = None,
        board_brief_markdown: Optional[str] = None,
        executive_memo_markdown: Optional[str] = None,
        appendix_markdown: Optional[str] = None,
        conflict_summary_markdown: Optional[str] = None,
        decision_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        previous_report = previous_report or {}
        feedback_notes = feedback_notes if feedback_notes is not None else list(previous_report.get("feedback_notes", []))
        now = iso_now()
        is_revision = bool(previous_report.get("markdown"))
        computed_section_count = sum(1 for line in str(markdown or "").splitlines() if line.startswith("## "))
        return {
            "markdown": markdown,
            "board_brief_markdown": board_brief_markdown or previous_report.get("board_brief_markdown") or "",
            "executive_memo_markdown": executive_memo_markdown or previous_report.get("executive_memo_markdown") or "",
            "appendix_markdown": appendix_markdown or previous_report.get("appendix_markdown") or "",
            "conflict_summary_markdown": conflict_summary_markdown or previous_report.get("conflict_summary_markdown") or "",
            "decision_snapshot": decision_snapshot or previous_report.get("decision_snapshot") or {},
            "generated_at": previous_report.get("generated_at") or now,
            "updated_at": now,
            "section_count": computed_section_count or (section_count if section_count is not None else previous_report.get("section_count", 0)),
            "evidence_count": evidence_count,
            "stage": stage,
            "revision_count": int(previous_report.get("revision_count", 0)) + (1 if is_revision else 0),
            "feedback_count": len(feedback_notes),
            "feedback_notes": feedback_notes,
            "draft_markdown": previous_report.get("draft_markdown") or markdown,
            "long_report_ready": stage == "final",
        }

    def extract_competitors(self, request: Dict[str, Any], evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        topic = str(request.get("topic") or "").strip()
        max_competitors = max(1, min(8, int(request.get("max_competitors", 6) or 6)))
        normalized_evidence = self.backfill_evidence_competitors(request, evidence)
        candidate_names = [
            name
            for name in self._candidate_competitor_names(normalized_evidence, limit=max_competitors + 2, request=request)
            if str(name or "").strip() and str(name or "").strip() != topic
        ]
        normalized_evidence = self.backfill_evidence_competitors(request, normalized_evidence, competitor_names=candidate_names)
        fallback_competitors = self._build_competitor_profiles(normalized_evidence, competitor_names=candidate_names, limit=max_competitors)
        if not self.llm_client or not self.llm_client.is_enabled():
            return fallback_competitors

        llm_sample = []
        for item in self._top_evidence(
            [entry for entry in normalized_evidence if str(entry.get("market_step") or "") in {"competitor-analysis", "business-and-channels", "experience-teardown"}]
            or normalized_evidence,
            limit=24,
        ):
            llm_sample.append(
                {
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "market_step": item.get("market_step"),
                    "competitor_name": item.get("competitor_name"),
                    "source_type": item.get("source_type"),
                }
            )
        sample = [
            item for item in llm_sample[:20]
        ]
        try:
            system_prompt = load_prompt_template("synthesizer")
            result = self.llm_client.complete_json(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "请从以下 evidence 中抽取竞品候选，返回 JSON 对象 {\"competitors\": [...]}。"
                            "每个 competitor 必须包含 name/category/positioning/pricing。"
                            "不要返回主题本身，不要编造不存在的竞品。"
                            f"\ntopic={request['topic']}"
                            f"\nevidence_sample={json.dumps(sample, ensure_ascii=False)}"
                            "\n只返回 JSON。"
                        ),
                    },
                ],
                temperature=0.15,
                max_tokens=900,
            )
            competitors = result.get("competitors", []) if isinstance(result, dict) else []
            fallback_lookup = {item.get("name"): item for item in fallback_competitors if item.get("name")}
            sanitized = []
            seen = set()
            for item in competitors:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name or name == topic or name in seen:
                    continue
                seen.add(name)
                base = fallback_lookup.get(name, {"name": name})
                llm_positioning = str(item.get("positioning") or "").strip()
                llm_pricing = str(item.get("pricing") or "").strip()
                sanitized.append(
                    {
                        "name": name,
                        "category": item.get("category") if item.get("category") in {"direct", "indirect"} else base.get("category", "direct"),
                        "positioning": llm_positioning if llm_positioning and not self._looks_like_placeholder(llm_positioning) else base.get("positioning", "当前已识别该竞品，但定位描述仍需补充。"),
                        "pricing": llm_pricing if llm_pricing and not self._looks_like_placeholder(llm_pricing) else base.get("pricing", "未见明确公开定价，需补充价格页或渠道报价。"),
                        "differentiation": base.get("differentiation", "当前主要差异仍需补充更多对比证据。"),
                        "coverage_gap": base.get("coverage_gap", "下一轮可补充功能矩阵、价格与渠道差异。"),
                        "evidence_count": base.get("evidence_count", 0),
                        "source_count": base.get("source_count", 0),
                        "source_domains": base.get("source_domains", []),
                        "source_types": base.get("source_types", []),
                        "key_sources": base.get("key_sources", []),
                        "highlights": base.get("highlights", []),
                    }
                )
            if sanitized:
                merged = list(sanitized)
                for item in fallback_competitors:
                    if item.get("name") and item.get("name") not in {entry.get("name") for entry in merged}:
                        merged.append(item)
                return merged[:max_competitors]
        except Exception:
            return fallback_competitors
        return fallback_competitors

    def _build_fallback_report(
        self,
        request: Dict[str, Any],
        claims: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        competitor_names: List[str],
        stage: str = "draft",
        feedback_notes: Optional[List[Dict[str, Any]]] = None,
        previous_report: Optional[Dict[str, Any]] = None,
        dossier: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        claims_by_step = self._group_by_market_step(claims)
        evidence_by_step = self._group_by_market_step(evidence)
        top_claims = self._top_claims(claims, limit=4)
        top_evidence = self._top_evidence(evidence, limit=6)
        feedback_notes = feedback_notes or []
        dossier = dossier or self._build_report_dossier(
            request=request,
            claims=claims,
            evidence=evidence,
            competitor_names=competitor_names,
            feedback_notes=feedback_notes,
            current_report=previous_report,
            stage=stage,
        )
        conflict_dossier = self._build_conflict_dossier(claims)
        decision_snapshot = self._build_decision_snapshot(claims, evidence, dossier, conflict_dossier)
        dossier["decision_snapshot"] = decision_snapshot
        dossier["conflicts"] = conflict_dossier
        readiness = str(decision_snapshot.get("readiness") or self._decision_readiness(claims, evidence))
        geo_scope = "、".join(request.get("geo_scope") or ["未指定"])
        workflow_label = str(request.get("workflow_label") or workflow_command_label(str(request.get("workflow_command") or "")) or "全景深度扫描").strip()
        project_memory = self._short_text(request.get("project_memory"), limit=160) if request.get("project_memory") else "未提供"
        source_footprint = dossier.get("source_footprint") or {}
        source_type_mix = source_footprint.get("source_type_mix") or {}
        source_tier_mix = source_footprint.get("source_tier_mix") or {}
        source_mix_text = " / ".join(f"{self._source_type_label(key)}:{value}" for key, value in list(source_type_mix.items())[:4]) or "待补充"
        source_tier_mix_text = " / ".join(f"{key}:{value}" for key, value in list(source_tier_mix.items())[:4]) or "待补充"
        section_sufficiency = dossier.get("section_sufficiency") or {}
        insufficient_sections: List[Dict[str, Any]] = []
        sections = [
            self._report_title(request, stage),
            "",
            (
                f"> 报告定位：面向 PM / 管理层的{self._stage_label(request, stage)}研究交付件。"
                f"当前基于 {len(evidence)} 个来源、{len(claims)} 条结构化判断生成，"
                f"可直接用于评审会讨论，但成熟度为“{readiness}”。"
            ),
            "",
            "## 核心结论摘要",
            "",
        ]
        if top_claims:
            sections.append(
                f"本轮研究已沉淀出 {len(claims)} 条结构化判断。当前最值得进入 PM 讨论的结论，"
                f"集中在用户需求、竞争格局与下一步动作三个层面。"
            )
            sections.append("")
            for paragraph in self._section_argument_paragraphs(
                dossier,
                ["user-research", "competitor-analysis", "recommendations", "opportunities-and-risks"],
                limit=2,
            ):
                sections.append(paragraph)
                sections.append("")
            for claim in top_claims:
                sections.append(
                    f"- {self._claim_text(claim)}；状态：{self._status_label(claim.get('status'))}；"
                    f"置信度：{self._confidence_label(claim.get('confidence'))}；"
                    f"PM 含义：{self._market_step_implication(str(claim.get('market_step') or ''))}"
                    f"{self._claim_citation_note(claim, evidence)}"
                )
            if dossier.get("open_questions"):
                sections.append(
                    f"- 当前仍有 {len(dossier['open_questions'])} 个关键待验证问题，"
                    f"说明本报告更适合支持方向判断和优先级排序，而非直接视作定案。"
                )
            sections.append(
                f"- 证据足迹：{source_footprint.get('unique_domains', 0)} 个独立域名，来源结构以 {source_mix_text} 为主。"
            )
        else:
            sections.append("当前已形成报告框架，但高置信度判断仍偏少，建议先补充直接相关证据，再进入方案决策。")
        sections.extend(
            [
                "",
                "## 决策快照",
                "",
                self._render_table(
                    ["维度", "当前状态"],
                    [
                        ["决策成熟度", decision_snapshot.get("readiness")],
                        ["成熟度说明", decision_snapshot.get("readiness_reason")],
                        ["适合支持的决策", "方向判断、优先级排序、补研规划" if readiness != "偏低" else "补研规划、假设收敛"],
                        ["暂不建议直接用于", "资源承诺 / 详细预算 / 大规模路线图锁定" if readiness != "较高" else "仍需结合执行约束复核"],
                        ["高置信判断", decision_snapshot.get("high_confidence_claims")],
                        ["推断判断", decision_snapshot.get("inferred_claims")],
                        ["争议判断", decision_snapshot.get("disputed_claims")],
                        ["待验证问题", decision_snapshot.get("open_questions")],
                        ["来源域名数", decision_snapshot.get("unique_domains")],
                        ["建议下一步", decision_snapshot.get("next_step")],
                    ],
                ),
                "",
                "当前解读：这个快照用于帮助 PM / 管理层判断“现在可以拿这份报告做什么决策、还不能跳过哪些验证”。",
                "",
                "## 研究范围与方法",
                "",
                self._render_table(
                    ["维度", "内容"],
                    [
                        ["研究主题", request.get("topic")],
                        ["行业模板", industry_template_label(str(request.get("industry_template") or ""))],
                        ["研究模式", research_mode_label(str(request.get("research_mode") or ""))],
                        ["深度预设", depth_preset_label(str(request.get("depth_preset") or ""))],
                        ["研究指令", workflow_label],
                        ["地域范围", geo_scope],
                        ["项目记忆", project_memory],
                        ["报告阶段", self._stage_label(request, stage)],
                        ["来源数量", len(evidence)],
                        ["结构化判断数", len(claims)],
                        ["竞品数量", len(competitor_names)],
                        ["独立来源域名", source_footprint.get("unique_domains")],
                        ["来源结构", source_mix_text],
                        ["来源可信度分层", source_tier_mix_text],
                        ["关键待验证问题", len(dossier.get("open_questions", []))],
                        ["当前决策成熟度", readiness],
                    ],
                ),
                "",
                "当前解读：上表用于界定这份报告的使用边界。若后续要进入立项、路线图或 GTM 决策，"
                "建议优先核查证据密度和待验证问题是否仍然偏多。",
                "",
            ]
        )

        for section in REPORT_SECTIONS[2:]:
            related_steps = REPORT_SECTION_STEP_MAP.get(section, [])
            section_claims: List[Dict[str, Any]] = []
            section_evidence: List[Dict[str, Any]] = []
            for step in related_steps:
                section_claims.extend(claims_by_step.get(step, []))
                section_evidence.extend(evidence_by_step.get(step, []))
            sufficiency = section_sufficiency.get(section) or self._section_evidence_sufficiency(section, evidence)
            should_force_render = section in {"建议动作", "待验证问题", "竞争格局"} or (
                section == "重点竞品拆解" and bool(dossier.get("competitors"))
            )
            if not bool(sufficiency.get("sufficient", True)) and not should_force_render:
                insufficient_sections.append(sufficiency)
                sections.append(f"## {section}")
                sections.append("")
                sections.append(
                    "当前与本章节直接相关的证据仍不足，暂不展开完整分析；建议先补足至少 3 条证据与 2 个独立域名后再完善本节。"
                )
                if section_evidence:
                    sections.append("")
                    sections.extend(self._section_support_lines(section_evidence, limit=1))
                sections.append("")
                continue
            if section == "竞争格局":
                sections.append("## 竞争格局")
                sections.append("")
                if dossier.get("competitors"):
                    sections.append(
                        f"当前已形成 {len(dossier['competitors'])} 个可进入对标讨论的竞品样本。"
                        "以下对比优先回答“它们分别卡位在哪里、价格线索如何、差异点是否已被证据支撑”。"
                    )
                    sections.append("")
                    sections.append(
                        self._render_table(
                            ["竞品", "角色", "当前定位", "定价线索", "核心差异", "证据足迹"],
                            [
                                [
                                    item.get("name"),
                                    "直接竞争" if item.get("category") == "direct" else "替代/间接",
                                    item.get("positioning"),
                                    item.get("pricing"),
                                    item.get("differentiation"),
                                    f"{item.get('evidence_count', 0)} 条证据 / {int(item.get('source_count', 0) or 0)} 个域名",
                                ]
                                for item in dossier["competitors"][:6]
                            ],
                        )
                    )
                    competitor_evidence = [item for item in evidence if item.get("market_step") == "competitor-analysis"]
                    if competitor_evidence:
                        sections.append("")
                        sections.extend(self._section_support_lines(competitor_evidence, limit=2))
                elif competitor_names:
                    sections.append(f"已识别竞品名单：{'、'.join(competitor_names)}。当前仍需补足统一口径的功能、价格与渠道对比。")
                else:
                    sections.append("当前尚未形成稳定的竞品样本池，本章节建议作为待补充模块处理。")
                sections.append("")
                for claim in claims_by_step.get("competitor-analysis", [])[:3]:
                    sections.append(
                        f"- {self._claim_text(claim)}；状态：{self._status_label(claim.get('status'))}；"
                        f"置信度：{self._confidence_label(claim.get('confidence'))}"
                    )
                if dossier.get("competitors"):
                    sections.append(
                        "- 当前优先补齐的缺口主要集中在统一价格口径、官方来源交叉验证，以及用户侧体验反馈三类。"
                    )
                sections.append("")
                continue

            if section == "重点竞品拆解":
                sections.append("## 重点竞品拆解")
                sections.append("")
                deep_dive_rows = []
                for item in dossier.get("competitors", [])[:4]:
                    deep_dive_rows.append(
                        [
                            item.get("name"),
                            item.get("positioning"),
                            item.get("differentiation"),
                            item.get("coverage_gap"),
                        ]
                    )
                if deep_dive_rows:
                    sections.append("以下对象适合作为下一轮重点拆解样本，优先补齐功能、价格、渠道与真实体验四个维度。")
                    sections.append("")
                    sections.append(self._render_table(["竞品", "当前定位", "最值得盯的差异", "仍需补的证据"], deep_dive_rows))
                    sections.append("")
                    for item in dossier.get("competitors", [])[:4]:
                        sections.append(f"### {item.get('name')}")
                        sections.append("")
                        sections.append(f"- 角色：{'直接竞争' if item.get('category') == 'direct' else '替代/间接'}")
                        sections.append(f"- 当前定位：{item.get('positioning')}")
                        sections.append(f"- 定价线索：{item.get('pricing')}")
                        sections.append(f"- 当前差异：{item.get('differentiation')}")
                        sections.append(f"- 仍需补证：{item.get('coverage_gap')}")
                        key_sources = [source for source in (item.get("key_sources") or []) if source]
                        if key_sources:
                            sections.append(f"- 关键来源：{'；'.join(key_sources[:2])}")
                        top_highlights = item.get("highlights") or []
                        for highlight in top_highlights[:2]:
                            sections.append(
                                f"- {highlight.get('citation_label') or ''} {highlight.get('summary') or highlight.get('title') or '已有相关证据'}"
                            )
                        sections.append("")
                else:
                    sections.append("暂未形成可支撑深挖的竞品样本，建议先完成竞品识别与证据补齐。")
                sections.append("")
                continue

            if section == "机会地图":
                sections.append("## 机会地图")
                sections.append("")
                opportunity_claims = sorted(
                    claims_by_step.get("opportunities-and-risks", []) + claims_by_step.get("recommendations", []),
                    key=lambda item: (self._safe_float(item.get("actionability_score")), self._safe_float(item.get("confidence"))),
                    reverse=True,
                )[:4]
                if opportunity_claims:
                    sections.append("以下机会判断应作为下一轮产品策略讨论的输入，而不是未经验证的最终结论。")
                    sections.append("")
                    sections.append(
                        self._render_table(
                            ["机会方向", "当前判断", "证据强度", "PM 含义"],
                            [
                                [
                                    self._claim_text(claim),
                                    self._status_label(claim.get("status")),
                                    self._confidence_label(claim.get("confidence")),
                                    self._market_step_implication(str(claim.get("market_step") or "")),
                                ]
                                for claim in opportunity_claims
                            ],
                        )
                    )
                    supporting_evidence = [
                        item
                        for item in evidence
                        if str(item.get("market_step") or "") in {"opportunities-and-risks", "recommendations"}
                    ]
                    if supporting_evidence:
                        sections.append("")
                        sections.extend(self._section_support_lines(supporting_evidence, limit=2))
                else:
                    sections.append("当前机会矩阵仍偏空，建议补齐市场、用户和竞品证据后再判断切入点。")
                sections.append("")
                continue

            if section == "风险与约束":
                sections.append("## 风险与约束")
                sections.append("")
                risk_rows = []
                for claim in claims[:6]:
                    caveat = "; ".join([str(item) for item in claim.get("caveats", [])[:2]]) or "暂无显式 caveat，建议结合证据密度继续核验。"
                    if claim.get("status") in {"disputed", "inferred", "directional"} or claim.get("caveats"):
                        risk_rows.append(
                            [
                                self._claim_text(claim),
                                f"{self._status_label(claim.get('status'))} / {self._confidence_label(claim.get('confidence'))}",
                                caveat,
                            ]
                        )
                if risk_rows:
                    sections.append("以下风险意味着当前报告应被用于决策讨论，而不是跳过验证直接落地。")
                    sections.append("")
                    sections.append(self._render_table(["风险点", "当前状态", "需要补充验证"], risk_rows[:5]))
                else:
                    sections.append("当前未识别出高显性的结构化风险，但证据覆盖度仍决定了报告可用边界。")
                sections.append("")
                continue

            if section == "建议动作":
                sections.append("## 建议动作")
                sections.append("")
                candidate_claims = sorted(
                    claims_by_step.get("recommendations", [])
                    + claims_by_step.get("opportunities-and-risks", [])
                    + claims_by_step.get("user-research", [])
                    + claims_by_step.get("competitor-analysis", []),
                    key=lambda item: (
                        self._safe_float(item.get("actionability_score")),
                        self._safe_float(item.get("confidence")),
                    ),
                    reverse=True,
                )[:5]
                if candidate_claims:
                    sections.append("建议动作按照“先验证、再扩张、最后优化”的思路排序，便于 PM 直接纳入下一轮工作计划。")
                    sections.append("")
                    sections.append(
                        self._render_table(
                            ["优先级", "建议动作", "为什么现在做", "证据状态", "主要风险"],
                            [
                                [
                                    self._priority_label(claim.get("priority"), claim.get("actionability_score")),
                                    self._claim_text(claim),
                                    self._market_step_implication(str(claim.get("market_step") or "")),
                                    f"{self._status_label(claim.get('status'))} / {self._confidence_label(claim.get('confidence'))}",
                                    "; ".join([str(item) for item in claim.get("caveats", [])[:2]]) or "需继续观察执行反馈",
                                ]
                                for claim in candidate_claims
                            ],
                        )
                    )
                    sections.append("")
                    sections.append("动作依据：这些建议优先来自高 actionability 的结构化判断，并由对应市场步骤中的高置信证据支撑。")
                else:
                    sections.append("当前证据尚不足以形成稳定的建议动作，优先任务应是补充直接相关研究来源。")
                sections.append("")
                continue

            if section == "待验证问题":
                sections.append("## 待验证问题")
                sections.append("")
                open_questions = dossier.get("open_questions") or []
                if open_questions:
                    sections.append("以下问题建议作为下一轮补研的明确输入，避免报告继续停留在泛化判断层。")
                    sections.append("")
                    for question in open_questions[:6]:
                        sections.append(f"- {question}")
                else:
                    sections.append("当前没有显式待验证问题，但建议继续补充一手访谈、竞品对标和转化路径验证。")
                if insufficient_sections:
                    sections.append("")
                    sections.append("以下章节当前仍不足以展开完整论证，建议直接作为下一轮补研清单：")
                    sections.append("")
                    sections.append(
                        self._render_table(
                            ["章节", "当前覆盖", "补证门槛"],
                            [
                                [
                                    item.get("section"),
                                    f"{int(item.get('evidence_count', 0) or 0)} 条证据 / {int(item.get('unique_domains', 0) or 0)} 个域名",
                                    "至少补到 3 条证据、2 个独立域名",
                                ]
                                for item in insufficient_sections
                            ],
                        )
                    )
                sections.append("")
                continue

            sections.append(f"## {section}")
            sections.append("")
            if section_claims:
                sections.append("本章节已有可讨论判断，建议把“结论本身”和“证据强度”分开看待。")
                sections.append("")
                for paragraph in self._section_argument_paragraphs(dossier, related_steps, limit=2):
                    sections.append(paragraph)
                    sections.append("")
                for claim in section_claims[:3]:
                    sections.append(
                        f"- {self._claim_text(claim)}；状态：{self._status_label(claim.get('status'))}；"
                        f"置信度：{self._confidence_label(claim.get('confidence'))}；"
                        f"PM 含义：{self._market_step_implication(str(claim.get('market_step') or ''))}"
                        f"{self._claim_citation_note(claim, evidence)}"
                    )
                    sections.append(f"  使用边界：{self._claim_boundary_text(claim)}")
                if section_evidence:
                    sections.append("")
                    sections.extend(self._section_support_lines(section_evidence, limit=2))
            elif section_evidence:
                sections.append("当前更多是证据线索，尚未收敛成稳定判断，但已经能帮助界定方向和后续验证优先级。")
                sections.append("")
                sections.extend(self._section_support_lines(section_evidence, limit=3))
            elif top_evidence and section in {"产品体验与关键流程", "用户声音与情绪反馈"}:
                sections.append("当前没有直接落到该章节的 claim，但仍可从高优先级来源中提炼观察。")
                sections.append("")
                sections.extend(self._section_support_lines(top_evidence[:2], limit=2))
            else:
                sections.append("当前与本章节直接相关的证据仍不足，建议作为待验证模块处理。")
            sections.append("")

        sections.append("## 证据冲突与使用边界")
        sections.append("")
        if conflict_dossier:
            sections.append("以下条目应在评审会中被显式提及，避免把弱信号或有争议判断误当成已定事实。")
            sections.append("")
            sections.append(
                self._render_table(
                    ["判断", "阶段", "当前状态", "为什么要谨慎", "建议验证动作"],
                    [
                        [
                            item.get("claim_text"),
                            self._market_step_label(item.get("market_step")),
                            f"{self._status_label(item.get('status'))} / {self._confidence_label(item.get('confidence'))}",
                            "; ".join(item.get("caveats") or []) or item.get("issue_summary"),
                            item.get("recommended_validation"),
                        ]
                        for item in conflict_dossier
                    ],
                )
            )
        else:
            sections.append("当前没有显式结构化冲突项，但仍建议结合待验证问题一并理解使用边界。")
        sections.append("")

        if feedback_notes:
            sections.append("## PM 反馈整合")
            sections.append("")
            sections.append("以下内容记录本轮 PM 反馈如何被吸收到报告结构中，便于后续复盘版本变化。")
            sections.append("")
            sections.append(
                self._render_table(
                    ["PM 反馈", "当前回应", "处理方式"],
                    [
                        [
                            item.get("feedback") or item.get("question") or "补充问题",
                            item.get("response") or "已纳入后续报告修订",
                            item.get("action") or "已同步进入相关章节",
                        ]
                        for item in feedback_notes[-4:]
                    ],
                )
            )
            sections.append("")
            sections.append(self._build_feedback_addendum(feedback_notes))
            sections.append("")

        sections.append("## 关键证据摘录")
        sections.append("")
        if top_evidence:
            sections.append("以下来源是当前报告最主要的事实支撑，适合在评审会中作为追溯依据。")
            sections.append("")
            sections.append(
                self._render_table(
                    ["引用", "来源", "层级", "类型", "关键提炼", "置信度"],
                    [
                        [
                            item.get("citation_label") or self._citation_label(item, index),
                            item.get("title"),
                            item.get("source_tier_label") or self._source_tier_label(item),
                            self._source_type_label(item.get("source_type")),
                            item.get("summary"),
                            self._confidence_label(item.get("confidence")),
                        ]
                        for index, item in enumerate(top_evidence)
                    ],
                )
            )
        else:
            sections.append("当前没有可用证据，建议先完成来源采集，再进入正式成文阶段。")

        markdown = "\n".join(sections).strip()
        board_brief_markdown = self._build_board_brief_markdown(
            request=request,
            claims=claims,
            dossier=dossier,
            decision_snapshot=decision_snapshot,
            conflict_dossier=conflict_dossier,
            stage=stage,
        )
        executive_memo_markdown = self._build_executive_memo_markdown(
            request=request,
            report_markdown=markdown,
            decision_snapshot=decision_snapshot,
            conflict_dossier=conflict_dossier,
            stage=stage,
        )
        conflict_summary_markdown = self._build_conflict_summary_markdown(
            request=request,
            conflict_dossier=conflict_dossier,
            decision_snapshot=decision_snapshot,
            dossier=dossier,
            stage=stage,
        )
        appendix_markdown = self._build_appendix_markdown(
            request=request,
            dossier=dossier,
            evidence=evidence,
            competitor_names=competitor_names,
            feedback_notes=feedback_notes,
            stage=stage,
        )
        return self._compose_report_asset(
            markdown=markdown,
            evidence_count=len(evidence),
            stage=stage,
            previous_report=previous_report,
            feedback_notes=feedback_notes,
            section_count=len(REPORT_SECTIONS) + 3 + (1 if feedback_notes else 0),
            board_brief_markdown=board_brief_markdown,
            executive_memo_markdown=executive_memo_markdown,
            appendix_markdown=appendix_markdown,
            conflict_summary_markdown=conflict_summary_markdown,
            decision_snapshot=decision_snapshot,
        )

    def build_report(
        self,
        request: Dict[str, Any],
        claims: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        competitor_names: List[str],
    ) -> Dict[str, Any]:
        dossier = self._build_report_dossier(
            request=request,
            claims=claims,
            evidence=evidence,
            competitor_names=competitor_names,
            stage="draft",
        )
        conflict_dossier = self._build_conflict_dossier(claims)
        decision_snapshot = self._build_decision_snapshot(claims, evidence, dossier, conflict_dossier)
        dossier["decision_snapshot"] = decision_snapshot
        dossier["conflicts"] = conflict_dossier
        fallback_report = self._build_fallback_report(request, claims, evidence, competitor_names, stage="draft", dossier=dossier)
        if not self.llm_client or not self.llm_client.is_enabled():
            return fallback_report

        try:
            system_prompt = load_prompt_template("synthesizer")
            content = self.llm_client.complete(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "你现在处于独立的报告成文上下文。前面的研究步骤已经结束，并被整理成结构化 dossier。"
                            "请只把 dossier 当作写作材料，重新写成一份 Markdown 市场研究报告初稿，面向 PM 负责人、产品负责人和管理层评审。"
                            "不要把 JSON 字段名、market_step、claim_id、evidence_id、数组结构或 dossier 术语直接搬进正文。"
                            "必须包含以下 Markdown 二级标题，并保持标题文本完全一致："
                            "核心结论摘要、决策快照、研究范围与方法、市场结构与趋势、目标用户与关键任务、竞争格局、重点竞品拆解、"
                            "定价、商业模式与渠道、产品体验与关键流程、用户声音与情绪反馈、机会地图、风险与约束、建议动作、待验证问题、"
                            "证据冲突与使用边界、关键证据摘录。"
                            "\n要求："
                            "\n1. 先写清晰的核心结论摘要，再逐节展开；摘要必须给出 3-5 条硬结论，并说明这些结论对 PM 决策意味着什么。"
                            "\n2. 决策快照必须明确说明当前决策成熟度、为什么是这个成熟度、哪些结论可用于讨论、哪些仍需验证。"
                            "\n3. 只能使用 dossier 里已有的事实、结论和反馈，不要编造新数字、新竞品、新份额或新定价。"
                            "\n4. 对证据不足处明确写“待验证 / 证据不足”，不要把方向性判断伪装成确定事实。"
                            "\n5. 竞争格局、建议动作、关键证据摘录、证据冲突与使用边界尽量用 Markdown 表格表达。"
                            "\n6. 建议动作必须写出优先级、建议动作、为什么现在做、证据状态和主要风险。"
                            "\n7. 证据冲突与使用边界必须点明冲突、弱信号和使用边界，不要弱化不确定性。"
                            "\n8. 如果 output_locale 是 zh-CN，请正文与标题都使用专业简体中文。"
                            "\n9. 文风要像正式市场研究报告或策略 memo，不要写成泛泛总结，不要出现 AI 自我描述。"
                            "\n10. 每个主要章节尽量写成：当前判断 -> 为什么重要 -> 最强证据/来源线索 -> 仍需保留的边界。"
                            "\n11. 研究范围与方法需要明确 source footprint，不要只列配置。"
                            "\n12. 不要逐条复述结构化素材，而是把它们综合重写成自然、连贯、可评审的中文报告。"
                            "\n13. 优先吸收 report_dossier.argument_chains，把结论、依据、PM 含义和边界写成完整分析，不要只写稀疏 bullet。"
                            "\n14. 对有足够材料的章节，正文至少写出一个完整分析段，不要只留一句判断。"
                            "\n15. 对核心判断执行严格的 [Sx] 引用纪律：只引用 dossier 中真实存在的 citation_label；没有对应引用时不要伪造。"
                            "\n16. 当来源层级明显不同，要让正文体现一手/高权威来源优先、社区或弱信号作为补充，而不是混为一谈。"
                            "\n17. 若 report_dossier.section_sufficiency[章节].sufficient=false，除竞争格局、建议动作、待验证问题外，不要强行展开成长段，可明确写证据不足。"
                            f"\nreport_dossier={json.dumps(dossier, ensure_ascii=False)}"
                        ),
                    },
                ],
                temperature=0.16,
                max_tokens=4200,
            )
            content = self._polish_generated_markdown(
                markdown=content,
                request=request,
                stage="draft",
                fallback_markdown=fallback_report["markdown"],
            )
            board_brief_markdown = self._build_board_brief_markdown(
                request=request,
                claims=claims,
                dossier=dossier,
                decision_snapshot=decision_snapshot,
                conflict_dossier=conflict_dossier,
                stage="draft",
            )
            executive_memo_markdown = self._build_executive_memo_markdown(
                request=request,
                report_markdown=content,
                decision_snapshot=decision_snapshot,
                conflict_dossier=conflict_dossier,
                stage="draft",
            )
            conflict_summary_markdown = self._build_conflict_summary_markdown(
                request=request,
                conflict_dossier=conflict_dossier,
                decision_snapshot=decision_snapshot,
                dossier=dossier,
                stage="draft",
            )
            appendix_markdown = self._build_appendix_markdown(
                request=request,
                dossier=dossier,
                evidence=evidence,
                competitor_names=competitor_names,
                feedback_notes=[],
                stage="draft",
            )
            return self._compose_report_asset(
                markdown=content,
                evidence_count=len(evidence),
                stage="draft",
                board_brief_markdown=board_brief_markdown,
                executive_memo_markdown=executive_memo_markdown,
                appendix_markdown=appendix_markdown,
                conflict_summary_markdown=conflict_summary_markdown,
                decision_snapshot=decision_snapshot,
            )
        except Exception:
            return fallback_report

    def revise_report(
        self,
        request: Dict[str, Any],
        current_report: Dict[str, Any],
        claims: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        competitor_names: List[str],
        feedback_notes: List[Dict[str, Any]],
        conversation_excerpt: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        claims, evidence, evidence_filter = self._filter_finalizable_material(claims, evidence)
        dossier = self._build_report_dossier(
            request=request,
            claims=claims,
            evidence=evidence,
            competitor_names=competitor_names,
            feedback_notes=feedback_notes,
            conversation_excerpt=conversation_excerpt,
            current_report=current_report,
            stage="final",
        )
        conflict_dossier = self._build_conflict_dossier(claims)
        decision_snapshot = self._build_decision_snapshot(claims, evidence, dossier, conflict_dossier)
        dossier["decision_snapshot"] = decision_snapshot
        dossier["conflicts"] = conflict_dossier
        fallback_report = self._build_fallback_report(
            request,
            claims,
            evidence,
            competitor_names,
            stage="final",
            feedback_notes=feedback_notes,
            previous_report=current_report,
            dossier=dossier,
        )
        fallback_report["evidence_filter"] = evidence_filter
        if not self.llm_client or not self.llm_client.is_enabled():
            return fallback_report

        try:
            system_prompt = load_prompt_template("synthesizer")
            content = self.llm_client.complete(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "你现在处于独立的最终成文上下文。"
                            "前面的调研步骤已经完成，新增补研结果和 PM 反馈也已经被整理成结构化 dossier。"
                            "请把 dossier 当作写作上下文，重新写成一份更完整、更可讨论、更适合评审会直接使用的长报告终稿。"
                            "不要把 claim/evidence 的结构化字段原样贴进正文，也不要把旧报告段落机械改写后拼接。"
                            "\n要求："
                            "\n1. 把 PM 反馈和补研结论整合到对应正文，而不是只在最后追加。"
                            "\n2. 保持 evidence-grounded；如果 dossier 里没有足够证据，就明确写出限制与使用边界。"
                            "\n3. 必须包含并清晰写好以下二级标题：核心结论摘要、决策快照、研究范围与方法、市场结构与趋势、目标用户与关键任务、竞争格局、重点竞品拆解、"
                            "定价、商业模式与渠道、产品体验与关键流程、用户声音与情绪反馈、机会地图、风险与约束、建议动作、待验证问题、证据冲突与使用边界、关键证据摘录。"
                            "\n4. 必须覆盖推荐动作、风险、待验证问题，并区分高置信度判断与推断。"
                            "\n5. 核心结论摘要需要像管理层摘要，明确回答“现阶段最重要的判断是什么、为什么重要、下一步做什么”。"
                            "\n6. 决策快照必须明确写出当前决策成熟度和使用边界。"
                            "\n7. 竞争格局、建议动作、关键证据摘录、证据冲突与使用边界尽量用 Markdown 表格表达。"
                            "\n8. PM 反馈整合保留为精炼的版本变化说明，不要替代正文。"
                            "\n9. 如果 output_locale 是 zh-CN，请正文与标题都使用专业简体中文。"
                            "\n10. PM Chat 后续会直接基于这份终稿继续对话，所以结构要清晰、章节边界要稳定。"
                            "\n11. 每个主要章节尽量写成：当前判断 -> 为什么重要 -> 最强证据/来源线索 -> 仍需保留的边界。"
                            "\n12. 研究范围与方法需要明确 source footprint，不要只列配置。"
                            "\n13. 你要综合重写，不要按 dossier 字段顺序逐段转写。正文应该像真正交付给团队的研究稿。"
                            "\n14. 优先吸收 report_dossier.argument_chains，把“判断为何成立”写清楚；每个关键章节都尽量包含判断依据、使用边界和对 PM 的含义。"
                            "\n15. 不要让正文退化成 bullet 清单；除表格外，核心章节要有成段论证。"
                            "\n16. 对核心判断执行严格的 [Sx] 引用纪律：只引用 dossier 中真实存在的 citation_label；没有对应引用时不要伪造。"
                            "\n17. 当来源层级明显不同，要让正文体现一手/高权威来源优先、社区或弱信号作为补充，而不是混为一谈。"
                            "\n18. 若 report_dossier.section_sufficiency[章节].sufficient=false，除竞争格局、建议动作、待验证问题外，不要强行展开成长段，可明确写证据不足。"
                            f"\nreport_dossier={json.dumps(dossier, ensure_ascii=False)}"
                        ),
                    },
                ],
                temperature=0.14,
                max_tokens=4600,
            )
            content = self._polish_generated_markdown(
                markdown=content,
                request=request,
                stage="final",
                fallback_markdown=fallback_report["markdown"],
                feedback_notes=feedback_notes,
            )
            board_brief_markdown = self._build_board_brief_markdown(
                request=request,
                claims=claims,
                dossier=dossier,
                decision_snapshot=decision_snapshot,
                conflict_dossier=conflict_dossier,
                stage="final",
            )
            executive_memo_markdown = self._build_executive_memo_markdown(
                request=request,
                report_markdown=content,
                decision_snapshot=decision_snapshot,
                conflict_dossier=conflict_dossier,
                stage="final",
            )
            conflict_summary_markdown = self._build_conflict_summary_markdown(
                request=request,
                conflict_dossier=conflict_dossier,
                decision_snapshot=decision_snapshot,
                dossier=dossier,
                stage="final",
            )
            appendix_markdown = self._build_appendix_markdown(
                request=request,
                dossier=dossier,
                evidence=evidence,
                competitor_names=competitor_names,
                feedback_notes=feedback_notes,
                stage="final",
            )
            report_asset = self._compose_report_asset(
                markdown=content,
                evidence_count=len(evidence),
                stage="final",
                previous_report=current_report,
                feedback_notes=feedback_notes,
                board_brief_markdown=board_brief_markdown,
                executive_memo_markdown=executive_memo_markdown,
                appendix_markdown=appendix_markdown,
                conflict_summary_markdown=conflict_summary_markdown,
                decision_snapshot=decision_snapshot,
            )
            report_asset["evidence_filter"] = evidence_filter
            return report_asset
        except Exception:
            return fallback_report
