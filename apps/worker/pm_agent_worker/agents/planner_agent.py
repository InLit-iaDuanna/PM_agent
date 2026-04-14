import os
import queue
import threading
from typing import Any, Dict, List, Optional

from pm_agent_worker.tools.config_loader import load_industry_templates, load_orchestration_presets, load_research_steps
from pm_agent_worker.tools.minimax_client import MiniMaxChatClient
from pm_agent_worker.tools.prompt_loader import load_prompt_template


CATEGORY_STEP_MAP = {
    "market_trends": "market-trends",
    "user_jobs_and_pains": "user-research",
    "competitor_landscape": "competitor-analysis",
    "product_experience_teardown": "experience-teardown",
    "reviews_and_sentiment": "reviews-and-sentiment",
    "pricing_and_business_model": "business-and-channels",
    "acquisition_and_distribution": "business-and-channels",
    "opportunities_and_risks": "opportunities-and-risks",
}

BALANCED_CATEGORY_PRIORITY = (
    "market_trends",
    "user_jobs_and_pains",
    "competitor_landscape",
    "pricing_and_business_model",
    "product_experience_teardown",
    "reviews_and_sentiment",
    "acquisition_and_distribution",
    "opportunities_and_risks",
)

DEFAULT_WORKFLOW_COMMAND = "deep_general_scan"

CATEGORY_SKILL_PACKS = {
    "market_trends": ("market-sizing-lite", "trend-triangulation", "benchmark-scouting"),
    "user_jobs_and_pains": ("jtbd-extraction", "pain-point-ranking", "voice-snippet-capture"),
    "competitor_landscape": ("competitive-mapping", "segment-layering", "positioning-diff"),
    "product_experience_teardown": ("flow-teardown", "feature-diffing", "friction-mapping"),
    "reviews_and_sentiment": ("review-clustering", "voice-of-customer", "signal-polarity"),
    "pricing_and_business_model": ("pricing-benchmarking", "packaging-analysis", "value-metric-check"),
    "acquisition_and_distribution": ("channel-diagnostics", "distribution-mapping", "growth-loop-check"),
    "opportunities_and_risks": ("opportunity-ranking", "execution-risk-audit", "decision-briefing"),
}

CATEGORY_AGENT_BLUEPRINTS = {
    "market_trends": {
        "goal": "像深度研究员一样确认 {topic} 所处赛道边界、增长方向和外部 benchmark，而不是只收集泛行业资讯。",
        "search_intents": ("official", "analysis", "comparison"),
        "must_cover": ("赛道边界与定义", "增长/采用信号", "外部 benchmark 或代表性案例"),
        "completion_criteria": ("至少 1 个权威/一手来源", "至少 1 个第三方趋势或分析来源", "至少 1 条交叉验证证据"),
    },
    "user_jobs_and_pains": {
        "goal": "确认 {topic} 的目标用户、核心场景、替代方案和高频痛点，优先真实用户声音而不是品牌自述。",
        "search_intents": ("community", "analysis", "official"),
        "must_cover": ("目标用户或角色", "高频任务与痛点", "替代方案/当前做法"),
        "completion_criteria": ("至少 1 个社区/评论来源", "至少 1 个案例/分析来源", "需要能提炼出具体 pain point"),
    },
    "competitor_landscape": {
        "goal": "建立 {topic} 的竞品版图与玩家分层，识别直接竞品、替代品和差异化信号。",
        "search_intents": ("official", "comparison", "community"),
        "must_cover": ("直接竞品", "替代方案", "核心差异点"),
        "completion_criteria": ("至少 2 个竞品被明确点名", "至少 1 个对比/替代来源", "至少 1 个外部口碑或评论来源"),
    },
    "product_experience_teardown": {
        "goal": "拆解 {topic} 的关键体验链路、交互结构和能力边界，优先产品文档、实操内容和真实体验反馈。",
        "search_intents": ("official", "comparison", "community"),
        "must_cover": ("核心流程/上手链路", "关键功能或体验亮点", "真实使用摩擦"),
        "completion_criteria": ("至少 1 个官方产品/文档来源", "至少 1 个体验反馈来源", "至少 1 个可对比的竞品视角"),
    },
    "reviews_and_sentiment": {
        "goal": "聚焦 {topic} 的高频好评、差评与争议点，区分真实用户声音与营销话术。",
        "search_intents": ("community", "analysis", "comparison"),
        "must_cover": ("高频好评", "高频差评", "争议或分歧点"),
        "completion_criteria": ("至少 2 个社区/评论来源", "需要有正负两类信号", "至少 1 条可用于 PM 判断的用户原声"),
    },
    "pricing_and_business_model": {
        "goal": "确认 {topic} 的定价方式、打包逻辑和商业化抓手，并与替代方案交叉比较。",
        "search_intents": ("official", "comparison", "community"),
        "must_cover": ("套餐/计费方式", "免费到付费路径", "和主要替代方案的差异"),
        "completion_criteria": ("至少 1 个官方定价来源", "至少 1 个第三方对比来源", "至少 1 条用户对价格/价值的反馈"),
    },
    "acquisition_and_distribution": {
        "goal": "识别 {topic} 的主要获客、分发和合作路径，判断增长是否依赖单一渠道。",
        "search_intents": ("analysis", "official", "community"),
        "must_cover": ("主要获客/分发路径", "合作/生态线索", "可复制或受限的增长机制"),
        "completion_criteria": ("至少 1 个分析/案例来源", "至少 1 个官方或生态来源", "至少 1 条真实市场反馈"),
    },
    "opportunities_and_risks": {
        "goal": "基于已知证据识别 {topic} 的机会窗口、约束条件和容易误判的地方。",
        "search_intents": ("analysis", "community", "comparison"),
        "must_cover": ("机会窗口", "执行约束或风险", "容易被高估/低估的变量"),
        "completion_criteria": ("至少 1 个行业分析来源", "至少 1 个真实市场/用户反馈来源", "至少 1 条交叉验证或反例"),
    },
}


class PlannerAgent:
    def __init__(self, llm_client: Optional[MiniMaxChatClient] = None) -> None:
        self.llm_client = llm_client

    def _planner_llm_timeout_seconds(self) -> float:
        try:
            return max(2.0, float(os.getenv("PM_AGENT_PLANNER_LLM_TIMEOUT_SECONDS", "12")))
        except (TypeError, ValueError):
            return 12.0

    def _complete_json_with_timeout(self, messages: List[Dict[str, str]], temperature: float, max_tokens: int) -> Any:
        if not self.llm_client:
            raise RuntimeError("Planner LLM client is unavailable")

        timeout_seconds = self._planner_llm_timeout_seconds()
        result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                result = self.llm_client.complete_json(messages, temperature=temperature, max_tokens=max_tokens)
                result_queue.put(("result", result))
            except Exception as error:  # pragma: no cover - propagated to caller
                result_queue.put(("error", error))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            kind, payload = result_queue.get(timeout=timeout_seconds)
        except queue.Empty as error:
            raise TimeoutError(f"planner llm timed out after {timeout_seconds:.1f}s") from error
        if kind == "error":
            raise payload
        return payload

    def _resolve_orchestration_preset(self, request: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        presets = load_orchestration_presets()
        requested_id = str(request.get("workflow_command") or DEFAULT_WORKFLOW_COMMAND).strip() or DEFAULT_WORKFLOW_COMMAND
        preset = presets.get(requested_id) or presets.get(DEFAULT_WORKFLOW_COMMAND) or {}
        resolved_id = requested_id if requested_id in presets else DEFAULT_WORKFLOW_COMMAND
        return resolved_id, preset

    def _short_project_memory(self, request: Dict[str, Any], limit: int = 200) -> str:
        project_memory = " ".join(str(request.get("project_memory") or "").split()).strip()
        if len(project_memory) <= limit:
            return project_memory
        return project_memory[: limit - 3].rstrip() + "..."

    def _sanitize_string_list(self, value: Any, fallback: tuple[str, ...], limit: int = 4) -> List[str]:
        if not isinstance(value, list):
            return list(fallback)
        cleaned: List[str] = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= limit:
                break
        return cleaned or list(fallback)

    def _task_blueprint(self, category: str, request: Dict[str, Any], workflow_command: str, preset: Dict[str, Any]) -> Dict[str, Any]:
        config = CATEGORY_AGENT_BLUEPRINTS.get(
            category,
            {
                "goal": "围绕 {topic} 做证据驱动的深度研究，优先补足可验证的一手来源和交叉验证来源。",
                "search_intents": ("official", "analysis", "community"),
                "must_cover": ("一手来源", "第三方分析", "交叉验证"),
                "completion_criteria": ("至少覆盖 3 类来源意图", "至少保留 1 条高置信证据", "不要只停留在单一域名"),
            },
        )
        topic = str(request.get("topic") or "该主题").strip()
        project_memory = self._short_project_memory(request)
        default_skill_packs = [str(item).strip() for item in preset.get("defaultSkillPacks", []) if str(item).strip()]
        category_skill_packs = [str(item).strip() for item in CATEGORY_SKILL_PACKS.get(category, ()) if str(item).strip()]
        merged_skill_packs: List[str] = []
        for item in [*default_skill_packs, *category_skill_packs]:
            if item not in merged_skill_packs:
                merged_skill_packs.append(item)
        command_label = str(preset.get("label") or workflow_command).strip()
        orchestration_notes = (
            f"Workflow command: {command_label}. "
            f"Focus: {str(preset.get('focusInstruction') or '').strip() or 'Keep the run decision-oriented and evidence-first.'}"
        ).strip()
        if project_memory:
            orchestration_notes += f" Project memory: {project_memory}"
        return {
            "agent_mode": "deep_research_harness",
            "command_id": workflow_command,
            "command_label": command_label,
            "research_goal": (
                f"{str(preset.get('focusInstruction') or '').strip()} "
                f"{str(config['goal']).format(topic=topic)}"
            ).strip(),
            "search_intents": list(config["search_intents"]),
            "must_cover": list(config["must_cover"]),
            "completion_criteria": list(config["completion_criteria"]),
            "skill_packs": merged_skill_packs or ["source-triangulation", "decision-memo"],
            "orchestration_notes": orchestration_notes,
        }

    def _select_categories(self, template: Dict[str, Any], max_subtasks: int, preset: Optional[Dict[str, Any]] = None) -> List[str]:
        available = list(template["taskCategories"])
        if max_subtasks >= len(available):
            return available

        selected: List[str] = []
        priority_chain = []
        for category in list(preset.get("categoryPriority", []) if preset else []) + list(BALANCED_CATEGORY_PRIORITY):
            if category not in priority_chain:
                priority_chain.append(category)

        for category in priority_chain:
            if category in available and category not in selected:
                selected.append(category)
            if len(selected) >= max_subtasks:
                return selected

        for category in available:
            if category not in selected:
                selected.append(category)
            if len(selected) >= max_subtasks:
                break
        return selected[:max_subtasks]

    def _build_fallback_tasks(
        self,
        request: Dict[str, Any],
        categories: List[str],
        template: Dict[str, Any],
        steps: List[Dict[str, Any]],
        workflow_command: str,
        preset: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        step_map = {step["id"]: step for step in steps}
        fallback_tasks = []

        for index, category in enumerate(categories):
            market_step = CATEGORY_STEP_MAP.get(category, "market-trends")
            step = step_map.get(market_step, {"id": market_step, "title": market_step})
            blueprint = self._task_blueprint(category, request, workflow_command, preset)
            fallback_tasks.append(
                {
                    "id": f"{request['job_id']}-task-{index + 1}",
                    "category": category,
                    "title": f"{template['label']} · {step['title']}",
                    "brief": f"围绕 {request['topic']} 调研 {step['title']}，重点关注 {', '.join(template['focusAreas'][:2])}。",
                    "market_step": step["id"],
                    "status": "queued",
                    "source_count": 0,
                    "retry_count": 0,
                    "latest_error": None,
                    **blueprint,
                }
            )
        return fallback_tasks

    def _sanitize_tasks(
        self,
        request: Dict[str, Any],
        categories: List[str],
        raw_tasks: Any,
        template: Dict[str, Any],
        steps: List[Dict[str, Any]],
        workflow_command: str,
        preset: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if not isinstance(raw_tasks, list):
            return []

        fallback_tasks = self._build_fallback_tasks(request, categories, template, steps, workflow_command, preset)
        allowed_steps = {step["id"] for step in steps}
        sanitized: List[Dict[str, Any]] = []
        seen_categories = set()
        for index, item in enumerate(raw_tasks[: request["max_subtasks"] * 2], start=1):
            if not isinstance(item, dict):
                continue
            category = item.get("category")
            if category not in categories or category in seen_categories:
                continue
            fallback_index = categories.index(category)
            market_step = item.get("market_step") or CATEGORY_STEP_MAP.get(category, fallback_tasks[fallback_index]["market_step"])
            if market_step not in allowed_steps:
                market_step = fallback_tasks[fallback_index]["market_step"]
            sanitized.append(
                {
                    "id": item.get("id") or f"{request['job_id']}-task-{len(sanitized) + 1}",
                    "category": category,
                    "title": item.get("title") or fallback_tasks[fallback_index]["title"],
                    "brief": item.get("brief") or fallback_tasks[fallback_index]["brief"],
                    "market_step": market_step,
                    "status": "queued",
                    "source_count": 0,
                    "retry_count": 0,
                    "latest_error": None,
                    "command_id": str(item.get("command_id") or fallback_tasks[fallback_index]["command_id"]).strip()
                    or fallback_tasks[fallback_index]["command_id"],
                    "command_label": str(item.get("command_label") or fallback_tasks[fallback_index]["command_label"]).strip()
                    or fallback_tasks[fallback_index]["command_label"],
                    "agent_mode": str(item.get("agent_mode") or fallback_tasks[fallback_index]["agent_mode"]).strip() or fallback_tasks[fallback_index]["agent_mode"],
                    "research_goal": str(item.get("research_goal") or fallback_tasks[fallback_index]["research_goal"]).strip()
                    or fallback_tasks[fallback_index]["research_goal"],
                    "search_intents": self._sanitize_string_list(
                        item.get("search_intents"),
                        tuple(fallback_tasks[fallback_index]["search_intents"]),
                    ),
                    "must_cover": self._sanitize_string_list(
                        item.get("must_cover"),
                        tuple(fallback_tasks[fallback_index]["must_cover"]),
                    ),
                    "completion_criteria": self._sanitize_string_list(
                        item.get("completion_criteria"),
                        tuple(fallback_tasks[fallback_index]["completion_criteria"]),
                    ),
                    "skill_packs": self._sanitize_string_list(
                        item.get("skill_packs"),
                        tuple(fallback_tasks[fallback_index]["skill_packs"]),
                        limit=6,
                    ),
                    "orchestration_notes": str(item.get("orchestration_notes") or fallback_tasks[fallback_index]["orchestration_notes"]).strip()
                    or fallback_tasks[fallback_index]["orchestration_notes"],
                }
            )
            seen_categories.add(category)
            if len(sanitized) >= len(categories):
                break

        for fallback_task in fallback_tasks:
            if len(sanitized) >= len(categories):
                break
            if fallback_task["category"] in seen_categories:
                continue
            sanitized.append(fallback_task)
            seen_categories.add(fallback_task["category"])
        return sanitized

    def build_tasks(self, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        templates = load_industry_templates()
        steps = load_research_steps()
        workflow_command, preset = self._resolve_orchestration_preset(request)
        template = templates[request["industry_template"]]
        categories = self._select_categories(template, request["max_subtasks"], preset)
        fallback_tasks = self._build_fallback_tasks(request, categories, template, steps, workflow_command, preset)
        if not self.llm_client or not self.llm_client.is_enabled():
            return fallback_tasks

        try:
            system_prompt = load_prompt_template("planner")
            result = self._complete_json_with_timeout(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "请将以下研究任务拆成 JSON 数组，字段必须包含 id/category/title/brief/market_step/status/source_count/retry_count/latest_error。\n"
                            "每个任务还应该尽量包含 command_id/command_label/agent_mode/research_goal/search_intents/must_cover/completion_criteria/skill_packs/orchestration_notes，用于后续深度研究循环。\n"
                            "任务之间必须覆盖不同研究维度，不要把两个任务都写成同一类视角的重复拆分。\n"
                            "优先保证市场/用户/竞品/商业化或体验中的横向覆盖，再考虑纵向细化。\n"
                            f"topic={request['topic']}\n"
                            f"industry_template={request['industry_template']}\n"
                            f"research_mode={request['research_mode']}\n"
                            f"workflow_command={workflow_command}\n"
                            f"workflow_label={preset.get('label')}\n"
                            f"workflow_summary={preset.get('summary')}\n"
                            f"workflow_focus_instruction={preset.get('focusInstruction')}\n"
                            f"default_skill_packs={preset.get('defaultSkillPacks', [])}\n"
                            f"project_memory={self._short_project_memory(request)}\n"
                            f"allowed_categories={categories}\n"
                            f"category_to_market_step={CATEGORY_STEP_MAP}\n"
                            f"focus_areas={template['focusAreas']}\n"
                            f"job_id={request['job_id']}\n"
                            "只返回 JSON。"
                        ),
                    },
                ],
                temperature=0.1,
                max_tokens=1400,
            )
            sanitized = self._sanitize_tasks(request, categories, result, template, steps, workflow_command, preset)
            if sanitized:
                return sanitized
        except Exception:
            return fallback_tasks
        return fallback_tasks
