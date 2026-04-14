from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkflowEvent:
    name: str
    payload: Dict[str, Any]


@dataclass
class ResearchBundle:
    job: Dict[str, Any]
    assets: Dict[str, Any]
    events: List[WorkflowEvent] = field(default_factory=list)


@dataclass
class DeltaResearchResult:
    delta_job_id: str
    claim: Dict[str, Any]
    evidence: List[Dict[str, Any]]
    follow_up_message: str


def build_phase_progress() -> List[Dict[str, Any]]:
    return [
        {"phase": "scoping", "label": "研究定义", "progress": 0, "status": "pending"},
        {"phase": "planning", "label": "研究规划", "progress": 0, "status": "pending"},
        {"phase": "collecting", "label": "证据采集", "progress": 0, "status": "pending"},
        {"phase": "verifying", "label": "校验与冲突处理", "progress": 0, "status": "pending"},
        {"phase": "synthesizing", "label": "洞察与成文", "progress": 0, "status": "pending"},
        {"phase": "finalizing", "label": "收尾与资产归档", "progress": 0, "status": "pending"},
    ]


def report_stage_label(stage: str) -> str:
    if stage == "final":
        return "终稿"
    if stage == "feedback_pending":
        return "待重成文"
    if stage == "draft":
        return "初稿"
    if stage == "draft_pending":
        return "生成中"
    return "报告版本"


def report_version_sort_key(version_id: Optional[str]) -> int:
    match = re.search(r"-report-v(\d+)$", str(version_id or "").strip())
    return int(match.group(1)) if match else 0


def next_report_version_id(current_value: Optional[str], research_job_id: str) -> str:
    if not current_value:
        return f"{research_job_id}-report-v1"
    match = re.search(r"^(.*-report-v)(\d+)$", current_value)
    if match:
        return f"{match.group(1)}{int(match.group(2)) + 1}"
    return f"{current_value}-v2"


def _normalized_id_list(items: Optional[List[Dict[str, Any]]]) -> List[str]:
    seen_ids = set()
    ordered_ids: List[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        ordered_ids.append(item_id)
    return ordered_ids


def _claim_linked_evidence_ids(
    claims: Optional[List[Dict[str, Any]]],
    valid_evidence_ids: Optional[set[str]] = None,
) -> List[str]:
    seen_ids = set()
    ordered_ids: List[str] = []
    for claim in claims or []:
        if not isinstance(claim, dict):
            continue
        for field_name in ("evidence_ids", "counter_evidence_ids"):
            for item in claim.get(field_name) or []:
                evidence_id = str(item or "").strip()
                if not evidence_id or evidence_id in seen_ids:
                    continue
                if valid_evidence_ids is not None and evidence_id not in valid_evidence_ids:
                    continue
                seen_ids.add(evidence_id)
                ordered_ids.append(evidence_id)
    return ordered_ids


def _normalized_source_domain(value: Any) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    if "://" not in raw_value and "/" not in raw_value:
        domain = raw_value.lower()
        return domain[4:] if domain.startswith("www.") else domain

    parsed = urlparse(raw_value if "://" in raw_value else f"https://{raw_value}")
    domain = (parsed.netloc or parsed.path or "").strip().lower()
    if "/" in domain:
        domain = domain.split("/", 1)[0]
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def build_report_support_snapshot(
    claims: Optional[List[Dict[str, Any]]] = None,
    evidence: Optional[List[Dict[str, Any]]] = None,
    prefer_claim_evidence: bool = False,
) -> Dict[str, Any]:
    claim_ids = _normalized_id_list(claims)
    normalized_evidence_ids = _normalized_id_list(evidence)
    valid_evidence_ids = set(normalized_evidence_ids)
    evidence_ids = _claim_linked_evidence_ids(claims, valid_evidence_ids) if prefer_claim_evidence and claim_ids else []
    if not evidence_ids:
        evidence_ids = normalized_evidence_ids
    evidence_id_filter = set(evidence_ids)
    seen_domains = set()
    source_domains: List[str] = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if evidence_id_filter and item_id and item_id not in evidence_id_filter:
            continue
        source_domain = _normalized_source_domain(item.get("source_domain") or item.get("source_url"))
        if not source_domain or source_domain in seen_domains:
            continue
        seen_domains.add(source_domain)
        source_domains.append(source_domain)
    return {
        "claim_ids": claim_ids,
        "evidence_ids": evidence_ids,
        "source_domains": source_domains,
    }


def attach_report_support_snapshot(
    report: Optional[Dict[str, Any]],
    claims: Optional[List[Dict[str, Any]]] = None,
    evidence: Optional[List[Dict[str, Any]]] = None,
    prefer_claim_evidence: bool = False,
) -> Dict[str, Any]:
    report = report or {}
    support_snapshot = build_report_support_snapshot(
        claims=claims,
        evidence=evidence,
        prefer_claim_evidence=prefer_claim_evidence,
    )
    report["claim_ids"] = support_snapshot["claim_ids"]
    report["evidence_ids"] = support_snapshot["evidence_ids"]
    report["source_domains"] = support_snapshot["source_domains"]
    report["evidence_count"] = len(support_snapshot["evidence_ids"])
    return report


def build_report_version_snapshot(
    version_id: Optional[str],
    report: Optional[Dict[str, Any]],
    claims: Optional[List[Dict[str, Any]]] = None,
    evidence: Optional[List[Dict[str, Any]]] = None,
    prefer_claim_evidence: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    version_id = str(version_id or "").strip()
    report = report or {}
    markdown = str(report.get("markdown") or "")
    if not version_id or not markdown.strip():
        return None

    support_snapshot = build_report_support_snapshot(
        claims=claims,
        evidence=evidence,
        prefer_claim_evidence=prefer_claim_evidence,
    )
    if report.get("claim_ids") or report.get("evidence_ids") or report.get("source_domains"):
        support_snapshot = {
            "claim_ids": [str(item).strip() for item in (report.get("claim_ids") or []) if str(item).strip()],
            "evidence_ids": [str(item).strip() for item in (report.get("evidence_ids") or []) if str(item).strip()],
            "source_domains": [str(item).strip() for item in (report.get("source_domains") or []) if str(item).strip()],
        }

    stage = str(report.get("stage") or "draft")
    version_kind = str(report.get("kind") or ("final" if stage == "final" else "draft"))
    updated_at = str(report.get("updated_at") or report.get("generated_at") or iso_now())
    generated_at = str(report.get("generated_at") or updated_at)
    snapshot: Dict[str, Any] = {
        "version_id": version_id,
        "version_number": report_version_sort_key(version_id),
        "label": report_stage_label(stage),
        "stage": stage,
        "kind": version_kind,
        "parent_version_id": report.get("parent_version_id"),
        "change_reason": report.get("change_reason"),
        "generated_from_question": report.get("generated_from_question"),
        "markdown": markdown,
        "board_brief_markdown": report.get("board_brief_markdown"),
        "executive_memo_markdown": report.get("executive_memo_markdown"),
        "appendix_markdown": report.get("appendix_markdown"),
        "conflict_summary_markdown": report.get("conflict_summary_markdown"),
        "decision_snapshot": report.get("decision_snapshot"),
        "generated_at": generated_at,
        "updated_at": updated_at,
        "section_count": report.get("section_count"),
        "evidence_count": report.get("evidence_count") if report.get("evidence_count") is not None else len(support_snapshot["evidence_ids"]),
        "feedback_count": report.get("feedback_count"),
        "revision_count": report.get("revision_count"),
        "long_report_ready": report.get("long_report_ready"),
        "claim_ids": support_snapshot["claim_ids"],
        "evidence_ids": support_snapshot["evidence_ids"],
        "source_domains": support_snapshot["source_domains"],
        "quality_gate": report.get("quality_gate"),
    }
    snapshot["support_snapshot"] = support_snapshot
    snapshot["diff_summary"] = report.get("diff_summary")
    if metadata:
        snapshot.update(metadata)
    return snapshot


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
    def to_set(snapshot: Optional[Dict[str, Any]], key: str) -> set[str]:
        if not snapshot:
            return set()
        return {str(item).strip() for item in (snapshot.get(key) or []) if str(item).strip()}

    added_claims = to_set(new_snapshot, "claim_ids") - to_set(base_snapshot, "claim_ids")
    removed_claims = to_set(base_snapshot, "claim_ids") - to_set(new_snapshot, "claim_ids")
    added_evidence = to_set(new_snapshot, "evidence_ids") - to_set(base_snapshot, "evidence_ids")
    removed_evidence = to_set(base_snapshot, "evidence_ids") - to_set(new_snapshot, "evidence_ids")
    added_domains = to_set(new_snapshot, "source_domains") - to_set(base_snapshot, "source_domains")
    removed_domains = to_set(base_snapshot, "source_domains") - to_set(new_snapshot, "source_domains")
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


def build_empty_assets() -> Dict[str, Any]:
    now = iso_now()
    return {
        "report": {
            "markdown": "",
            "board_brief_markdown": "",
            "executive_memo_markdown": "",
            "appendix_markdown": "",
            "conflict_summary_markdown": "",
            "claim_ids": [],
            "evidence_ids": [],
            "source_domains": [],
            "decision_snapshot": {
                "readiness": "待生成",
            },
            "generated_at": now,
            "updated_at": now,
            "stage": "draft_pending",
            "revision_count": 0,
            "feedback_count": 0,
            "feedback_notes": [],
        },
        "claims": [],
        "evidence": [],
        "competitors": [],
        "market_map": {},
        "progress_snapshot": {
            "source_growth": [],
            "source_mix": [],
            "competitor_coverage": [],
        },
        "report_versions": [],
        "artifacts": [],
    }


def top_keywords(text: str, limit: int = 3) -> List[str]:
    tokens = [token.strip() for token in text.replace("，", " ").replace(",", " ").split() if token.strip()]
    return tokens[:limit] or ["PM", "research", "agent"]


def build_task_log(message: str, level: str = "info") -> Dict[str, Any]:
    return {
        "id": uuid4().hex,
        "timestamp": iso_now(),
        "level": level,
        "message": message,
    }
