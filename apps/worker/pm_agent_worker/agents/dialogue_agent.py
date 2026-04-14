import re
from typing import Any, Dict, List, Optional, Tuple

from pm_agent_worker.tools.minimax_client import MiniMaxChatClient
from pm_agent_worker.tools.prompt_loader import load_prompt_template
from pm_agent_worker.workflows.presentation_labels import market_step_label
from pm_agent_worker.workflows.research_models import DeltaResearchResult, iso_now

SECTION_HEADING_ALIASES = {
    "市场结构与趋势": ["Market Structure & Trends"],
    "目标用户与关键任务": ["Target Users & JTBD"],
    "竞争格局": ["Competitive Landscape"],
    "风险与约束": ["Risks & Constraints"],
    "建议动作": ["Recommended Actions"],
    "定价、商业模式与渠道": ["Pricing / Business Model / Channel"],
}


class DialogueAgent:
    def __init__(self, llm_client: Optional[MiniMaxChatClient] = None) -> None:
        self.llm_client = llm_client

    def _claim_text(self, claim: Dict[str, Any]) -> str:
        claim_text = claim.get("claim_text")
        if isinstance(claim_text, str) and claim_text.strip():
            return claim_text.strip()
        caveats = claim.get("caveats")
        if isinstance(caveats, list):
            for item in caveats:
                text = str(item or "").strip()
                if text:
                    return text
        elif isinstance(caveats, str) and caveats.strip():
            return caveats.strip()
        market_step = str(claim.get("market_step") or "").strip()
        if market_step:
            return f"{market_step_label(market_step)}维度已有补充结论，但原始 claim_text 缺失。"
        return "这条补充结论缺少正文。"

    def _is_social_message(self, text: str) -> bool:
        normalized = text.strip().lower()
        social_tokens = {
            "hi",
            "hello",
            "hey",
            "你好",
            "您好",
            "嗨",
            "在吗",
            "哈喽",
            "hello there",
            "早上好",
            "下午好",
            "晚上好",
        }
        return normalized in social_tokens

    def _looks_like_report_feedback(self, text: str) -> bool:
        lowered = text.strip().lower()
        feedback_tokens = (
            "补充",
            "补研",
            "完善",
            "终稿",
            "长报告",
            "细化",
            "展开",
            "深入",
            "调研",
            "研究",
            "扩写",
            "重写",
            "加入",
            "补全",
            "报告",
            "delta",
            "refine",
            "expand",
            "report",
            "revise",
            "investigate",
            "deeper",
            "research more",
        )
        return any(token in lowered for token in feedback_tokens)

    def _extract_tokens(self, text: str) -> List[str]:
        normalized = text.lower().strip()
        if not normalized:
            return []

        tokens = [normalized]
        for token in re.findall(r"[a-z0-9][a-z0-9\-_/.]+|[\u4e00-\u9fff]{2,}", normalized):
            if token not in tokens:
                tokens.append(token)
        return tokens[:12]

    def _score_text(self, text: str, tokens: List[str]) -> int:
        lowered = str(text or "").lower()
        return sum(1 for token in tokens if token and token in lowered)

    def _select_claims(self, claims: List[Dict[str, Any]], tokens: List[str]) -> List[Dict[str, Any]]:
        ranked = []
        for claim in claims:
            score = self._score_text(self._claim_text(claim), tokens)
            if score <= 0:
                continue
            ranked.append((score, claim))
        ranked.sort(
            key=lambda item: (
                item[0],
                float(item[1].get("actionability_score", 0)),
                float(item[1].get("confidence", 0)),
            ),
            reverse=True,
        )
        return [claim for _, claim in ranked[:3]]

    def _select_evidence(self, evidence: List[Dict[str, Any]], tokens: List[str]) -> List[Dict[str, Any]]:
        ranked = []
        for item in evidence:
            score = self._score_text(
                " ".join([str(item.get("title") or ""), str(item.get("summary") or ""), str(item.get("quote") or "")]),
                tokens,
            )
            if score <= 0:
                continue
            ranked.append((score, item))
        ranked.sort(key=lambda entry: (entry[0], float(entry[1].get("confidence", 0))), reverse=True)
        return [item for _, item in ranked[:2]]

    def _select_report_excerpt(self, report_markdown: str, tokens: List[str]) -> Tuple[str, bool]:
        lines = [line.strip() for line in report_markdown.splitlines() if line.strip()]
        if not lines:
            return "", False

        ranked = sorted(lines, key=lambda line: self._score_text(line, tokens), reverse=True)
        excerpt_lines = [line for line in ranked if not line.startswith("#")][:3]
        if any(self._score_text(line, tokens) > 0 for line in excerpt_lines):
            return "\n".join(excerpt_lines), True

        sections: Dict[str, List[str]] = {}
        current_section = ""
        for line in lines:
            if line.startswith("## "):
                current_section = line[3:].strip()
                sections.setdefault(current_section, [])
                continue
            if current_section:
                sections.setdefault(current_section, []).append(line)

        def get_section_lines(section_name: str) -> List[str]:
            aliases = {section_name}
            if section_name in SECTION_HEADING_ALIASES:
                aliases.update(SECTION_HEADING_ALIASES[section_name])
            for canonical, legacy_aliases in SECTION_HEADING_ALIASES.items():
                if section_name == canonical or section_name in legacy_aliases:
                    aliases.add(canonical)
                    aliases.update(legacy_aliases)
            collected: List[str] = []
            for alias in aliases:
                collected.extend(sections.get(alias, []))
            return collected

        intent_section_map = [
            (("建议", "下一步", "action", "recommend"), "建议动作"),
            (("渠道", "获客", "channel", "distribution"), "定价、商业模式与渠道"),
            (("定价", "收费", "pricing", "price"), "定价、商业模式与渠道"),
            (("竞品", "竞争", "competitor"), "竞争格局"),
            (("用户", "人群", "jtbd", "pain"), "目标用户与关键任务"),
            (("市场", "趋势", "market"), "市场结构与趋势"),
            (("风险", "constraint", "risk"), "风险与约束"),
        ]
        for keywords, section_name in intent_section_map:
            if any(keyword in token for keyword in keywords for token in tokens):
                section_lines = [
                    line
                    for line in get_section_lines(section_name)
                    if "当前样本尚不足" not in line and "建议继续补充" not in line
                ]
                if section_lines:
                    return "\n".join(section_lines[:3]), True

        return "", False

    def _serialize_history(self, messages: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, str]]:
        serialized: List[Dict[str, str]] = []
        for message in messages[-limit:]:
            role = message.get("role")
            content = (message.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                serialized.append({"role": role, "content": content})
        return serialized

    def build_response(
        self,
        user_message: str,
        claims: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        report_markdown: str,
        job_id: str,
        message_history: Optional[List[Dict[str, Any]]] = None,
        report_stage: str = "draft",
        project_memory: str = "",
        workflow_command_label: str = "",
    ) -> Dict[str, object]:
        del job_id
        tokens = self._extract_tokens(user_message)
        matched_claims = self._select_claims(claims, tokens) if claims else []
        matched_evidence = self._select_evidence(evidence, tokens) if evidence else []
        report_excerpt, report_has_match = self._select_report_excerpt(report_markdown, tokens) if report_markdown else ("", False)
        history_excerpt = self._serialize_history(message_history or [])
        feedback_intent = self._looks_like_report_feedback(user_message)

        if self.llm_client and self.llm_client.is_enabled():
            try:
                system_prompt = load_prompt_template("dialogue")
                result = self.llm_client.complete_json(
                    [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": (
                                "你正在作为 PM Research Chat 与用户对话。"
                                "请优先使用研究报告、claims、evidence 和对话历史来回答。"
                                "如果用户在给报告提反馈、要求补充、扩写或修订，通常应该给出当前回答并把 needs_delta_research 设为 true，以便后续更新报告。"
                                "只有当现有上下文明显不足时，才把 needs_delta_research 设为 true。"
                                "问候语、寒暄、确认类消息不要触发补研。"
                                "返回 JSON 对象，字段必须包含 content/cited_claim_ids/needs_delta_research。"
                                f"\nquestion={user_message}"
                                f"\nreport_stage={report_stage}"
                                f"\nworkflow_command={workflow_command_label}"
                                f"\nproject_memory={project_memory[:1000]}"
                                f"\nconversation_history={history_excerpt}"
                                f"\nreport_markdown={report_markdown[:5000]}"
                                f"\nclaims={claims[:8]}"
                                f"\nevidence={evidence[:6]}"
                                "\n只返回 JSON。"
                            ),
                        },
                    ],
                    temperature=0.2,
                    max_tokens=1400,
                )
                if isinstance(result, dict) and "content" in result:
                    valid_claim_ids = {claim.get("id") for claim in claims}
                    cited_claim_ids = [claim_id for claim_id in result.get("cited_claim_ids", []) if claim_id in valid_claim_ids]
                    return {
                        "content": result["content"],
                        "cited_claim_ids": cited_claim_ids,
                        "needs_delta_research": bool(result.get("needs_delta_research", False)),
                    }
            except Exception:
                pass

        if self._is_social_message(user_message):
            summary_hint = report_excerpt or "我已经接入当前报告、claims 和 evidence，可以继续问我结论、建议、竞品、用户痛点或渠道策略。"
            if workflow_command_label:
                summary_hint = f"当前研究指令是 {workflow_command_label}。{summary_hint}"
            return {
                "content": "\n".join(
                    [
                        "### 我在",
                        f"你好，我在。{summary_hint}",
                        "",
                        "### 你可以继续问",
                        "- 产品策略怎么排优先级",
                        "- 竞品差异和切入机会",
                        "- 用户痛点、渠道或定价问题",
                    ]
                ),
                "cited_claim_ids": [],
                "needs_delta_research": False,
            }

        if matched_claims or matched_evidence or report_has_match:
            fallback_sections: List[str] = []
            fallback_sections.append("### 直接回答")
            fallback_sections.append(f"基于当前报告{'终稿' if report_stage == 'final' else '初稿'}，我先给你一个可执行回答。")
            if workflow_command_label:
                fallback_sections.append(f"- 当前研究指令：{workflow_command_label}")
            if project_memory.strip():
                fallback_sections.append(f"- 已继承项目记忆：{project_memory.strip()[:160]}")
            if matched_claims:
                fallback_sections.append("### 关键结论")
                fallback_sections.append(
                    "\n".join(
                        [f"- {self._claim_text(claim)}（状态：{claim['status']}，置信度：{claim['confidence']}）" for claim in matched_claims[:3]]
                    )
                )
            if report_excerpt:
                fallback_sections.append("### 报告片段")
                fallback_sections.append(report_excerpt)
            if matched_evidence and not matched_claims:
                fallback_sections.append("### 补充证据")
                fallback_sections.append(
                    "\n".join([f"- {item['title']}：{item['summary']}" for item in matched_evidence[:2]])
                )
            if feedback_intent:
                fallback_sections.append("### 下一步")
                fallback_sections.append("- 我会把这条反馈纳入报告，并继续补齐需要扩展的部分。")
            fallback_result = {
                "content": "\n".join(fallback_sections),
                "cited_claim_ids": [claim["id"] for claim in matched_claims[:3]],
                "needs_delta_research": feedback_intent,
            }
            if not self.llm_client or not self.llm_client.is_enabled():
                return fallback_result
            return fallback_result

        if feedback_intent and report_markdown:
            return {
                "content": "\n".join(
                    [
                        "### 已记录反馈",
                        "- 我会基于当前报告继续补齐这部分内容。",
                        "- 这条反馈会进入下一版长报告。",
                    ]
                ),
                "cited_claim_ids": [],
                "needs_delta_research": True,
            }

        return {
            "content": "\n".join(
                [
                    "### 当前状态",
                    "- 现有报告里还没有足够材料回答这个问题。",
                    "",
                    "### 下一步",
                    "- 我会触发补充研究。",
                    "- 完成后会把结果回填到对话和报告。",
                ]
            ),
            "cited_claim_ids": [],
            "needs_delta_research": True,
        }

    def build_report_addendum(self, user_message: str, claim: Dict[str, Any], follow_up_message: str) -> str:
        lines = [
            f"### {user_message}",
            f"- 补充结论：{self._claim_text(claim)}",
            f"- 回答：{follow_up_message}",
            f"- 置信度：{claim['confidence']}",
        ]
        caveats = claim.get("caveats") or []
        if caveats:
            lines.append("- Caveats：" + "；".join(caveats))
        return "\n".join(lines)

    def build_delta_follow_up(self, user_message: str, claim: Dict[str, Any], evidence: List[Dict[str, Any]]) -> str:
        evidence_sample = [
            {
                "title": item.get("title"),
                "summary": item.get("summary"),
                "source_url": item.get("source_url"),
                "source_type": item.get("source_type"),
            }
            for item in evidence[:3]
        ]
        fallback_lines = [
            "### 补充研究已完成",
            f"围绕“{user_message}”，当前更稳妥的回答是：",
            "",
            "### 更新后的判断",
            f"- {self._claim_text(claim)}",
        ]
        if evidence_sample:
            fallback_lines.append("")
            fallback_lines.append("### 这次主要参考了")
            fallback_lines.extend(
                [f"- {item['title']}（{item['source_type']}）：{item['summary']}" for item in evidence_sample if item.get("title")]
            )
        caveats = claim.get("caveats") or []
        if caveats:
            fallback_lines.append("")
            fallback_lines.append("### 需要注意")
            fallback_lines.extend([f"- {caveat}" for caveat in caveats[:2]])
        fallback_message = "\n".join(fallback_lines)

        if not self.llm_client or not self.llm_client.is_enabled():
            return fallback_message

        try:
            system_prompt = load_prompt_template("dialogue")
            result = self.llm_client.complete_json(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "请基于以下追问补充研究，用 PM 对话口吻生成一个 JSON 对象。"
                            "字段必须包含 follow_up_message。"
                            f"\nquestion={user_message}"
                            f"\nclaim={claim}"
                            f"\nevidence={evidence_sample}"
                            "\n只返回 JSON。"
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=800,
            )
            if isinstance(result, dict) and result.get("follow_up_message"):
                return str(result["follow_up_message"]).strip()
        except Exception:
            return fallback_message
        return fallback_message

    def run_delta_research(self, research_job_id: str, user_message: str, delta_job_id: str) -> DeltaResearchResult:
        evidence = {
            "id": f"{delta_job_id}-evidence-1",
            "task_id": f"{delta_job_id}-task",
            "market_step": "recommendations",
            "source_url": f"internal://delta-context/{delta_job_id}",
            "source_type": "internal",
            "source_tier": "t4",
            "source_tier_label": "T4 内部上下文线索（不可单独成稿）",
            "title": "补研兜底说明",
            "captured_at": iso_now(),
            "quote": f"用户追问：{user_message}",
            "summary": "这轮补充搜索没有拿到足够新的外部来源，系统先基于现有报告和对话上下文整理增量建议。",
            "extracted_fact": "未找到高质量新增外部来源时，系统会退回现有报告上下文给出保守建议。",
            "authority_score": 0.38,
            "freshness_score": 0.58,
            "confidence": 0.52,
            "injection_risk": 0.0,
            "evidence_role": "context_only",
            "final_eligibility": "requires_external_evidence",
            "tags": ["delta", "report-context-fallback", "delta-context-fallback", "context-only"],
            "competitor_name": None,
        }
        claim = {
            "id": f"{delta_job_id}-claim-1",
            "claim_text": f"围绕“{user_message}”建议先验证转化路径与用户付费意愿。",
            "market_step": "recommendations",
            "evidence_ids": [evidence["id"]],
            "counter_evidence_ids": [],
            "confidence": 0.52,
            "status": "inferred",
            "caveats": [
                "这次没有拿到足够新的外部来源，仍需补充定向搜索或一手验证",
                "当前仅有 internal://delta-context 类型线索，不能单独作为正式终稿证据链。",
            ],
            "competitor_ids": [],
            "priority": "medium",
            "actionability_score": 0.72,
            "last_verified_at": iso_now(),
            "final_eligibility": "requires_external_evidence",
            "evidence_boundary": "context_only",
        }
        if self.llm_client and self.llm_client.is_enabled():
            try:
                system_prompt = load_prompt_template("dialogue")
                result = self.llm_client.complete_json(
                    [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": (
                                "基于以下追问生成一个 JSON 对象，字段包含 claim_text/caveats/follow_up_message。"
                                f"\nquestion={user_message}\n"
                                "只返回 JSON。"
                            ),
                        },
                    ],
                    temperature=0.25,
                    max_tokens=900,
                )
                if isinstance(result, dict):
                    claim["claim_text"] = str(result.get("claim_text") or claim["claim_text"]).strip()
                    result_caveats = result.get("caveats")
                    if isinstance(result_caveats, list):
                        claim["caveats"] = [str(item).strip() for item in result_caveats if str(item).strip()] or claim["caveats"]
                    elif isinstance(result_caveats, str) and result_caveats.strip():
                        claim["caveats"] = [result_caveats.strip()]
                    follow_up_message = str(
                        result.get(
                            "follow_up_message",
                            f"这轮补充搜索没有拿到足够新的外部来源，我先基于现有报告建议优先验证“{user_message}”对应的关键假设。",
                        )
                    ).strip()
                else:
                    follow_up_message = f"这轮补充搜索没有拿到足够新的外部来源，我先基于现有报告建议优先验证“{user_message}”对应的关键假设。"
            except Exception:
                follow_up_message = f"这轮补充搜索没有拿到足够新的外部来源，我先基于现有报告建议优先验证“{user_message}”对应的关键假设。"
        else:
            follow_up_message = f"这轮补充搜索没有拿到足够新的外部来源，我先基于现有报告建议优先验证“{user_message}”对应的关键假设。"

        return DeltaResearchResult(
            delta_job_id=delta_job_id,
            claim=claim,
            evidence=[evidence],
            follow_up_message=follow_up_message,
        )
