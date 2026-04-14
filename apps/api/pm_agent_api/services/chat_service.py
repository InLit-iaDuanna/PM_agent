import asyncio
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

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

from pm_agent_worker.workflows.research_models import attach_report_support_snapshot, build_report_version_snapshot
from pm_agent_worker.workflows.research_workflow import ResearchWorkflowEngine


LOGGER = logging.getLogger(__name__)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatService:
    def __init__(self, repository: StateRepositoryProtocol) -> None:
        self.repository = repository

    def _require_owned_job(self, research_job_id: str, owner_user_id: str) -> Dict[str, Any]:
        job = self.repository.get_job(research_job_id, owner_user_id=owner_user_id)
        if not job:
            raise KeyError(research_job_id)
        return job

    def _require_owned_session(self, session_id: str, owner_user_id: str) -> Dict[str, Any]:
        session = self.repository.get_chat_session(session_id, owner_user_id=owner_user_id)
        if not session:
            raise KeyError(session_id)
        return session

    def _build_workflow_for_job(self, research_job_id: str) -> ResearchWorkflowEngine:
        job = self.repository.get_job(research_job_id) or {}
        return ResearchWorkflowEngine(runtime_config=job.get("runtime_config"))

    def _active_report_version_id(self, job: Dict[str, Any]) -> str | None:
        return str(job.get("active_report_version_id") or job.get("report_version_id") or "").strip() or None

    def _stable_report_version_id(self, job: Dict[str, Any]) -> str | None:
        return str(job.get("stable_report_version_id") or "").strip() or None

    def _requires_finalize(self, job: Dict[str, Any]) -> bool:
        active_version_id = self._active_report_version_id(job)
        stable_version_id = self._stable_report_version_id(job)
        return bool(active_version_id and active_version_id != stable_version_id)

    def _set_report_version_pointers(
        self,
        job: Dict[str, Any],
        *,
        active_version_id: str | None,
        stable_version_id: str | None,
    ) -> None:
        job["active_report_version_id"] = active_version_id
        job["stable_report_version_id"] = stable_version_id
        job["report_version_id"] = active_version_id

    def _sanitize_delta_evidence(self, evidence: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        sanitized: list[Dict[str, Any]] = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            record = dict(item)
            if is_context_only_evidence(record):
                record["evidence_role"] = "context_only"
                record["source_tier"] = "t4"
                record["source_tier_label"] = "T4 内部上下文线索（不可单独成稿）"
                record["final_eligibility"] = "requires_external_evidence"
                tags = {str(tag or "").strip() for tag in (record.get("tags") or []) if str(tag or "").strip()}
                tags.update({"delta-context-fallback", "context-only"})
                record["tags"] = sorted(tags)
            sanitized.append(record)
        return sanitized

    def _build_delta_event_payload(
        self,
        session_id: str,
        delta_job_id: str,
        user_message: str,
        extra: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        payload = self._build_session_event_payload(session_id)
        payload.update(
            {
                "delta_job_id": delta_job_id,
                "question": user_message,
            }
        )
        if extra:
            payload.update(extra)
        return payload

    def _build_session_event_payload(self, session_id: str, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "session_id": session_id,
        }
        session = self.repository.get_chat_session(session_id)
        if session:
            payload["session"] = session
        if extra:
            payload.update(extra)
        return payload

    def _publish_session_updated(self, research_job_id: str, session_id: str) -> None:
        self.repository.publish_job_event(
            research_job_id,
            "chat.session.updated",
            self._build_session_event_payload(session_id),
        )

    def create_session(self, research_job_id: str, owner_user_id: str, reuse_existing: bool = True) -> Dict[str, Any]:
        self._require_owned_job(research_job_id, owner_user_id)
        if reuse_existing:
            existing_session = self.repository.get_latest_chat_session_for_job(research_job_id, owner_user_id=owner_user_id)
            if existing_session:
                return existing_session
        session = {
            "id": str(uuid.uuid4()),
            "research_job_id": research_job_id,
            "owner_user_id": owner_user_id,
            "messages": [],
        }
        self.repository.create_chat_session(session)
        return self.repository.get_chat_session(session["id"], owner_user_id=owner_user_id) or session

    def list_sessions(self, research_job_id: str, owner_user_id: str) -> list[Dict[str, Any]]:
        self._require_owned_job(research_job_id, owner_user_id)
        return self.repository.list_chat_sessions(research_job_id=research_job_id, owner_user_id=owner_user_id)

    async def send_message(self, session_id: str, content: str, owner_user_id: str) -> Dict[str, Any]:
        session = self._require_owned_session(session_id, owner_user_id)
        job = self.repository.get_job(session["research_job_id"]) or {}

        user_message = {
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": content,
            "cited_claim_ids": [],
            "created_at": iso_now(),
        }
        self.repository.append_chat_message(session_id, user_message, owner_user_id=owner_user_id)

        assets = self.repository.get_assets(session["research_job_id"]) or {"claims": [], "evidence": [], "report": {"markdown": ""}}
        report_asset = assets.get("report", {})
        report_markdown = report_asset.get("markdown", "")
        if not str(report_markdown or "").strip():
            assistant_message = {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": "研究还在生成报告初稿。等初稿完成后，我会基于报告与你继续讨论，并把反馈回写进终稿。",
                "cited_claim_ids": [],
                "answer_mode": "report_pending",
                "draft_version_id": self._active_report_version_id(job),
                "requires_finalize": self._requires_finalize(job),
                "created_at": iso_now(),
            }
            self.repository.append_chat_message(session_id, assistant_message, owner_user_id=owner_user_id)
            self._publish_session_updated(session["research_job_id"], session_id)
            return {
                "session_id": session_id,
                "message": assistant_message,
                "answer_mode": assistant_message["answer_mode"],
                "draft_version_id": assistant_message["draft_version_id"],
                "requires_finalize": assistant_message["requires_finalize"],
            }

        workflow = self._build_workflow_for_job(session["research_job_id"])
        response = workflow.dialogue.build_response(
            content,
            assets.get("claims", []),
            assets.get("evidence", []),
            report_markdown,
            session["research_job_id"],
            (session.get("messages") or []) + [user_message],
            report_stage=report_asset.get("stage", "draft"),
            project_memory=str(job.get("project_memory") or ""),
            workflow_command_label=str(job.get("workflow_label") or job.get("workflow_command") or ""),
        )
        assistant_message = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": response["content"],
            "cited_claim_ids": response["cited_claim_ids"],
            "answer_mode": "delta_requested" if response["needs_delta_research"] else "report_context",
            "draft_version_id": self._active_report_version_id(job),
            "requires_finalize": self._requires_finalize(job),
            "created_at": iso_now(),
        }
        if response["needs_delta_research"]:
            delta_job_id = f"delta-{uuid.uuid4().hex[:8]}"
            assistant_message["triggered_delta_job_id"] = delta_job_id
        self.repository.append_chat_message(session_id, assistant_message, owner_user_id=owner_user_id)
        self._publish_session_updated(session["research_job_id"], session_id)
        if response["needs_delta_research"]:
            thread = threading.Thread(
                target=self._finish_delta_research_sync,
                args=(session_id, session["research_job_id"], delta_job_id, content),
                daemon=True,
            )
            thread.start()
        return {
            "session_id": session_id,
            "message": assistant_message,
            "answer_mode": assistant_message["answer_mode"],
            "draft_version_id": assistant_message["draft_version_id"],
            "requires_finalize": assistant_message["requires_finalize"],
        }

    def _finish_delta_research_sync(self, session_id: str, research_job_id: str, delta_job_id: str, user_message: str) -> None:
        try:
            asyncio.run(self._finish_delta_research(session_id, research_job_id, delta_job_id, user_message))
        except Exception as error:
            LOGGER.exception("Delta research %s crashed for research job %s.", delta_job_id, research_job_id)
            self._handle_delta_research_failure(session_id, research_job_id, delta_job_id, user_message, error)

    def _handle_delta_research_failure(
        self,
        session_id: str,
        research_job_id: str,
        delta_job_id: str,
        user_message: str,
        error: Exception,
    ) -> None:
        failure_content = "这次补充研究在后台执行时失败了。我先保留你的问题，你可以稍后重试，或先基于当前报告继续讨论。"
        job = self.repository.get_job(research_job_id) or {}
        failure_message = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": failure_content,
            "cited_claim_ids": [],
            "triggered_delta_job_id": delta_job_id,
            "answer_mode": "delta_failed",
            "draft_version_id": self._active_report_version_id(job),
            "requires_finalize": self._requires_finalize(job),
            "created_at": iso_now(),
        }
        try:
            self.repository.append_chat_message(session_id, failure_message)
            self._publish_session_updated(research_job_id, session_id)
        except KeyError:
            pass

        job = self.repository.get_job(research_job_id)
        next_draft_version_id = self._active_report_version_id(job or {})
        if job:
            job.setdefault("activity_log", []).append(
                {
                    "id": uuid.uuid4().hex,
                    "timestamp": iso_now(),
                    "level": "error",
                    "message": f"PM Chat 补充研究失败：{error}",
                }
            )
            job["activity_log"] = job["activity_log"][-40:]
            self.repository.update_job(research_job_id, job)

        payload = self._build_delta_event_payload(
            session_id=session_id,
            delta_job_id=delta_job_id,
            user_message=user_message,
            extra={"message": failure_content, "error": str(error)},
        )
        latest_job = self.repository.get_job(research_job_id)
        if latest_job:
            payload["job"] = latest_job
        assets = self.repository.get_assets(research_job_id)
        if assets is not None:
            payload["assets"] = assets
        self.repository.publish_job_event(research_job_id, "delta_research.failed", payload)

    async def _finish_delta_research(self, session_id: str, research_job_id: str, delta_job_id: str, user_message: str) -> None:
        self.repository.publish_job_event(
            research_job_id,
            "delta_research.started",
            self._build_delta_event_payload(session_id=session_id, delta_job_id=delta_job_id, user_message=user_message),
        )
        await asyncio.sleep(0.05)
        workflow = self._build_workflow_for_job(research_job_id)
        assets = self.repository.get_assets(research_job_id) or {"claims": [], "evidence": [], "report": {"markdown": ""}, "competitors": [], "market_map": {}, "progress_snapshot": {}}
        job = self.repository.get_job(research_job_id)
        request_context = (
            build_request_from_job(job)
            if job
            else build_request_from_job(
                {
                    "id": research_job_id,
                    "topic": research_job_id,
                    "workflow_label": "全景深度扫描",
                    "max_sources": 6,
                }
            )
        )
        existing_competitor_names = [item["name"] for item in assets.get("competitors", []) if item.get("name")]
        try:
            delta_result = await workflow.run_delta_research(request_context, user_message, delta_job_id, existing_competitor_names)
        except Exception:
            delta_result = workflow.dialogue.run_delta_research(request_context.get("job_id", research_job_id), user_message, delta_job_id)
        delta_evidence = self._sanitize_delta_evidence(list(delta_result.evidence or []))
        requires_external_verification = bool(delta_evidence) and all(is_context_only_evidence(item) for item in delta_evidence)
        delta_claim = dict(delta_result.claim or {})
        delta_claim.setdefault("id", f"{delta_job_id}-claim-1")
        claim_caveats = [str(item).strip() for item in (delta_claim.get("caveats") or []) if str(item).strip()]
        if requires_external_verification:
            boundary_text = "当前仅有 internal://delta-context 类型线索，需补充外部证据后才能进入正式终稿。"
            if boundary_text not in claim_caveats:
                claim_caveats.append(boundary_text)
            delta_claim["status"] = "inferred"
            delta_claim["final_eligibility"] = "requires_external_evidence"
            delta_claim["evidence_boundary"] = "context_only"
        delta_claim["caveats"] = claim_caveats
        assets["claims"].append(delta_claim)
        assets["evidence"].extend(delta_evidence)
        assets["competitors"] = workflow.synthesizer.extract_competitors(request_context, assets["evidence"])
        feedback_notes = list((assets.get("report") or {}).get("feedback_notes", []))
        feedback_notes.append(
            {
                "question": user_message,
                "response": delta_result.follow_up_message,
                "claim_id": delta_claim["id"],
                "created_at": iso_now(),
                "action": (
                    "已纳入结构化补研资产（内部上下文线索），需补充外部证据后再进入终稿"
                    if requires_external_verification
                    else "已纳入结构化补研资产，等待手动生成终稿"
                ),
            }
        )
        competitor_names = [item["name"] for item in assets.get("competitors", []) if item.get("name")]
        current_report = dict(assets.get("report") or {})
        current_report["feedback_notes"] = feedback_notes
        current_report["feedback_count"] = len(feedback_notes)
        current_report["updated_at"] = iso_now()
        current_report["stage"] = "feedback_pending"
        current_report["long_report_ready"] = False
        current_report["draft_markdown"] = current_report.get("draft_markdown") or current_report.get("markdown", "")
        current_report["quality_gate"] = {
            "pending": True,
            "reason": "新增补研结果尚未经过终稿质量门槛校验。",
            "checked_at": iso_now(),
        }
        current_report["kind"] = "draft"
        assets["report"] = current_report
        attach_report_support_snapshot(
            assets["report"],
            claims=assets["claims"],
            evidence=assets["evidence"],
            prefer_claim_evidence=False,
        )
        if job:
            job["claims_count"] = len(assets["claims"])
            job["source_count"] = len(assets["evidence"])
            job["competitor_count"] = len(assets.get("competitors", []))
            current_active_version_id = self._active_report_version_id(job)
            if not current_active_version_id and str((assets.get("report") or {}).get("markdown") or "").strip():
                current_active_version_id = f"{research_job_id}-report-v1"
                base_snapshot = find_report_version_snapshot(assets, current_active_version_id)
                if not base_snapshot:
                    base_snapshot = build_report_version_snapshot(
                        current_active_version_id,
                        assets["report"],
                        claims=assets["claims"],
                        evidence=assets["evidence"],
                        prefer_claim_evidence=False,
                        metadata={
                            "kind": "draft",
                            "parent_version_id": None,
                            "change_reason": "legacy_report_backfill",
                        },
                    )
                    if base_snapshot:
                        append_report_version_snapshot_to_assets(assets, base_snapshot)
            next_draft_version_id = next_report_version_id(current_active_version_id, research_job_id)
            draft_snapshot = build_report_version_snapshot(
                next_draft_version_id,
                {
                    **assets["report"],
                    "kind": "draft",
                    "parent_version_id": current_active_version_id,
                    "change_reason": "pm_chat_delta_research",
                    "generated_from_question": user_message,
                },
                claims=assets["claims"],
                evidence=assets["evidence"],
                prefer_claim_evidence=False,
                metadata={
                    "kind": "draft",
                    "parent_version_id": current_active_version_id,
                    "change_reason": "pm_chat_delta_research",
                    "generated_from_question": user_message,
                },
            )
            if draft_snapshot:
                base_snapshot = find_report_version_snapshot(assets, current_active_version_id)
                diff_summary = build_report_version_diff_summary(draft_snapshot, base_snapshot)
                draft_snapshot["diff_summary"] = {
                    "summary": diff_summary.get("summary"),
                    "added_claim_ids": diff_summary.get("added_claim_ids") or diff_summary.get("claim_ids_added") or [],
                    "removed_claim_ids": diff_summary.get("removed_claim_ids") or diff_summary.get("claim_ids_removed") or [],
                    "added_evidence_ids": diff_summary.get("added_evidence_ids") or diff_summary.get("evidence_ids_added") or [],
                    "removed_evidence_ids": diff_summary.get("removed_evidence_ids") or diff_summary.get("evidence_ids_removed") or [],
                    "changed_sections": [],
                }
                append_report_version_snapshot_to_assets(assets, draft_snapshot)
                assets["report"]["diff_summary"] = draft_snapshot["diff_summary"]
                assets["report"]["parent_version_id"] = current_active_version_id
                assets["report"]["generated_from_question"] = user_message
                assets["report"]["change_reason"] = "pm_chat_delta_research"
                self._set_report_version_pointers(
                    job,
                    active_version_id=next_draft_version_id,
                    stable_version_id=self._stable_report_version_id(job),
                )
                job["quality_score_summary"] = {
                    "report_readiness": "draft",
                    "formal_claim_count": 0,
                    "formal_evidence_count": 0,
                    "formal_domain_count": 0,
                    "requires_finalize": True,
                }
            else:
                next_draft_version_id = current_active_version_id
        assets["market_map"] = {
            **(assets.get("market_map") or {}),
            "topic": request_context["topic"],
            "focus_areas": request_context.get("geo_scope", []),
            "browser_mode": workflow.browser.mode() if workflow.browser.is_available() else "static-fetch-degraded",
            "report_stage": current_report.get("stage", "feedback_pending"),
            "report_context_source": "structured-claims-pending-final-compose",
            "context_only_evidence_count": sum(1 for item in assets["evidence"] if is_context_only_evidence(item)),
        }
        assets["progress_snapshot"] = workflow._build_progress_snapshot(
            job or {"tasks": [], "source_count": len(assets["evidence"]), "claims_count": len(assets["claims"]), "completed_task_count": 0},
            assets,
            competitor_names,
        )
        self.repository.set_assets(research_job_id, assets)
        follow_up_message = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": delta_result.follow_up_message,
            "cited_claim_ids": [delta_claim["id"]],
            "triggered_delta_job_id": delta_job_id,
            "answer_mode": "delta_draft",
            "draft_version_id": next_draft_version_id,
            "requires_finalize": True,
            "created_at": iso_now(),
        }
        self.repository.append_chat_message(session_id, follow_up_message)
        self._publish_session_updated(research_job_id, session_id)
        if job:
            job["runtime_summary"] = workflow._build_runtime_summary()
            job.setdefault("activity_log", []).append(
                {
                    "id": uuid.uuid4().hex,
                    "timestamp": iso_now(),
                    "level": "info",
                    "message": "PM Chat 触发的补充研究已完成，新增结论已进入结构化资产，等待显式最终成文。",
                }
            )
            job["activity_log"] = job["activity_log"][-40:]
            self.repository.update_job(research_job_id, job)
        self.repository.publish_job_event(
            research_job_id,
            "delta_research.completed",
            self._build_delta_event_payload(
                session_id=session_id,
                delta_job_id=delta_job_id,
                user_message=user_message,
                extra={
                    "claim_id": delta_claim["id"],
                    "message": delta_result.follow_up_message,
                    "requires_external_verification": requires_external_verification,
                    "draft_version_id": next_draft_version_id,
                    "requires_finalize": True,
                    "job": self.repository.get_job(research_job_id),
                    "assets": assets,
                },
            ),
        )

    def get_session(self, session_id: str, owner_user_id: str) -> Dict[str, Any]:
        return self._require_owned_session(session_id, owner_user_id)
