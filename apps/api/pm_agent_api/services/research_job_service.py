import asyncio
import difflib
import json
import logging
import os
import subprocess
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from queue import Empty
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pm_agent_api.repositories.base import StateRepositoryProtocol
from pm_agent_api.runtime.repo_bootstrap import ensure_repo_paths
from pm_agent_api.services.job_service_utils import (
    append_report_version_snapshot_to_assets,
    build_report_version_diff_summary,
    build_request_from_job,
    find_report_version_snapshot,
    is_context_only_evidence,
    next_report_version_id,
)

ensure_repo_paths()

from pm_agent_worker.agents.research_worker_agent import ResearchWorkerAgent
from pm_agent_worker.agents.synthesizer_agent import SynthesizerAgent
from pm_agent_worker.tools.llm_runtime import infer_provider_from_settings, load_llm_settings
from pm_agent_worker.tools.opencli_browser_tool import OpenCliBrowserTool
from pm_agent_worker.tools.runtime_profiles import hydrate_runtime_config, merge_runtime_configs
from pm_agent_worker.workflows.control import JobCancelledError
from pm_agent_worker.workflows.research_models import (
    attach_report_support_snapshot,
    build_empty_assets,
    build_report_version_snapshot,
    build_task_log,
    iso_now,
    report_version_sort_key,
)
from pm_agent_worker.workflows.research_workflow import ResearchWorkflowEngine


LOGGER = logging.getLogger(__name__)


class ResearchJobService:
    ACTIVE_JOB_STATUSES = {"queued", "planning", "researching", "verifying", "synthesizing"}
    FINALIZE_QUALITY_GATE_POLICY_VERSION = "2026-04-11.finalize-gate.v2"
    MIN_FORMAL_EVIDENCE_COUNT = 2
    MIN_FORMAL_DOMAIN_COUNT = 2
    MIN_FORMAL_CLAIM_COUNT = 1

    def __init__(self, repository: StateRepositoryProtocol, background_mode: str = "subprocess") -> None:
        self.repository = repository
        self.browser = OpenCliBrowserTool()
        self.background_mode = background_mode

    def _build_workflow(self, runtime_config: Optional[Dict[str, Any]] = None) -> ResearchWorkflowEngine:
        return ResearchWorkflowEngine(runtime_config=runtime_config)

    def _per_task_source_target(self, job: Dict[str, Any]) -> int:
        max_sources = max(1, int(job.get("max_sources", 12) or 12))
        task_count = max(1, len(job.get("tasks") or []))
        max_subtasks = max(1, int(job.get("max_subtasks", task_count) or task_count))
        return max(3, min(12, max_sources // max_subtasks))

    def _reconcile_task_coverage_status(self, job: Dict[str, Any], assets: Dict[str, Any]) -> Dict[str, Any]:
        tasks = job.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            return job

        evidence_by_task: Dict[str, List[Dict[str, Any]]] = {}
        for item in assets.get("evidence") or []:
            if not isinstance(item, dict):
                continue
            task_id = str(item.get("task_id") or "").strip()
            if not task_id:
                continue
            evidence_by_task.setdefault(task_id, []).append(item)

        if not evidence_by_task:
            return job

        worker = ResearchWorkerAgent()
        target_sources = self._per_task_source_target(job)
        changed = False
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_evidence = evidence_by_task.get(str(task.get("id") or "").strip(), [])
            if not task_evidence:
                continue
            refreshed_coverage = worker.build_task_coverage_status(task, task_evidence, target_sources)
            if task.get("coverage_status") != refreshed_coverage:
                task["coverage_status"] = refreshed_coverage
                changed = True

        if changed:
            self.repository.update_job(job["id"], job)
            return self.repository.get_job(job["id"]) or job
        return job

    def _resolve_runtime_config(self, runtime_config: Optional[Dict[str, Any]], owner_user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        saved_runtime = self.repository.get_runtime_config(owner_user_id) or {}
        runtime_config = runtime_config or {}
        if saved_runtime or runtime_config:
            return merge_runtime_configs(saved_runtime, runtime_config)

        env_settings = load_llm_settings()
        env_runtime_config: Dict[str, Any] = {
            "provider": infer_provider_from_settings(env_settings),
            "base_url": getattr(env_settings, "base_url", ""),
            "model": getattr(env_settings, "model", ""),
            "timeout_seconds": getattr(env_settings, "timeout_seconds", None),
        }
        api_key = str(getattr(env_settings, "api_key", "") or "").strip()
        if api_key:
            env_runtime_config["api_key"] = api_key
        return hydrate_runtime_config(env_runtime_config)

    def _job_is_active(self, status: Optional[str]) -> bool:
        return str(status or "").strip() in self.ACTIVE_JOB_STATUSES

    def _default_cancellation_reason(self) -> str:
        return "研究任务已被手动取消，系统会保留当前已收集的证据和草稿。"

    def _cancel_reason_from_job(self, job: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(job, dict):
            return None
        if job.get("status") != "cancelled" and not job.get("cancel_requested"):
            return None
        reason = str(job.get("cancellation_reason") or "").strip()
        return reason or self._default_cancellation_reason()

    def _raise_if_job_cancelled(self, job_id: str) -> None:
        reason = self._cancel_reason_from_job(self.repository.get_job(job_id))
        if reason:
            raise JobCancelledError(reason)

    def _build_conversation_excerpt(self, research_job_id: str, limit: int = 12) -> List[Dict[str, str]]:
        session = self.repository.get_latest_chat_session_for_job(research_job_id) or {}
        excerpt: List[Dict[str, str]] = []
        for message in (session.get("messages") or [])[-limit:]:
            role = message.get("role")
            content = str(message.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                excerpt.append({"role": role, "content": content})
        return excerpt

    def _append_report_version_snapshot(
        self,
        assets: Dict[str, Any],
        version_id: Optional[str],
        report: Optional[Dict[str, Any]],
        claims: Optional[List[Dict[str, Any]]] = None,
        evidence: Optional[List[Dict[str, Any]]] = None,
        prefer_claim_evidence: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        snapshot = build_report_version_snapshot(
            version_id,
            report,
            claims=claims,
            evidence=evidence,
            prefer_claim_evidence=prefer_claim_evidence,
            metadata=metadata,
        )
        if snapshot:
            append_report_version_snapshot_to_assets(assets, snapshot)
        return snapshot

    def _active_report_version_id(self, job: Dict[str, Any]) -> Optional[str]:
        return str(job.get("active_report_version_id") or job.get("report_version_id") or "").strip() or None

    def _stable_report_version_id(self, job: Dict[str, Any]) -> Optional[str]:
        return str(job.get("stable_report_version_id") or "").strip() or None

    def _set_report_version_pointers(
        self,
        job: Dict[str, Any],
        *,
        active_version_id: Optional[str],
        stable_version_id: Optional[str],
    ) -> None:
        job["active_report_version_id"] = active_version_id
        job["stable_report_version_id"] = stable_version_id
        job["report_version_id"] = active_version_id

    def _update_quality_score_summary(
        self,
        job: Dict[str, Any],
        *,
        readiness: str,
        quality_gate: Optional[Dict[str, Any]] = None,
        formal_claim_count: int = 0,
        formal_evidence_count: int = 0,
        formal_domain_count: int = 0,
        requires_finalize: bool = False,
    ) -> None:
        report_quality_score = None
        if isinstance(quality_gate, dict):
            metrics = quality_gate.get("metrics") or {}
            thresholds = quality_gate.get("thresholds") or {}
            evidence_target = max(1, int(thresholds.get("min_formal_evidence_count", self.MIN_FORMAL_EVIDENCE_COUNT) or self.MIN_FORMAL_EVIDENCE_COUNT))
            domain_target = max(1, int(thresholds.get("min_formal_domain_count", self.MIN_FORMAL_DOMAIN_COUNT) or self.MIN_FORMAL_DOMAIN_COUNT))
            claim_target = max(1, int(thresholds.get("min_formal_claim_count", self.MIN_FORMAL_CLAIM_COUNT) or self.MIN_FORMAL_CLAIM_COUNT))
            evidence_score = min(1.0, float(metrics.get("formal_evidence_count", formal_evidence_count) or formal_evidence_count) / evidence_target)
            domain_score = min(1.0, float(metrics.get("formal_domain_count", formal_domain_count) or formal_domain_count) / domain_target)
            claim_score = min(1.0, float(metrics.get("formal_claim_count", formal_claim_count) or formal_claim_count) / claim_target)
            report_quality_score = round(((evidence_score + domain_score + claim_score) / 3.0) * 100, 1)
        job["quality_score_summary"] = {
            "report_readiness": readiness,
            "report_quality_score": report_quality_score,
            "formal_claim_count": formal_claim_count,
            "formal_evidence_count": formal_evidence_count,
            "formal_domain_count": formal_domain_count,
            "requires_finalize": requires_finalize,
        }

    def _normalize_job_response(self, job: Dict[str, Any]) -> Dict[str, Any]:
        normalized = deepcopy(job)
        normalized["quality_score_summary"] = normalized.get("quality_score_summary") or {}
        normalized["phase_progress"] = list(normalized.get("phase_progress") or [])
        normalized["tasks"] = list(normalized.get("tasks") or [])
        normalized["activity_log"] = list(normalized.get("activity_log") or [])
        return normalized

    def _refresh_competitor_progress_snapshot(self, assets: Dict[str, Any], competitor_names: List[str]) -> Dict[str, Any]:
        snapshot = deepcopy(assets.get("progress_snapshot") or {})
        competitor_assets = [item for item in (assets.get("competitors") or []) if isinstance(item, dict)]
        competitor_coverage = []
        for name in competitor_names[:6]:
            asset_match = next((item for item in competitor_assets if str(item.get("name") or "").strip() == name), None)
            coverage_value = int(asset_match.get("evidence_count") or 0) if asset_match else 0
            competitor_coverage.append({"name": name, "value": coverage_value})
        snapshot["competitor_coverage"] = competitor_coverage
        return snapshot

    def _repair_competitor_intelligence(
        self,
        job: Dict[str, Any],
        assets: Dict[str, Any],
        *,
        persist: bool = False,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        evidence = [item for item in (assets.get("evidence") or []) if isinstance(item, dict)]
        if not evidence:
            return job, assets

        stored_competitors = [item for item in (assets.get("competitors") or []) if isinstance(item, dict)]
        stored_competitor_names = [str(item.get("name") or "").strip() for item in stored_competitors if str(item.get("name") or "").strip()]
        missing_evidence_competitor_name = any(not str(item.get("competitor_name") or "").strip() for item in evidence)
        request_context = build_request_from_job(job)
        synthesizer = SynthesizerAgent()
        seed_names = synthesizer._topic_competitor_seed_names(request_context)
        stored_competitor_name_set = set(stored_competitor_names)
        seed_name_set = set(seed_names)
        if (
            stored_competitor_names
            and not missing_evidence_competitor_name
            and int(job.get("competitor_count") or 0) == len(stored_competitor_names)
            and (not seed_name_set or stored_competitor_name_set.issubset(seed_name_set))
        ):
            return job, assets

        has_competitor_context = bool(seed_names) or any(
            str(item.get("market_step") or "").strip() in {"competitor-analysis", "business-and-channels", "experience-teardown"}
            for item in evidence
        )
        if not has_competitor_context and not stored_competitor_names and not missing_evidence_competitor_name:
            return job, assets

        should_refresh_competitors = not stored_competitors or (
            bool(seed_name_set)
            and not stored_competitor_name_set.issubset(seed_name_set)
        )
        normalized_competitors = stored_competitors
        if should_refresh_competitors:
            normalized_competitors = synthesizer.extract_competitors(request_context, evidence)
        competitor_names = [
            str(item.get("name") or "").strip()
            for item in normalized_competitors
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        competitor_names = list(dict.fromkeys(competitor_names))
        normalized_evidence = synthesizer.backfill_evidence_competitors(
            request_context,
            evidence,
            competitor_names=competitor_names or stored_competitor_names or None,
        )
        competitor_names = [
            str(item.get("name") or "").strip()
            for item in normalized_competitors
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        competitor_names = list(dict.fromkeys(competitor_names))
        changed = (
            normalized_evidence != evidence
            or normalized_competitors != stored_competitors
            or int(job.get("competitor_count") or 0) != len(competitor_names)
        )
        if not changed:
            return job, assets

        normalized_assets = deepcopy(assets)
        normalized_assets["evidence"] = normalized_evidence
        normalized_assets["competitors"] = normalized_competitors
        normalized_assets["progress_snapshot"] = self._refresh_competitor_progress_snapshot(normalized_assets, competitor_names)

        normalized_job = deepcopy(job)
        normalized_job["competitor_count"] = len(competitor_names)

        if persist:
            self.repository.set_assets(job["id"], normalized_assets)
            self.repository.update_job(job["id"], normalized_job)
            persisted_job = self.repository.get_job(job["id"]) or normalized_job
            persisted_assets = self.repository.get_assets(job["id"]) or normalized_assets
            return persisted_job, persisted_assets
        return normalized_job, normalized_assets

    def _build_version_diff_record(
        self,
        job_id: str,
        version_snapshot: Dict[str, Any],
        base_snapshot: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        diff_summary = build_report_version_diff_summary(version_snapshot, base_snapshot)
        version_id = str(version_snapshot.get("version_id") or "").strip()
        base_version_id = str((base_snapshot or {}).get("version_id") or "").strip()
        version_lines = str(version_snapshot.get("markdown") or "").splitlines()
        base_lines = str((base_snapshot or {}).get("markdown") or "").splitlines()
        unified_diff = list(
            difflib.unified_diff(
                base_lines,
                version_lines,
                fromfile=base_version_id or "base",
                tofile=version_id or "version",
                lineterm="",
                n=1,
            )
        )
        diff_markdown = ""
        if unified_diff:
            diff_markdown = "```diff\n" + "\n".join(unified_diff[:120]) + "\n```"
        elif diff_summary.get("summary"):
            diff_markdown = f"- {diff_summary['summary']}"
        return {
            "job_id": job_id,
            "version_id": version_id,
            "base_version_id": base_version_id,
            "summary": diff_summary.get("summary") or "当前两个版本没有结构化差异。",
            "version": version_snapshot,
            "base_version": base_snapshot,
            "diff_markdown": diff_markdown,
            "added_claim_ids": diff_summary.get("added_claim_ids") or diff_summary.get("claim_ids_added") or [],
            "removed_claim_ids": diff_summary.get("removed_claim_ids") or diff_summary.get("claim_ids_removed") or [],
            "added_evidence_ids": diff_summary.get("added_evidence_ids") or diff_summary.get("evidence_ids_added") or [],
            "removed_evidence_ids": diff_summary.get("removed_evidence_ids") or diff_summary.get("evidence_ids_removed") or [],
        }

    def _ensure_report_version_defaults(self, job: Dict[str, Any], assets: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        changed = False
        if not self._active_report_version_id(job) and str(job.get("report_version_id") or "").strip():
            job["active_report_version_id"] = job.get("report_version_id")
            changed = True
        if (
            assets
            and not self._stable_report_version_id(job)
            and str((assets.get("report") or {}).get("stage") or "").strip() == "final"
            and self._active_report_version_id(job)
        ):
            job["stable_report_version_id"] = self._active_report_version_id(job)
            changed = True
        if changed:
            self.repository.update_job(job["id"], job)
            return self.repository.get_job(job["id"]) or job
        return job

    def _source_domain(self, source_url: Any) -> str:
        parsed = urlparse(str(source_url or "").strip())
        domain = (parsed.netloc or parsed.path or "").strip().lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def _claim_verification_state(self, claim: Dict[str, Any]) -> str:
        explicit = str(claim.get("verification_state") or "").strip().lower()
        if explicit in {"supported", "inferred", "conflicted", "open_question"}:
            return explicit
        status = str(claim.get("status") or "").strip().lower()
        if status == "verified":
            return "supported"
        if status == "disputed":
            return "conflicted"
        evidence_ids = [str(item).strip() for item in (claim.get("supporting_evidence_ids") or claim.get("evidence_ids") or []) if str(item).strip()]
        return "inferred" if evidence_ids else "open_question"

    def _evidence_is_formal_candidate(self, item: Dict[str, Any]) -> bool:
        if not isinstance(item, dict) or is_context_only_evidence(item):
            return False
        source_type = str(item.get("source_type") or "").strip().lower()
        source_tier = str(item.get("source_tier") or "").strip().lower()
        final_eligibility = str(item.get("final_eligibility") or "").strip().lower()
        if source_type == "internal":
            return False
        if source_tier == "t4":
            return False
        if final_eligibility == "requires_external_evidence":
            return False
        return True

    def _formal_evidence(self, evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [item for item in evidence if self._evidence_is_formal_candidate(item)]

    def _claim_has_formal_support(
        self,
        claim: Dict[str, Any],
        formal_evidence_by_id: Dict[str, Dict[str, Any]],
    ) -> bool:
        if str(claim.get("final_eligibility") or "").strip().lower() == "requires_external_evidence":
            return False
        verification_state = self._claim_verification_state(claim)
        if verification_state in {"conflicted", "open_question"}:
            return False
        support_ids = {
            str(item).strip()
            for item in (claim.get("supporting_evidence_ids") or claim.get("evidence_ids") or [])
            if str(item).strip()
        }
        if not support_ids:
            return False
        formal_support = [formal_evidence_by_id[item_id] for item_id in support_ids if item_id in formal_evidence_by_id]
        if not formal_support:
            return False
        if len(formal_support) >= 2:
            return True
        strongest_tier = str(formal_support[0].get("source_tier") or "").strip().lower()
        strongest_authority = float(formal_support[0].get("authority_score", 0) or 0)
        return verification_state == "supported" and (
            strongest_tier in {"t1", "t2"} or strongest_authority >= 0.72
        )

    def _formal_claims(self, claims: List[Dict[str, Any]], formal_evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        formal_evidence_by_id = {
            str(item.get("id") or "").strip(): item
            for item in formal_evidence
            if str(item.get("id") or "").strip()
        }
        return [
            claim
            for claim in claims
            if isinstance(claim, dict) and self._claim_has_formal_support(claim, formal_evidence_by_id)
        ]

    def _build_finalize_quality_gate(
        self,
        current_report: Dict[str, Any],
        claims: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        formal_claims: List[Dict[str, Any]],
        formal_evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        formal_evidence_by_id = {
            str(item.get("id") or "").strip(): item
            for item in formal_evidence
            if str(item.get("id") or "").strip()
        }
        formal_domain_count = len(
            {
                domain
                for domain in (self._source_domain(item.get("source_url")) for item in formal_evidence)
                if domain
            }
        )
        context_only_evidence_count = max(0, len(evidence) - len(formal_evidence))
        unsupported_claim_ids = [
            str(item.get("id") or "").strip()
            for item in claims
            if isinstance(item, dict)
            and str(item.get("id") or "").strip()
            and not self._claim_has_formal_support(item, formal_evidence_by_id)
        ]
        reasons: List[str] = []
        if not str(current_report.get("markdown") or "").strip():
            reasons.append("当前没有可复用的报告正文，无法生成正式终稿。")
        if len(formal_evidence) < self.MIN_FORMAL_EVIDENCE_COUNT:
            reasons.append(
                f"外部可引用证据不足（当前 {len(formal_evidence)} 条，至少需要 {self.MIN_FORMAL_EVIDENCE_COUNT} 条）。"
            )
        if formal_domain_count < self.MIN_FORMAL_DOMAIN_COUNT:
            reasons.append(
                f"独立外部来源域名不足（当前 {formal_domain_count} 个，至少需要 {self.MIN_FORMAL_DOMAIN_COUNT} 个）。"
            )
        if len(formal_claims) < self.MIN_FORMAL_CLAIM_COUNT:
            reasons.append(
                f"可被外部证据支撑的结论不足（当前 {len(formal_claims)} 条，至少需要 {self.MIN_FORMAL_CLAIM_COUNT} 条）。"
            )
            if unsupported_claim_ids:
                preview = "、".join(unsupported_claim_ids[:4])
                suffix = " 等" if len(unsupported_claim_ids) > 4 else ""
                reasons.append(f"以下结论仍缺少可信支撑矩阵：{preview}{suffix}。")
        if evidence and context_only_evidence_count == len(evidence):
            reasons.append("当前新增材料全部来自 internal://delta-context，仅可作为补研线索，不能单独支撑正式终稿。")
        return {
            "policy_version": self.FINALIZE_QUALITY_GATE_POLICY_VERSION,
            "checked_at": iso_now(),
            "passed": not reasons,
            "thresholds": {
                "min_formal_evidence_count": self.MIN_FORMAL_EVIDENCE_COUNT,
                "min_formal_domain_count": self.MIN_FORMAL_DOMAIN_COUNT,
                "min_formal_claim_count": self.MIN_FORMAL_CLAIM_COUNT,
            },
            "metrics": {
                "total_claim_count": len(claims),
                "total_evidence_count": len(evidence),
                "formal_claim_count": len(formal_claims),
                "formal_evidence_count": len(formal_evidence),
                "formal_domain_count": formal_domain_count,
                "context_only_evidence_count": context_only_evidence_count,
                "unsupported_claim_count": len(unsupported_claim_ids),
            },
            "reasons": reasons,
        }

    async def create_job(self, payload: Dict[str, Any], owner_user_id: Optional[str] = None) -> Dict[str, Any]:
        job_id = str(uuid.uuid4())
        payload = deepcopy(payload)
        payload["job_id"] = job_id
        payload["runtime_config"] = self._resolve_runtime_config(payload.get("runtime_config"), owner_user_id=owner_user_id)
        workflow = self._build_workflow(payload.get("runtime_config"))
        runtime_retrieval_profile_id = workflow._resolve_retrieval_profile_id(payload)
        if runtime_retrieval_profile_id and not payload.get("retrieval_profile_id"):
            payload["retrieval_profile_id"] = runtime_retrieval_profile_id
        job = workflow.build_job_blueprint(payload)
        placeholder_tasks = [
            workflow._decorate_task(
                {
                    **task,
                    "agent_name": f"子研究体 {index + 1} · {task['title']}",
                    "agent_role": "sub-agent",
                    "sub_agent_id": f"{job_id}-sub-agent-{index + 1}",
                    "sub_agent_index": index + 1,
                }
            )
            for index, task in enumerate(workflow.planner.build_fallback_tasks(payload))
        ]
        if placeholder_tasks:
            job["tasks"] = placeholder_tasks
        job["quality_score_summary"] = job.get("quality_score_summary") or {}
        if job.get("retrieval_profile_id"):
            job["quality_score_summary"]["retrieval_profile_id"] = job.get("retrieval_profile_id")
        if payload.get("runtime_config"):
            runtime_config = payload["runtime_config"]
            quality_policy = runtime_config.get("quality_policy") or {}
            job["quality_score_summary"]["profile_id"] = str(runtime_config.get("profile_id") or "").strip() or None
            job["quality_score_summary"]["quality_policy_id"] = str(quality_policy.get("profile_id") or "").strip() or None
        job = self._normalize_job_response(job)
        if owner_user_id:
            job["owner_user_id"] = owner_user_id
        self.repository.create_job(job)
        self.repository.set_assets(job_id, build_empty_assets())

        if self.background_mode == "inline":
            self._run_job_sync(job_id, payload)
            return self.get_job(job_id, owner_user_id=owner_user_id)

        if self.background_mode == "worker":
            if not self.repository.supports_background_worker():
                self._mark_job_failed(job_id, "当前存储后端未启用共享 worker 队列，请配置 Redis 后再切换到 worker 模式。")
                return self.get_job(job_id, owner_user_id=owner_user_id)

            job["execution_mode"] = "worker"
            job["background_process"] = {
                "mode": "worker",
                "queue": "redis",
                "active": True,
                "enqueued_at": iso_now(),
                "launcher_pid": os.getpid(),
            }
            self.repository.update_job(job_id, job)
            try:
                self.repository.enqueue_background_job(job_id)
            except Exception as error:
                LOGGER.exception("Failed to enqueue shared worker job %s.", job_id)
                self._mark_job_failed(job_id, f"共享 worker 入队失败：{error}")
                return self.get_job(job_id, owner_user_id=owner_user_id)
            self.repository.publish_job_event(
                job_id,
                "job.progress",
                {
                    "job": self.repository.get_job(job_id),
                    "assets": self.repository.get_assets(job_id),
                    "message": "研究任务已进入共享 worker 队列，等待后台 worker 领取。",
                },
            )
            return deepcopy(job)

        try:
            process, log_path = self._spawn_job_process(job_id)
        except Exception as error:
            LOGGER.exception("Failed to launch detached worker for research job %s.", job_id)
            self._mark_job_failed(job_id, f"后台 worker 启动失败：{error}")
            return self.get_job(job_id, owner_user_id=owner_user_id)

        job["execution_mode"] = "subprocess"
        job["background_process"] = {
            "pid": process.pid,
            "active": True,
            "entrypoint": "pm_agent_api.worker_entry",
            "started_at": iso_now(),
            "launcher_pid": os.getpid(),
            "log_path": str(log_path),
        }
        self.repository.update_job(job_id, job)
        self.repository.publish_job_event(
            job_id,
            "job.progress",
            {
                "job": deepcopy(job),
                "assets": self.repository.get_assets(job_id),
                "message": "研究任务已进入独立后台 worker 进程执行。",
            },
        )
        return self._normalize_job_response(job)

    def list_jobs(self, owner_user_id: str) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        for job in self.repository.list_jobs(owner_user_id=owner_user_id):
            if int(job.get("competitor_count") or 0) <= 0:
                assets = self.repository.get_assets(job["id"])
                if assets:
                    job, _ = self._repair_competitor_intelligence(job, assets, persist=True)
            jobs.append(self._normalize_job_response(job))
        return jobs

    def get_health_status(self, runtime_configured: bool, owner_user_id: Optional[str] = None) -> Dict[str, Any]:
        return {
            "status": "ok",
            "active_job_count": self.repository.count_active_jobs(owner_user_id=owner_user_id),
            "active_detached_worker_count": self.repository.count_active_detached_workers(owner_user_id=owner_user_id),
            "runtime_configured": runtime_configured,
            "timestamp": iso_now(),
        }

    def _worker_entry_command(self, job_id: str) -> List[str]:
        return [
            sys.executable,
            "-m",
            "pm_agent_api.worker_entry",
            "--job-id",
            job_id,
        ]

    def _worker_log_path(self, job_id: str) -> Path:
        state_root = getattr(self.repository, "_state_root", Path(__file__).resolve().parents[4] / "output" / "state")
        log_dir = Path(state_root) / "worker_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / f"{job_id}.log"

    def _spawn_job_process(self, job_id: str) -> tuple[subprocess.Popen[Any], Path]:
        api_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        log_path = self._worker_log_path(job_id)
        with log_path.open("ab") as log_handle:
            process = subprocess.Popen(
                self._worker_entry_command(job_id),
                cwd=str(api_root),
                env=env,
                start_new_session=True,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
        return process, log_path

    def run_job_foreground(self, job_id: str) -> None:
        job = self.repository.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        payload = build_request_from_job(job)
        payload["runtime_config"] = job.get("runtime_config")
        self._run_job_sync(job_id, payload)

    def _mark_background_process_finished(self, job_id: str) -> None:
        job = self.repository.get_job(job_id)
        if not job:
            return

        background_process = job.get("background_process") or {}
        if not isinstance(background_process, dict) or not background_process.get("active"):
            return

        background_process["active"] = False
        background_process["finished_at"] = iso_now()
        job["background_process"] = background_process
        self.repository.update_job(job_id, job)

    def _run_job_sync(self, job_id: str, payload: Dict[str, Any]) -> None:
        try:
            self._raise_if_job_cancelled(job_id)
            asyncio.run(self._run_job(job_id, payload))
        except JobCancelledError as error:
            self._mark_job_cancelled(job_id, str(error))
        except Exception as error:
            cancelled_reason = self._cancel_reason_from_job(self.repository.get_job(job_id))
            if cancelled_reason:
                self._mark_job_cancelled(job_id, cancelled_reason)
                return
            LOGGER.exception("Research job %s crashed in background execution.", job_id)
            self._mark_job_failed(job_id, f"研究任务执行失败：{error}")
        finally:
            self._mark_background_process_finished(job_id)

    def _mark_job_failed(self, job_id: str, message: str) -> None:
        job = self.repository.get_job(job_id)
        if not job:
            return

        job["status"] = "failed"
        job["completion_mode"] = "diagnostic"
        job["latest_error"] = message
        job["latest_warning"] = None
        job["cancel_requested"] = False
        job["eta_seconds"] = 0
        job["running_task_count"] = 0
        job["completed_at"] = iso_now()
        background_process = job.get("background_process") or {}
        if isinstance(background_process, dict):
            background_process["active"] = False
            background_process["finished_at"] = iso_now()
            job["background_process"] = background_process
        job.setdefault("activity_log", []).append(build_task_log(message, level="error"))
        job["activity_log"] = job["activity_log"][-40:]
        self.repository.update_job(job_id, job)

        payload: Dict[str, Any] = {
            "job": self.repository.get_job(job_id),
            "message": message,
        }
        assets = self.repository.get_assets(job_id)
        if assets is not None:
            payload["assets"] = assets
        self.repository.publish_job_event(job_id, "job.failed", payload)

    def _mark_job_cancelled(self, job_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        job = self.repository.get_job(job_id)
        if not job:
            raise KeyError(job_id)

        cancellation_reason = str(reason or job.get("cancellation_reason") or "").strip() or self._default_cancellation_reason()
        existing_reason = str(job.get("cancellation_reason") or "").strip()
        should_append_log = job.get("status") != "cancelled" or existing_reason != cancellation_reason

        job["status"] = "cancelled"
        job["cancel_requested"] = True
        job["cancellation_reason"] = cancellation_reason
        job["latest_error"] = None
        job["latest_warning"] = None
        job["eta_seconds"] = 0
        job["running_task_count"] = 0
        job["completed_at"] = iso_now()
        for task in job.get("tasks", []):
            if task.get("status") in {"queued", "running"}:
                task["status"] = "cancelled"
                task["current_action"] = "已取消"
        background_process = job.get("background_process") or {}
        if isinstance(background_process, dict):
            background_process["cancel_requested_at"] = iso_now()
            job["background_process"] = background_process
        if should_append_log:
            job.setdefault("activity_log", []).append(build_task_log(f"研究任务已取消：{cancellation_reason}", level="warning"))
            job["activity_log"] = job["activity_log"][-40:]
        self.repository.update_job(job_id, job)
        return self.repository.get_job(job_id) or job

    def cancel_job(self, job_id: str, owner_user_id: Optional[str] = None, reason: Optional[str] = None) -> Dict[str, Any]:
        job = self.repository.get_job(job_id, owner_user_id=owner_user_id)
        if not job:
            raise KeyError(job_id)
        if job.get("status") == "cancelled":
            return job
        if not self._job_is_active(job.get("status")):
            raise ValueError("当前任务已结束，无法取消。")

        cancelled_job = self._mark_job_cancelled(job_id, reason)
        payload: Dict[str, Any] = {
            "job": cancelled_job,
            "message": cancelled_job.get("cancellation_reason") or self._default_cancellation_reason(),
        }
        assets = self.repository.get_assets(job_id)
        if assets is not None:
            payload["assets"] = assets
        self.repository.publish_job_event(job_id, "job.cancelled", payload)
        return cancelled_job

    async def _run_job(self, job_id: str, payload: Dict[str, Any]) -> None:
        job = self.repository.get_job(job_id)
        if not job:
            return
        self._raise_if_job_cancelled(job_id)
        workflow = self._build_workflow(payload.get("runtime_config"))

        def check_cancelled() -> Optional[str]:
            return self._cancel_reason_from_job(self.repository.get_job(job_id))

        async def publish(event_name: str, event_payload: Dict[str, Any]) -> None:
            current_job = self.repository.get_job(job_id)
            if current_job and current_job.get("status") == "cancelled":
                if "assets" in event_payload:
                    self.repository.set_assets(job_id, event_payload["assets"])
                if event_name == "job.cancelled":
                    payload_for_cancel = deepcopy(event_payload)
                    payload_for_cancel["job"] = current_job
                    payload_for_cancel.setdefault("assets", self.repository.get_assets(job_id))
                    self.repository.publish_job_event(job_id, event_name, payload_for_cancel)
                return
            updated_job = event_payload.get("job")
            if updated_job:
                self.repository.update_job(job_id, updated_job)
            if "assets" in event_payload:
                self.repository.set_assets(job_id, event_payload["assets"])
            self.repository.publish_job_event(job_id, event_name, event_payload)

        assets = await workflow.run_research(job, payload, publish, check_cancelled=check_cancelled)
        current_job = self.repository.get_job(job_id)
        if current_job and current_job.get("status") == "cancelled":
            cancelled_job = deepcopy(job)
            cancelled_job["status"] = "cancelled"
            cancelled_job["cancel_requested"] = True
            cancelled_job["cancellation_reason"] = (
                str(cancelled_job.get("cancellation_reason") or "").strip()
                or str(current_job.get("cancellation_reason") or "").strip()
                or self._default_cancellation_reason()
            )
            cancelled_job["latest_error"] = None
            cancelled_job["latest_warning"] = None
            cancelled_job["eta_seconds"] = 0
            cancelled_job["running_task_count"] = 0
            cancelled_job["completed_at"] = cancelled_job.get("completed_at") or current_job.get("completed_at") or iso_now()
            current_background_process = current_job.get("background_process") or {}
            cancelled_background_process = cancelled_job.get("background_process") or {}
            if isinstance(current_background_process, dict):
                merged_background_process = deepcopy(cancelled_background_process) if isinstance(cancelled_background_process, dict) else {}
                merged_background_process.update(current_background_process)
                cancelled_job["background_process"] = merged_background_process
            self.repository.update_job(job_id, cancelled_job)
            self.repository.set_assets(job_id, assets)
            return
        if current_job:
            self.repository.update_job(job_id, current_job)
        self.repository.set_assets(job_id, assets)
        final_job = self.repository.get_job(job_id)
        if final_job and final_job.get("status") == "completed":
            completion_message = str(final_job.get("latest_warning") or "").strip() or "研究任务已完成。"
            self.repository.publish_job_event(job_id, "job.progress", {"job": final_job, "message": completion_message})

    def get_job(self, job_id: str, owner_user_id: Optional[str] = None) -> Dict[str, Any]:
        job = self.repository.get_job(job_id, owner_user_id=owner_user_id)
        if not job:
            raise KeyError(job_id)
        assets = self.repository.get_assets(job_id)
        if assets:
            job, assets = self._repair_competitor_intelligence(job, assets, persist=True)
            job = self._reconcile_task_coverage_status(job, assets)
            job = self._ensure_report_version_defaults(job, assets)
        job = self._normalize_job_response(job)
        job["quality_score_summary"] = job.get("quality_score_summary") or {}
        return job

    def get_assets(self, job_id: str, owner_user_id: Optional[str] = None) -> Dict[str, Any]:
        job = self.repository.get_job(job_id, owner_user_id=owner_user_id)
        if not job:
            raise KeyError(job_id)
        assets = self.repository.get_assets(job_id)
        if not assets:
            raise KeyError(job_id)
        job, assets = self._repair_competitor_intelligence(job, assets, persist=True)
        self._ensure_report_version_defaults(job, assets)
        return assets

    def finalize_report(
        self,
        job_id: str,
        owner_user_id: Optional[str] = None,
        source_version_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        job = self.repository.get_job(job_id, owner_user_id=owner_user_id)
        if not job:
            raise KeyError(job_id)

        assets = self.repository.get_assets(job_id)
        if not assets:
            raise KeyError(job_id)
        job, assets = self._repair_competitor_intelligence(job, assets, persist=False)
        job = self._ensure_report_version_defaults(job, assets)

        workflow = self._build_workflow(job.get("runtime_config"))
        request_context = build_request_from_job(job)
        requested_source_version_id = str(source_version_id or self._active_report_version_id(job) or "").strip() or None
        source_snapshot = find_report_version_snapshot(assets, requested_source_version_id)
        if requested_source_version_id and not source_snapshot and requested_source_version_id != self._active_report_version_id(job):
            raise ValueError("Report version not found")
        current_report = deepcopy(source_snapshot or assets.get("report") or {})
        if source_snapshot:
            current_report.setdefault("feedback_notes", deepcopy((assets.get("report") or {}).get("feedback_notes") or []))
            current_report.setdefault("feedback_count", len(current_report.get("feedback_notes") or []))
            current_report["updated_at"] = iso_now()
        current_version_id = requested_source_version_id or (
            f"{job_id}-report-v1" if str(current_report.get("markdown") or "").strip() else None
        )
        all_claims = [item for item in (assets.get("claims") or []) if isinstance(item, dict)]
        all_evidence = [item for item in (assets.get("evidence") or []) if isinstance(item, dict)]
        attach_report_support_snapshot(
            current_report,
            claims=all_claims,
            evidence=all_evidence,
            prefer_claim_evidence=False,
        )
        base_snapshot = self._append_report_version_snapshot(
            assets,
            current_version_id,
            current_report,
            claims=all_claims,
            evidence=all_evidence,
            prefer_claim_evidence=False,
            metadata={
                "kind": current_report.get("kind") or "draft",
                "parent_version_id": current_report.get("parent_version_id"),
                "change_reason": current_report.get("change_reason") or "pre_finalize_snapshot",
                "generated_from_question": current_report.get("generated_from_question"),
            },
        )
        formal_evidence = self._formal_evidence(all_evidence)
        formal_claims = self._formal_claims(all_claims, formal_evidence)
        quality_gate = self._build_finalize_quality_gate(
            current_report=current_report,
            claims=all_claims,
            evidence=all_evidence,
            formal_claims=formal_claims,
            formal_evidence=formal_evidence,
        )
        competitor_names = [item["name"] for item in assets.get("competitors", []) if item.get("name")]
        if not competitor_names:
            assets["competitors"] = workflow.synthesizer.extract_competitors(request_context, formal_evidence)
            competitor_names = [item["name"] for item in assets.get("competitors", []) if item.get("name")]

        if not quality_gate["passed"]:
            blocked_report = deepcopy(current_report)
            attach_report_support_snapshot(
                blocked_report,
                claims=all_claims,
                evidence=all_evidence,
                prefer_claim_evidence=False,
            )
            blocked_report["updated_at"] = iso_now()
            blocked_report["stage"] = blocked_report.get("stage") if blocked_report.get("stage") in {"draft", "feedback_pending", "draft_pending"} else "draft"
            blocked_report["long_report_ready"] = False
            blocked_report["quality_gate"] = quality_gate
            blocked_report["kind"] = "draft"
            blocked_report["parent_version_id"] = current_version_id
            blocked_report["change_reason"] = "finalize_quality_gate_blocked"
            assets["report"] = blocked_report
            job["competitor_count"] = len(competitor_names)
            job["claims_count"] = len(all_claims)
            job["source_count"] = len(all_evidence)
            self._set_report_version_pointers(
                job,
                active_version_id=current_version_id,
                stable_version_id=self._stable_report_version_id(job),
            )
            self._update_quality_score_summary(
                job,
                readiness="draft",
                quality_gate=quality_gate,
                formal_claim_count=len(formal_claims),
                formal_evidence_count=len(formal_evidence),
                formal_domain_count=int(quality_gate["metrics"]["formal_domain_count"]),
                requires_finalize=True,
            )
            assets["market_map"] = {
                **(assets.get("market_map") or {}),
                "topic": request_context["topic"],
                "focus_areas": request_context.get("geo_scope", []),
                "browser_mode": workflow.browser.mode() if workflow.browser.is_available() else "static-fetch-degraded",
                "report_stage": blocked_report.get("stage", "draft"),
                "report_context_source": "finalize-quality-gate-blocked",
                "quality_gate_passed": False,
                "quality_gate_reasons": quality_gate.get("reasons", []),
            }
            assets["progress_snapshot"] = workflow._build_progress_snapshot(job, assets, competitor_names)
            self.repository.set_assets(job_id, assets)
            readable_reasons = "；".join(quality_gate.get("reasons", []))
            job.setdefault("activity_log", []).append(
                build_task_log(f"终稿生成已拦截：{readable_reasons}", level="warning")
            )
            job["activity_log"] = job["activity_log"][-40:]
            self.repository.update_job(job_id, job)
            self.repository.publish_job_event(
                job_id,
                "report.finalize_blocked",
                {
                    "job": self.repository.get_job(job_id),
                    "assets": assets,
                    "quality_gate": quality_gate,
                    "source_version_id": current_version_id,
                    "message": "终稿质量门槛未通过，已保留草稿状态。",
                },
            )
            return assets

        feedback_notes = list((assets.get("report") or {}).get("feedback_notes", current_report.get("feedback_notes", [])))
        conversation_excerpt = self._build_conversation_excerpt(job_id)
        job["competitor_count"] = len(competitor_names)
        job["claims_count"] = len(all_claims)
        job["source_count"] = len(all_evidence)
        assets["report"] = workflow.synthesizer.revise_report(
            request=request_context,
            current_report=current_report,
            claims=formal_claims,
            evidence=formal_evidence,
            competitor_names=competitor_names,
            feedback_notes=feedback_notes,
            conversation_excerpt=conversation_excerpt,
        )
        attach_report_support_snapshot(
            assets["report"],
            claims=formal_claims,
            evidence=formal_evidence,
            prefer_claim_evidence=True,
        )
        assets["report"]["kind"] = "final"
        assets["report"]["parent_version_id"] = current_version_id
        assets["report"]["change_reason"] = "manual_finalize" if source_version_id else "quality_gate_finalize"
        assets["report"]["quality_gate"] = quality_gate
        assets["report"]["formal_claim_count"] = len(formal_claims)
        assets["report"]["formal_evidence_count"] = len(formal_evidence)
        assets["report"]["context_only_evidence_count"] = quality_gate["metrics"]["context_only_evidence_count"]
        assets["market_map"] = {
            **(assets.get("market_map") or {}),
            "topic": request_context["topic"],
            "focus_areas": request_context.get("geo_scope", []),
            "browser_mode": workflow.browser.mode() if workflow.browser.is_available() else "static-fetch-degraded",
            "report_stage": assets["report"].get("stage", "final"),
            "report_context_source": "llm-dossier-rewrite-formal-evidence-only",
            "quality_gate_passed": True,
        }
        next_version_id = next_report_version_id(self._active_report_version_id(job) or current_version_id, job_id)
        final_snapshot = self._append_report_version_snapshot(
            assets,
            next_version_id,
            assets["report"],
            claims=formal_claims,
            evidence=formal_evidence,
            prefer_claim_evidence=True,
            metadata={
                "kind": "final",
                "parent_version_id": current_version_id,
                "change_reason": assets["report"].get("change_reason"),
                "generated_from_question": assets["report"].get("generated_from_question"),
                "quality_gate": quality_gate,
            },
        )
        if final_snapshot:
            diff_record = self._build_version_diff_record(job_id, final_snapshot, base_snapshot)
            final_snapshot["diff_summary"] = {
                "summary": diff_record["summary"],
                "added_claim_ids": diff_record["added_claim_ids"],
                "removed_claim_ids": diff_record["removed_claim_ids"],
                "added_evidence_ids": diff_record["added_evidence_ids"],
                "removed_evidence_ids": diff_record["removed_evidence_ids"],
                "changed_sections": [],
            }
            assets["report"]["diff_summary"] = final_snapshot["diff_summary"]
            append_report_version_snapshot_to_assets(assets, final_snapshot)
        assets["progress_snapshot"] = workflow._build_progress_snapshot(job, assets, competitor_names)
        self.repository.set_assets(job_id, assets)

        self._set_report_version_pointers(
            job,
            active_version_id=next_version_id,
            stable_version_id=next_version_id,
        )
        self._update_quality_score_summary(
            job,
            readiness="stable",
            quality_gate=quality_gate,
            formal_claim_count=len(formal_claims),
            formal_evidence_count=len(formal_evidence),
            formal_domain_count=int(quality_gate["metrics"]["formal_domain_count"]),
            requires_finalize=False,
        )
        job["runtime_summary"] = workflow._build_runtime_summary()
        job.setdefault("activity_log", []).append(
            build_task_log("已基于最新结构化研究材料重新生成正式终稿，并保留历史版本快照，当前终稿可供 PM Chat 继续引用。")
        )
        job["activity_log"] = job["activity_log"][-40:]
        self.repository.update_job(job_id, job)
        self.repository.publish_job_event(
            job_id,
            "report.finalized",
            {
                "job": self.repository.get_job(job_id),
                "assets": assets,
                "source_version_id": current_version_id,
                "final_version_id": next_version_id,
            },
        )
        return assets

    def get_report_version_diff(
        self,
        job_id: str,
        version_id: str,
        base_version_id: str,
        owner_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        job = self.repository.get_job(job_id, owner_user_id=owner_user_id)
        if not job:
            raise KeyError(job_id)
        assets = self.repository.get_assets(job_id)
        if not assets:
            raise KeyError(job_id)

        version_snapshot = find_report_version_snapshot(assets, version_id)
        base_snapshot = find_report_version_snapshot(assets, base_version_id)
        if not version_snapshot or not base_snapshot:
            raise ValueError("Report version not found")
        return self._build_version_diff_record(job_id, version_snapshot, base_snapshot)

    def open_task_source(self, job_id: str, task_id: str, owner_user_id: Optional[str] = None, url: Optional[str] = None) -> Dict[str, Any]:
        task = self.repository.find_task(job_id, task_id, owner_user_id=owner_user_id)
        if not task:
            raise KeyError(task_id)
        selected_url = url or task.get("current_url")
        if not selected_url:
            visited_sources = task.get("visited_sources", [])
            selected_url = visited_sources[0]["url"] if visited_sources else None
        if not selected_url:
            raise ValueError("No URL available for this task")
        result = self.browser.open(selected_url)
        return {"task_id": task_id, **result}

    async def stream(self, job_id: str, owner_user_id: Optional[str] = None):
        self.get_job(job_id, owner_user_id=owner_user_id)
        event_cursor = self.repository.get_job_event_cursor(job_id)
        event_queue = self.repository.subscribe_job_events(job_id)
        seen_event_ids: set[str] = set()
        try:
            while True:
                try:
                    event = await asyncio.to_thread(event_queue.get, True, 0.75)
                    if event.get("event") == self.repository.STREAM_CLOSED_EVENT:
                        break
                    event_id = str(event.get("id") or "")
                    if event_id:
                        seen_event_ids.add(event_id)
                    payload = json.dumps(event["payload"], ensure_ascii=False)
                    yield f"event: {event['event']}\ndata: {payload}\n\n"
                except Empty:
                    pass

                persisted_events, event_cursor = self.repository.read_job_events_since(job_id, event_cursor)
                for event in persisted_events:
                    event_id = str(event.get("id") or "")
                    if event_id and event_id in seen_event_ids:
                        continue
                    if event_id:
                        seen_event_ids.add(event_id)
                    payload = json.dumps(event["payload"], ensure_ascii=False)
                    yield f"event: {event['event']}\ndata: {payload}\n\n"
        finally:
            self.repository.unsubscribe_job_events(job_id, event_queue)
