import re
from typing import Any, Dict, Optional

from pm_agent_worker.workflows.research_models import report_version_sort_key


def build_request_from_job(job: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    request = {
        "job_id": job["id"],
        "topic": job.get("topic", ""),
        "industry_template": job.get("industry_template", "general"),
        "research_mode": job.get("research_mode", "standard"),
        "depth_preset": job.get("depth_preset", "standard"),
        "failure_policy": job.get("failure_policy", "graceful"),
        "workflow_command": job.get("workflow_command", "deep_general_scan"),
        "workflow_label": job.get("workflow_label", ""),
        "project_memory": job.get("project_memory", ""),
        "geo_scope": job.get("geo_scope", []),
        "max_sources": job.get("max_sources", 12),
        "max_subtasks": job.get("max_subtasks", 1),
        "max_competitors": job.get("max_competitors", 6),
        "review_sample_target": job.get("review_sample_target", 100),
        "time_budget_minutes": job.get("time_budget_minutes", 15),
        "language": job.get("language", "zh-CN"),
        "output_locale": job.get("output_locale", "zh-CN"),
    }
    if overrides:
        request.update(overrides)
    return request


def next_report_version_id(current_value: Optional[str], research_job_id: str) -> str:
    if not current_value:
        return f"{research_job_id}-report-v1"
    match = re.search(r"^(.*-report-v)(\d+)$", current_value)
    if match:
        return f"{match.group(1)}{int(match.group(2)) + 1}"
    return f"{current_value}-v2"


def is_context_only_evidence(item: Dict[str, Any]) -> bool:
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


def append_report_version_snapshot_to_assets(assets: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    if not snapshot:
        return
    sanitized: Dict[str, Dict[str, Any]] = {}
    for item in assets.get("report_versions") or []:
        if not isinstance(item, dict):
            continue
        version_id = str(item.get("version_id") or "").strip()
        markdown = str(item.get("markdown") or "").strip()
        if not version_id or not markdown:
            continue
        sanitized[version_id] = item
    sanitized[snapshot["version_id"]] = snapshot
    assets["report_versions"] = sorted(
        sanitized.values(),
        key=lambda entry: report_version_sort_key(entry.get("version_id")),
    )


def find_report_version_snapshot(assets: Dict[str, Any], version_id: Optional[str]) -> Optional[Dict[str, Any]]:
    version_id = str(version_id or "").strip()
    if not version_id:
        return None
    for item in assets.get("report_versions") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("version_id") or "") == version_id:
            return item
    return None


def build_report_version_diff_summary(new_snapshot: Dict[str, Any], base_snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    def _set_items(snapshot: Optional[Dict[str, Any]], key: str) -> set[str]:
        if not snapshot:
            return set()
        return {str(item).strip() for item in (snapshot.get(key) or []) if str(item).strip()}

    added_claims = _set_items(new_snapshot, "claim_ids") - _set_items(base_snapshot, "claim_ids")
    removed_claims = _set_items(base_snapshot, "claim_ids") - _set_items(new_snapshot, "claim_ids")
    added_evidence = _set_items(new_snapshot, "evidence_ids") - _set_items(base_snapshot, "evidence_ids")
    removed_evidence = _set_items(base_snapshot, "evidence_ids") - _set_items(new_snapshot, "evidence_ids")
    added_domains = _set_items(new_snapshot, "source_domains") - _set_items(base_snapshot, "source_domains")
    removed_domains = _set_items(base_snapshot, "source_domains") - _set_items(new_snapshot, "source_domains")
    summary_parts = [
        f"新增结论 {len(added_claims)} 条",
        f"移除结论 {len(removed_claims)} 条",
        f"新增证据 {len(added_evidence)} 条",
        f"移除证据 {len(removed_evidence)} 条",
    ]
    return {
        "summary": "，".join(summary_parts),
        "added_claim_ids": sorted(added_claims),
        "removed_claim_ids": sorted(removed_claims),
        "added_evidence_ids": sorted(added_evidence),
        "removed_evidence_ids": sorted(removed_evidence),
        "changed_sections": [],
        "claims_added": len(added_claims),
        "claims_removed": len(removed_claims),
        "claim_ids_added": sorted(added_claims),
        "claim_ids_removed": sorted(removed_claims),
        "evidence_added": len(added_evidence),
        "evidence_removed": len(removed_evidence),
        "evidence_ids_added": sorted(added_evidence),
        "evidence_ids_removed": sorted(removed_evidence),
        "domains_added": sorted(added_domains),
        "domains_removed": sorted(removed_domains),
    }
