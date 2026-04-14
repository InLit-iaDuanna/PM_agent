import asyncio
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional

from pm_agent_worker.agents.dialogue_agent import DialogueAgent
from pm_agent_worker.agents.planner_agent import PlannerAgent
from pm_agent_worker.agents.research_worker_agent import ResearchWorkerAgent
from pm_agent_worker.agents.synthesizer_agent import SynthesizerAgent
from pm_agent_worker.agents.verifier_agent import VerifierAgent
from pm_agent_worker.tools.config_loader import load_orchestration_presets, load_research_defaults
from pm_agent_worker.tools.llm_runtime import create_llm_client
from pm_agent_worker.tools.opencli_browser_tool import OpenCliBrowserTool
from pm_agent_worker.workflows.control import JobCancelledError
from pm_agent_worker.workflows.presentation_labels import market_step_label
from pm_agent_worker.workflows.progress_engine import recompute_overall_progress, set_phase_progress, update_collecting_progress
from pm_agent_worker.workflows.research_models import (
    DeltaResearchResult,
    append_report_version_snapshot_to_assets,
    attach_report_support_snapshot,
    build_empty_assets,
    build_phase_progress,
    build_report_version_snapshot,
    build_task_log,
    iso_now,
)


class ResearchWorkflowEngine:
    DELTA_RESEARCH_TIMEOUT_SECONDS = 12.0

    def __init__(self, runtime_config: Optional[Dict[str, Any]] = None) -> None:
        self.defaults = load_research_defaults()
        self.browser = OpenCliBrowserTool()
        self.runtime_config = runtime_config or {}
        self.llm_client = create_llm_client(self.runtime_config)
        self.planner = PlannerAgent(self.llm_client)
        self.research_worker = ResearchWorkerAgent(self.llm_client)
        self.verifier = VerifierAgent(self.llm_client)
        self.synthesizer = SynthesizerAgent(self.llm_client)
        self.dialogue = DialogueAgent(self.llm_client)

    def _resolve_orchestration_preset(self, workflow_command: Optional[str]) -> tuple[str, Dict[str, Any]]:
        presets = load_orchestration_presets()
        resolved_id = str(workflow_command or "deep_general_scan").strip() or "deep_general_scan"
        preset = presets.get(resolved_id) or presets.get("deep_general_scan") or {}
        if resolved_id not in presets:
            resolved_id = "deep_general_scan"
        return resolved_id, preset

    def _build_runtime_summary(self) -> Dict[str, Any]:
        summary = self.llm_client.status_summary()
        return {
            **summary,
            "browser_mode": self.browser.mode(),
            "browser_available": self.browser.is_available(),
        }

    def _resolve_retrieval_profile_id(self, request: Dict[str, Any]) -> Optional[str]:
        def _extract(candidate: Any) -> Optional[str]:
            if isinstance(candidate, dict):
                return candidate.get("profile_id") or candidate.get("id")
            if isinstance(candidate, str):
                return candidate
            return None

        runtime_config = request.get("runtime_config")
        profile_id = None
        if isinstance(runtime_config, dict):
            profile_id = _extract(runtime_config.get("retrieval_profile"))
            if not profile_id:
                profile_id = runtime_config.get("retrieval_profile_id") or runtime_config.get("retrievalProfileId")
        if not profile_id:
            profile_id = _extract(request.get("retrieval_profile")) or request.get("retrieval_profile_id")
        if profile_id:
            profile_id_str = str(profile_id).strip()
            if profile_id_str:
                return profile_id_str
        return None

    def build_job_blueprint(self, request: Dict[str, Any]) -> Dict[str, Any]:
        depth_config = deepcopy(self.defaults["depthPresets"][request["depth_preset"]])
        workflow_command, preset = self._resolve_orchestration_preset(request.get("workflow_command"))
        runtime_config = request.get("runtime_config") if isinstance(request.get("runtime_config"), dict) else {}
        for key, value in depth_config.items():
            request.setdefault(key, value)
        request["workflow_command"] = workflow_command

        request["max_sources"] = min(request["max_sources"], self.defaults["limits"]["max_sources"])
        request["max_subtasks"] = min(request["max_subtasks"], self.defaults["limits"]["max_subtasks"])
        request["max_competitors"] = min(request["max_competitors"], self.defaults["limits"]["max_competitors"])
        request["review_sample_target"] = min(request["review_sample_target"], self.defaults["limits"]["review_sample_target"])
        request["time_budget_minutes"] = min(request["time_budget_minutes"], self.defaults["limits"]["time_budget_minutes"])

        phases = build_phase_progress()
        retrieval_profile_id = self._resolve_retrieval_profile_id(request)
        quality_policy = runtime_config.get("quality_policy") or {}
        return {
            "id": request["job_id"],
            "topic": request["topic"],
            "industry_template": request["industry_template"],
            "research_mode": request["research_mode"],
            "depth_preset": request["depth_preset"],
            "failure_policy": str(request.get("failure_policy") or "graceful"),
            "completion_mode": "formal",
            "workflow_command": workflow_command,
            "workflow_label": str(preset.get("label") or workflow_command).strip(),
            "project_memory": str(request.get("project_memory") or "").strip(),
            "orchestration_summary": str(preset.get("summary") or "").strip(),
            "status": "queued",
            "current_phase": "scoping",
            "overall_progress": 0.0,
            "eta_seconds": request["time_budget_minutes"] * 60,
            "source_count": 0,
            "competitor_count": 0,
            "completed_task_count": 0,
            "running_task_count": 0,
            "failed_task_count": 0,
            "claims_count": 0,
            "report_version_id": None,
            "phase_progress": phases,
            "tasks": [],
            "activity_log": [],
            "latest_error": None,
            "latest_warning": None,
            "cancel_requested": False,
            "cancellation_reason": None,
            "execution_mode": None,
            "background_process": None,
            "max_sources": request["max_sources"],
            "max_subtasks": request["max_subtasks"],
            "max_competitors": request["max_competitors"],
            "review_sample_target": request["review_sample_target"],
            "time_budget_minutes": request["time_budget_minutes"],
            "geo_scope": request.get("geo_scope", []),
            "language": request.get("language", "zh-CN"),
            "output_locale": request.get("output_locale", "zh-CN"),
            "runtime_config": runtime_config or None,
            "runtime_summary": self._build_runtime_summary(),
            "active_report_version_id": None,
            "stable_report_version_id": None,
            "retrieval_profile_id": retrieval_profile_id,
            "quality_score_summary": {
                "profile_id": str(runtime_config.get("profile_id") or "").strip() or None,
                "retrieval_profile_id": retrieval_profile_id,
                "quality_policy_id": str(quality_policy.get("profile_id") or "").strip() or None,
            },
            "created_at": iso_now(),
        }

    def _decorate_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task.setdefault("progress", 0)
        task_label = market_step_label(str(task.get("market_step") or task.get("category") or ""))
        task.setdefault("agent_name", f"研究执行体 · {task_label}")
        task.setdefault("command_id", "deep_general_scan")
        task.setdefault("command_label", "全景深度扫描")
        task.setdefault("skill_packs", [])
        task.setdefault("orchestration_notes", "")
        task.setdefault("current_action", "等待开始")
        task.setdefault("current_url", None)
        task.setdefault("browser_mode", self.browser.mode())
        task.setdefault("browser_available", self.browser.is_available())
        task.setdefault("search_queries", [])
        task.setdefault("visited_sources", [])
        task.setdefault("logs", [])
        return task

    def _append_task_log(self, job: Dict[str, Any], task: Dict[str, Any], message: str, level: str = "info") -> None:
        log = build_task_log(message, level=level)
        task.setdefault("logs", []).append(log)
        job.setdefault("activity_log", []).append(log)
        job["activity_log"] = job["activity_log"][-40:]

    def _mark_job_failed(self, job: Dict[str, Any], message: str) -> None:
        job["status"] = "failed"
        job["completion_mode"] = "diagnostic"
        job["latest_error"] = message
        job["latest_warning"] = None
        job["eta_seconds"] = 0
        job["running_task_count"] = 0
        job["runtime_summary"] = self._build_runtime_summary()
        job["completed_at"] = iso_now()
        job.setdefault("activity_log", []).append(build_task_log(message, level="error"))
        job["activity_log"] = job["activity_log"][-40:]
        recompute_overall_progress(job)

    def _mark_job_cancelled(self, job: Dict[str, Any], message: str) -> None:
        job["status"] = "cancelled"
        job["cancel_requested"] = True
        job["cancellation_reason"] = message
        job["latest_warning"] = None
        job["eta_seconds"] = 0
        job["running_task_count"] = 0
        job["runtime_summary"] = self._build_runtime_summary()
        job["completed_at"] = iso_now()
        for task in job.get("tasks", []):
            if task.get("status") in {"queued", "running"}:
                task["status"] = "cancelled"
                task["current_action"] = "已取消"
        job.setdefault("activity_log", []).append(build_task_log(message, level="warning"))
        job["activity_log"] = job["activity_log"][-40:]
        recompute_overall_progress(job)

    def _attach_failure_draft_report(
        self,
        job: Dict[str, Any],
        request: Dict[str, Any],
        assets: Dict[str, Any],
        competitor_names: List[str],
        report_context_source: str,
    ) -> None:
        report = self.synthesizer.build_report(request, assets.get("claims", []), assets.get("evidence", []), competitor_names)
        attach_report_support_snapshot(
            report,
            claims=assets.get("claims", []),
            evidence=assets.get("evidence", []),
            prefer_claim_evidence=False,
        )
        assets["report"] = report
        assets["market_map"] = {
            **(assets.get("market_map") or {}),
            "topic": request["topic"],
            "focus_areas": request.get("geo_scope", []),
            "browser_mode": self.browser.mode() if self.browser.is_available() else "static-fetch-degraded",
            "report_stage": report.get("stage", "draft"),
            "report_context_source": report_context_source,
        }
        if not job.get("report_version_id") and str(report.get("markdown") or "").strip():
            job["report_version_id"] = f"{job['id']}-report-v1"
        if job.get("report_version_id"):
            job["active_report_version_id"] = job.get("report_version_id")
            job["stable_report_version_id"] = None
            job["quality_score_summary"] = {
                "report_readiness": "draft",
                "formal_claim_count": 0,
                "formal_evidence_count": 0,
                "formal_domain_count": 0,
                "requires_finalize": True,
                "retrieval_profile_id": job.get("retrieval_profile_id"),
            }
        report_snapshot = build_report_version_snapshot(
            job.get("report_version_id"),
            report,
            claims=assets.get("claims", []),
            evidence=assets.get("evidence", []),
            prefer_claim_evidence=False,
            metadata={
                "kind": "draft",
                "parent_version_id": None,
                "change_reason": report_context_source,
            },
        )
        assets["report_versions"] = []
        if report_snapshot:
            append_report_version_snapshot_to_assets(assets, report_snapshot)

    def _build_progress_snapshot(self, job: Dict[str, Any], assets: Dict[str, Any], competitor_names: List[str]) -> Dict[str, Any]:
        source_mix: Dict[str, int] = {}
        for item in assets["evidence"]:
            source_mix[item["source_type"]] = source_mix.get(item["source_type"], 0) + 1
        competitor_coverage = []
        competitor_assets = [item for item in (assets.get("competitors") or []) if isinstance(item, dict)]
        coverage_names = competitor_names[: min(6, len(competitor_names))]
        if not coverage_names:
            coverage_names = [
                str(item.get("name") or "").strip()
                for item in competitor_assets[:6]
                if str(item.get("name") or "").strip()
            ]
        for name in coverage_names:
            asset_match = next((item for item in competitor_assets if str(item.get("name") or "").strip() == name), None)
            count = int(asset_match.get("evidence_count") or 0) if asset_match else sum(
                1 for item in assets["evidence"] if item.get("competitor_name") == name
            )
            competitor_coverage.append({"name": name, "value": count})
        return {
            "source_growth": [
                {"label": "规划", "value": min(len(job["tasks"]), max(1, job["completed_task_count"]))},
                {"label": "采集", "value": job["source_count"]},
                {"label": "校验", "value": job["claims_count"]},
                {"label": "成文", "value": len(assets["report"].get("markdown", "")) // 200 if assets["report"].get("markdown") else 0},
            ],
            "source_mix": [{"name": name, "value": value} for name, value in sorted(source_mix.items())] or [{"name": "web", "value": 0}],
            "competitor_coverage": competitor_coverage,
        }

    def _cancellation_snapshot(
        self,
        check_cancelled: Optional[Callable[[], Optional[str]]],
    ) -> Optional[str]:
        if not check_cancelled:
            return None
        reason = str(check_cancelled() or "").strip()
        return reason or None

    def _cancellation_reason(self, cancellation_snapshot: Optional[str]) -> str:
        return str(cancellation_snapshot or "").strip() or "研究任务已取消。"

    def _apply_cancelled_state(self, job: Dict[str, Any], cancellation_snapshot: Optional[str]) -> None:
        reason = self._cancellation_reason(cancellation_snapshot)
        job["status"] = "cancelled"
        job["cancel_requested"] = True
        job["cancellation_reason"] = reason
        job["latest_error"] = None
        job["latest_warning"] = None
        job["eta_seconds"] = 0
        job["running_task_count"] = 0
        job["runtime_summary"] = self._build_runtime_summary()
        job["completed_at"] = iso_now()
        for task in job.get("tasks", []):
            if task.get("status") in {"queued", "running"}:
                task["status"] = "cancelled"
                task["current_action"] = "已取消"
                task["latest_error"] = None
        recompute_overall_progress(job)

    def _build_no_evidence_failure_message(self, job: Dict[str, Any]) -> str:
        query_summaries = [
            summary
            for task in job.get("tasks", [])
            for round_record in (task.get("research_rounds") or [])
            if isinstance(round_record, dict)
            for summary in (round_record.get("query_summaries") or [])
            if isinstance(summary, dict)
        ]
        task_errors = [
            str(task.get("latest_error") or "").strip()
            for task in job.get("tasks", [])
            if str(task.get("latest_error") or "").strip()
        ]
        visited_source_count = sum(len(task.get("visited_sources") or []) for task in job.get("tasks", []))
        search_error_count = sum(1 for summary in query_summaries if str(summary.get("status") or "").strip() == "search_error")
        zero_result_count = sum(1 for summary in query_summaries if str(summary.get("status") or "").strip() == "zero_results")
        filtered_count = sum(1 for summary in query_summaries if str(summary.get("status") or "").strip() == "filtered")
        query_hit_count = sum(1 for summary in query_summaries if int(summary.get("search_result_count", 0) or 0) > 0)
        if task_errors:
            unique_errors: List[str] = []
            for error in task_errors:
                if error not in unique_errors:
                    unique_errors.append(error)
            blocked_error = next(
                (
                    error
                    for error in unique_errors
                    if any(token in error.lower() for token in (" 401 ", " 403 ", " 429 ", " 451 ", "unauthorized", "forbidden", "too many requests"))
                    or any(token in error for token in ("401", "403", "429", "451", "Unauthorized", "Forbidden", "限制访问", "频率限制"))
                ),
                None,
            )
            if blocked_error and visited_source_count > 0:
                blocked_reason = "部分来源限制访问"
                if "429" in blocked_error or "too many requests" in blocked_error.lower():
                    blocked_reason = "部分来源触发访问频率限制"
                return f"这轮研究已自动跳过{blocked_reason}，并保留了可复核线索，但暂时还不够支撑正式结论。系统已保留研究快照；建议补充更具体的产品名、地区或官网域名后继续。"
            return (
                "这轮研究已经完成搜索与抓取，但暂时还没有积累到足够稳定的外部证据。"
                "期间有少量来源获取不稳定，系统已保留研究快照供继续补搜和人工复核。"
            )
        if search_error_count > 0 and query_hit_count == 0 and visited_source_count == 0:
            return (
                "这轮研究在搜索阶段遇到较多连接异常，系统已跳过不稳定来源并保留研究快照。"
                "建议稍后重试，或补充更具体的官网域名、英文产品名后继续。"
            )
        if filtered_count > 0 and query_hit_count > 0 and visited_source_count == 0:
            return (
                "这轮研究已经命中过候选页面，但当前结果相关性或可引用性还不够稳定。"
                "系统已保留研究快照；建议补充更具体的产品名、地区或竞品锚点后继续。"
            )
        if zero_result_count > 0 and query_hit_count == 0 and visited_source_count == 0:
            return (
                "这轮研究已经尝试过多组关键词，但暂时还没有命中足够相关的公开结果。"
                "系统已先保留研究快照；建议补充更具体的产品名、地区或官网域名后继续。"
            )
        if visited_source_count > 0:
            return "这轮研究已经完成搜索与抓取，但暂时还不够支撑正式结论。系统已保留研究快照；请补充更具体的产品名、地区或竞品锚点后继续。"
        return "这轮研究还没有拿到足够稳定的外部证据，系统已先保留研究快照；请补充更具体的产品名、地区或竞品锚点后继续。"

    def _uses_strict_failure_policy(self, payload: Dict[str, Any]) -> bool:
        return str(payload.get("failure_policy") or "graceful").strip().lower() == "strict"

    def _mark_job_completed_with_warning(self, job: Dict[str, Any], message: str) -> None:
        job["status"] = "completed"
        job["completion_mode"] = "diagnostic"
        job["latest_error"] = None
        job["latest_warning"] = message
        job["current_phase"] = "finalizing"
        job["overall_progress"] = 100
        job["eta_seconds"] = 0
        job["running_task_count"] = 0
        job["runtime_summary"] = self._build_runtime_summary()
        job["completed_at"] = iso_now()
        set_phase_progress(job, "scoping", 100, "completed")
        set_phase_progress(job, "planning", 100, "completed")
        set_phase_progress(job, "collecting", 100, "completed")
        set_phase_progress(job, "verifying", 100, "completed")
        set_phase_progress(job, "synthesizing", 100, "completed")
        set_phase_progress(job, "finalizing", 100, "completed")
        job.setdefault("activity_log", []).append(build_task_log(message, level="warning"))
        job["activity_log"] = job["activity_log"][-40:]
        recompute_overall_progress(job)

    async def run_delta_research(
        self,
        request: Dict[str, Any],
        user_message: str,
        delta_job_id: str,
        competitor_names: Optional[List[str]] = None,
    ) -> DeltaResearchResult:
        competitor_names = competitor_names or []
        delta_request = {
            **deepcopy(request),
            "job_id": delta_job_id,
            "max_sources": max(3, min(6, int(request.get("max_sources", 6) or 6))),
            "max_subtasks": 1,
            "max_competitors": max(3, min(6, int(request.get("max_competitors", 4) or 4))),
            "time_budget_minutes": max(5, min(15, int(request.get("time_budget_minutes", 10) or 10))),
        }
        delta_task = self._decorate_task(self.research_worker.build_delta_task(delta_request, user_message, delta_job_id))
        self._append_task_log({"activity_log": []}, delta_task, "已进入追问补充研究。")
        timeout_seconds = min(
            self.DELTA_RESEARCH_TIMEOUT_SECONDS,
            max(6.0, float(delta_request.get("time_budget_minutes", 10) or 10) * 1.2),
        )
        try:
            delta_evidence = await asyncio.wait_for(
                self.research_worker.collect_evidence(delta_request, delta_task, competitor_names, self.browser),
                timeout=timeout_seconds,
            )
        except (asyncio.TimeoutError, TimeoutError):
            return self.dialogue.run_delta_research(request.get("job_id", delta_job_id), user_message, delta_job_id)
        if not delta_evidence:
            return self.dialogue.run_delta_research(request.get("job_id", delta_job_id), user_message, delta_job_id)

        claim = self.verifier.build_delta_claim(
            request=delta_request,
            question=user_message,
            market_step=delta_task["market_step"],
            evidence=delta_evidence,
            claim_id=f"{delta_job_id}-claim-1",
        )
        follow_up_message = self.dialogue.build_delta_follow_up(user_message, claim, delta_evidence)
        return DeltaResearchResult(
            delta_job_id=delta_job_id,
            claim=claim,
            evidence=delta_evidence,
            follow_up_message=follow_up_message,
        )

    async def run_research(
        self,
        job: Dict[str, Any],
        request: Dict[str, Any],
        publish,
        check_cancelled: Optional[Callable[[], Optional[str]]] = None,
    ) -> Dict[str, Any]:
        assets = build_empty_assets()
        competitor_names: List[str] = []

        cancellation_snapshot = self._cancellation_snapshot(check_cancelled)
        if cancellation_snapshot:
            self._apply_cancelled_state(job, cancellation_snapshot)
            assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
            return assets

        set_phase_progress(job, "scoping", 100, "completed")
        recompute_overall_progress(job)
        await publish("job.progress", {"job": deepcopy(job), "message": "研究边界已确认。"})

        cancellation_snapshot = self._cancellation_snapshot(check_cancelled)
        if cancellation_snapshot:
            self._apply_cancelled_state(job, cancellation_snapshot)
            assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
            return assets

        job["status"] = "planning"
        job["current_phase"] = "planning"
        set_phase_progress(job, "planning", 30, "running")
        recompute_overall_progress(job)
        await publish("job.progress", {"job": deepcopy(job), "message": "正在拆分研究子任务。"})
        await asyncio.sleep(0.05)

        request["job_id"] = job["id"]
        cancellation_snapshot = self._cancellation_snapshot(check_cancelled)
        if cancellation_snapshot:
            self._apply_cancelled_state(job, cancellation_snapshot)
            assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
            return assets
        planned_tasks = self.planner.build_tasks(request)
        job["tasks"] = [
            self._decorate_task(
                {
                    **task,
                    "agent_name": f"子研究体 {index + 1} · {task['title']}",
                    "agent_role": "sub-agent",
                    "sub_agent_id": f"{job['id']}-sub-agent-{index + 1}",
                    "sub_agent_index": index + 1,
                }
            )
            for index, task in enumerate(planned_tasks)
        ]
        if not job["tasks"]:
            failure_message = "研究规划未生成可执行的子任务，任务已停止。"
            if self._uses_strict_failure_policy(request):
                self._mark_job_failed(job, failure_message)
                assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
                await publish("job.failed", {"job": deepcopy(job), "message": failure_message, "assets": deepcopy(assets)})
            else:
                self._attach_failure_draft_report(
                    job,
                    request,
                    assets,
                    competitor_names,
                    report_context_source="planning-diagnostic-draft",
                )
                self._mark_job_completed_with_warning(job, "未生成可执行子任务，系统已输出诊断草稿并结束本次研究。")
                assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
                await publish("job.progress", {"job": deepcopy(job), "message": job["latest_warning"], "assets": deepcopy(assets)})
            return assets

        set_phase_progress(job, "planning", 100, "completed")
        job["status"] = "researching"
        job["current_phase"] = "collecting"
        set_phase_progress(job, "collecting", 0, "running")
        recompute_overall_progress(job)
        assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
        await publish(
            "job.progress",
            {
                "job": deepcopy(job),
                "message": f"研究任务规划完成，准备启动 {len(job['tasks'])} 个子 Agent。",
                "assets": deepcopy(assets),
            },
        )

        cancellation_snapshot = self._cancellation_snapshot(check_cancelled)
        if cancellation_snapshot:
            self._apply_cancelled_state(job, cancellation_snapshot)
            assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
            return assets

        publish_lock = asyncio.Lock()
        parallel_workers = max(1, min(len(job["tasks"]), int(request.get("max_subtasks", len(job["tasks"])) or len(job["tasks"])), 4))
        semaphore = asyncio.Semaphore(parallel_workers)

        async def publish_snapshot(event_name: str, task: Optional[Dict[str, Any]] = None, message: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> None:
            payload: Dict[str, Any] = {
                "job_id": job["id"],
                "job": deepcopy(job),
                "assets": deepcopy(assets),
            }
            if task is not None:
                payload["task"] = deepcopy(task)
            if message:
                payload["message"] = message
            if extra:
                payload.update(extra)
            await publish(event_name, payload)

        def sync_task_evidence_snapshot(task_id: str, task_evidence: List[Dict[str, Any]]) -> None:
            normalized_task_id = str(task_id or "").strip()
            retained_evidence = [
                item
                for item in (assets.get("evidence") or [])
                if isinstance(item, dict) and str(item.get("task_id") or "").strip() != normalized_task_id
            ]
            retained_evidence.extend(item for item in task_evidence if isinstance(item, dict))
            assets["evidence"] = retained_evidence

        def refresh_live_competitor_names() -> None:
            nonlocal competitor_names
            merged: List[str] = []
            seen = set()
            candidate_groups = [
                competitor_names,
                [item.get("name") for item in (assets.get("competitors") or []) if isinstance(item, dict)],
                [item.get("competitor_name") for item in (assets.get("evidence") or []) if isinstance(item, dict)],
                [
                    name
                    for task_item in job.get("tasks", [])
                    if isinstance(task_item, dict)
                    for name in (task_item.get("known_competitor_names") or [])
                ],
            ]
            for group in candidate_groups:
                for raw_name in group or []:
                    cleaned = str(raw_name or "").strip()
                    if not cleaned or cleaned in seen:
                        continue
                    merged.append(cleaned)
                    seen.add(cleaned)
                    if len(merged) >= 8:
                        competitor_names = merged
                        return
            competitor_names = merged

        async def run_task_sub_agent(task: Dict[str, Any]) -> None:
            async with semaphore:
                cancellation_snapshot = self._cancellation_snapshot(check_cancelled)
                if cancellation_snapshot:
                    async with publish_lock:
                        task["status"] = "cancelled"
                        task["current_action"] = "已取消"
                        job["running_task_count"] = sum(1 for item in job["tasks"] if item["status"] == "running")
                        assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
                    return

                async with publish_lock:
                    task["status"] = "running"
                    task["current_action"] = "开始执行搜索与抓取"
                    self._append_task_log(job, task, f"{task['agent_name']} 已启动。")
                    job["running_task_count"] = sum(1 for item in job["tasks"] if item["status"] == "running")
                    assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
                    await publish_snapshot("task.started", task=task, message=f"{task['agent_name']} 已接管该调研步骤。")

                async def on_task_progress(updated_task: Dict[str, Any], message: str) -> None:
                    if self._cancellation_snapshot(check_cancelled):
                        return
                    async with publish_lock:
                        partial_evidence = updated_task.pop("partial_evidence", None)
                        if isinstance(partial_evidence, list):
                            sync_task_evidence_snapshot(str(updated_task.get("id") or ""), partial_evidence)
                            refresh_live_competitor_names()
                        self._append_task_log(job, updated_task, message)
                        job["source_count"] = max(
                            len(assets.get("evidence") or []),
                            sum(int(item.get("source_count") or 0) for item in job["tasks"]),
                        )
                        update_collecting_progress(job)
                        assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
                        await publish_snapshot("task.progress", task=updated_task, message=message)

                try:
                    task_evidence = await self.research_worker.collect_evidence(
                        request,
                        task,
                        competitor_names,
                        self.browser,
                        on_task_progress,
                        cancel_probe=lambda: self._cancellation_reason(self._cancellation_snapshot(check_cancelled))
                        if self._cancellation_snapshot(check_cancelled)
                        else None,
                    )
                except JobCancelledError as error:
                    async with publish_lock:
                        partial_evidence = list(error.partial_evidence or [])
                        task["status"] = "cancelled"
                        task["source_count"] = len(partial_evidence)
                        task["current_action"] = "已取消"
                        if partial_evidence:
                            sync_task_evidence_snapshot(task["id"], partial_evidence)
                            refresh_live_competitor_names()
                            job["source_count"] = len(assets["evidence"])
                        job["running_task_count"] = sum(1 for item in job["tasks"] if item["status"] == "running")
                        assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
                    return
                except Exception as error:
                    async with publish_lock:
                        task["status"] = "failed"
                        task["latest_error"] = str(error)
                        task["current_action"] = "执行失败"
                        self._append_task_log(job, task, f"{task['agent_name']} 执行失败：{error}", level="error")
                        job["running_task_count"] = sum(1 for item in job["tasks"] if item["status"] == "running")
                        job["failed_task_count"] = sum(1 for item in job["tasks"] if item["status"] == "failed")
                        update_collecting_progress(job)
                        assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
                        await publish_snapshot("task.failed", task=task, message=f"{task['agent_name']} 执行失败。")
                    return

                cancellation_snapshot = self._cancellation_snapshot(check_cancelled)
                if cancellation_snapshot:
                    async with publish_lock:
                        task["status"] = "cancelled"
                        task["current_action"] = "已取消"
                        job["running_task_count"] = sum(1 for item in job["tasks"] if item["status"] == "running")
                        assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
                    return

                async with publish_lock:
                    task["status"] = "completed"
                    task["source_count"] = len(task_evidence)
                    task["current_action"] = "已完成"
                    sync_task_evidence_snapshot(task["id"], task_evidence)
                    refresh_live_competitor_names()
                    job["source_count"] = len(assets["evidence"])
                    job["running_task_count"] = sum(1 for item in job["tasks"] if item["status"] == "running")
                    job["completed_task_count"] = sum(1 for item in job["tasks"] if item["status"] == "completed")
                    job["failed_task_count"] = sum(1 for item in job["tasks"] if item["status"] == "failed")
                    update_collecting_progress(job)
                    assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
                    await publish_snapshot("task.completed", task=task, message=f"{task['agent_name']} 已完成该步骤。")

        await asyncio.gather(*(run_task_sub_agent(task) for task in job["tasks"]))

        cancellation_snapshot = self._cancellation_snapshot(check_cancelled)
        if cancellation_snapshot:
            self._apply_cancelled_state(job, cancellation_snapshot)
            assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
            return assets

        if not assets["evidence"]:
            completion_message = (
                "这一轮还没有沉淀出可复用的外部证据，系统已保留研究快照，方便继续补搜或人工复核。"
                if job["failed_task_count"] >= len(job["tasks"])
                else self._build_no_evidence_failure_message(job)
            )
            self._attach_failure_draft_report(
                job,
                request,
                assets,
                competitor_names,
                report_context_source="no-evidence-diagnostic-draft",
            )
            if self._uses_strict_failure_policy(request):
                self._mark_job_failed(job, completion_message)
                terminal_event = "job.failed"
            else:
                self._mark_job_completed_with_warning(job, completion_message)
                terminal_event = "job.progress"
            assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
            await publish(terminal_event, {"job": deepcopy(job), "message": completion_message, "assets": deepcopy(assets)})
            return assets

        set_phase_progress(job, "collecting", 100, "completed")
        job["current_phase"] = "verifying"
        job["status"] = "verifying"
        set_phase_progress(job, "verifying", 30, "running")
        recompute_overall_progress(job)
        await publish("job.progress", {"job": deepcopy(job), "message": "正在校验来源和生成 claims。"})
        await asyncio.sleep(0.05)

        cancellation_snapshot = self._cancellation_snapshot(check_cancelled)
        if cancellation_snapshot:
            self._apply_cancelled_state(job, cancellation_snapshot)
            assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
            return assets

        assets["claims"] = self.verifier.build_claims(request, assets["evidence"])
        assets["competitors"] = self.synthesizer.extract_competitors(request, assets["evidence"])
        competitor_names = [item["name"] for item in assets["competitors"]]
        job["claims_count"] = len(assets["claims"])
        assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
        set_phase_progress(job, "verifying", 100, "completed")
        job["current_phase"] = "synthesizing"
        job["status"] = "synthesizing"
        set_phase_progress(job, "synthesizing", 50, "running")
        recompute_overall_progress(job)
        await publish("claim.generated", {"job_id": job["id"], "claims_count": job["claims_count"], "job": deepcopy(job), "assets": deepcopy(assets)})
        await asyncio.sleep(0.05)

        cancellation_snapshot = self._cancellation_snapshot(check_cancelled)
        if cancellation_snapshot:
            self._apply_cancelled_state(job, cancellation_snapshot)
            assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)
            return assets

        assets["report"] = self.synthesizer.build_report(request, assets["claims"], assets["evidence"], competitor_names)
        attach_report_support_snapshot(
            assets["report"],
            claims=assets["claims"],
            evidence=assets["evidence"],
            prefer_claim_evidence=False,
        )
        assets["market_map"] = {
            "topic": request["topic"],
            "focus_areas": request["geo_scope"],
            "browser_mode": self.browser.mode() if self.browser.is_available() else "static-fetch-degraded",
            "report_stage": assets["report"].get("stage", "draft"),
        }
        assets["progress_snapshot"] = self._build_progress_snapshot(job, assets, competitor_names)

        set_phase_progress(job, "synthesizing", 100, "completed")
        job["current_phase"] = "finalizing"
        set_phase_progress(job, "finalizing", 100, "completed")
        job["status"] = "completed"
        job["completion_mode"] = "formal"
        job["overall_progress"] = 100
        job["eta_seconds"] = 0
        job["competitor_count"] = len(competitor_names)
        job["report_version_id"] = f"{job['id']}-report-v1"
        job["active_report_version_id"] = job["report_version_id"]
        job["stable_report_version_id"] = None
        job["runtime_summary"] = self._build_runtime_summary()
        job["completed_at"] = iso_now()
        job["latest_error"] = None
        job["latest_warning"] = None
        job["quality_score_summary"] = {
            "report_readiness": "draft",
            "formal_claim_count": 0,
            "formal_evidence_count": len(assets["evidence"]),
            "formal_domain_count": len({str(item.get("source_domain") or "").strip() for item in assets["evidence"] if str(item.get("source_domain") or "").strip()}),
            "requires_finalize": True,
            "retrieval_profile_id": job.get("retrieval_profile_id"),
        }
        initial_report_snapshot = build_report_version_snapshot(
            job["report_version_id"],
            assets["report"],
            claims=assets["claims"],
            evidence=assets["evidence"],
            prefer_claim_evidence=False,
            metadata={
                "kind": "draft",
                "parent_version_id": None,
                "change_reason": "initial_research_completed",
            },
        )
        assets["report_versions"] = []
        if initial_report_snapshot:
            append_report_version_snapshot_to_assets(assets, initial_report_snapshot)

        await publish(
            "report.section.completed",
            {
                "job_id": job["id"],
                "job": deepcopy(job),
                "section_count": int(assets["report"].get("section_count", 0) or 0),
                "assets": deepcopy(assets),
            },
        )
        return assets
