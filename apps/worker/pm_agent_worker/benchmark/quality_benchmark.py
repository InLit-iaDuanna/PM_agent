from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_CASES_PATH = ROOT_DIR / "packages" / "research-core" / "data" / "golden_research_benchmarks.json"
DEFAULT_RESULTS_PATH = ROOT_DIR / "benchmarks" / "sample_results.json"
DEFAULT_JSON_REPORT_PATH = ROOT_DIR / "tmp" / "benchmark-quality-report.json"

TIER_WEIGHT = {"t1": 4, "t2": 3, "t3": 2, "t4": 1}
OFFICIAL_SOURCE_TYPES = {"documentation", "pricing", "web"}
SCENARIO_SOURCE_TYPES = {
    "market_trends": ("web", "article", "web", "community", "article"),
    "user_jobs_and_pains": ("community", "article", "web", "review", "article"),
    "competitor_landscape": ("web", "review", "article", "community", "web"),
    "product_experience_teardown": ("web", "documentation", "review", "article", "community"),
    "reviews_and_sentiment": ("community", "review", "article", "web", "community"),
    "pricing_and_business_model": ("pricing", "documentation", "review", "article", "web"),
    "acquisition_and_distribution": ("article", "web", "community", "article", "web"),
    "opportunities_and_risks": ("web", "article", "community", "documentation", "article"),
}
SCENARIO_STEP = {
    "market_trends": "market-trends",
    "user_jobs_and_pains": "user-research",
    "competitor_landscape": "competitor-analysis",
    "product_experience_teardown": "experience-teardown",
    "reviews_and_sentiment": "reviews-and-sentiment",
    "pricing_and_business_model": "pricing-and-growth",
    "acquisition_and_distribution": "business-and-channels",
    "opportunities_and_risks": "recommendations",
}


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_benchmark_cases(path: Path | str = DEFAULT_CASES_PATH) -> List[Dict[str, Any]]:
    raw = _read_json(Path(path))
    if not isinstance(raw, list):
        raise ValueError("Benchmark cases must be a JSON array.")
    cases: List[Dict[str, Any]] = []
    seen_ids = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("id") or "").strip()
        if not case_id or case_id in seen_ids:
            continue
        seen_ids.add(case_id)
        cases.append(item)
    return cases


def load_benchmark_results(path: Path | str = DEFAULT_RESULTS_PATH) -> Dict[str, Dict[str, Any]]:
    results_path = Path(path)
    bundles: List[Dict[str, Any]] = []
    if results_path.is_dir():
        for item in sorted(results_path.glob("*.json")):
            payload = _read_json(item)
            if isinstance(payload, list):
                bundles.extend(entry for entry in payload if isinstance(entry, dict))
            elif isinstance(payload, dict):
                bundles.append(payload)
    else:
        payload = _read_json(results_path)
        if isinstance(payload, list):
            bundles.extend(entry for entry in payload if isinstance(entry, dict))
        elif isinstance(payload, dict):
            bundles.append(payload)

    result_by_case: Dict[str, Dict[str, Any]] = {}
    for item in bundles:
        case_id = str(item.get("case_id") or "").strip()
        if case_id:
            result_by_case[case_id] = item
    return result_by_case


def _normalized_text(*parts: Any) -> str:
    return " ".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())


def _normalized_domain(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("www."):
        return text[4:]
    return text


def _tier_weight(item: Dict[str, Any]) -> int:
    return TIER_WEIGHT.get(str(item.get("source_tier") or "").strip().lower(), 0)


def _ranked_evidence(evidence: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        [item for item in evidence if isinstance(item, dict)],
        key=lambda item: (
            _tier_weight(item),
            float(item.get("confidence", 0) or 0),
            float(item.get("authority_score", 0) or 0),
            float(item.get("freshness_score", 0) or 0),
        ),
        reverse=True,
    )


def _is_context_only_evidence(item: Dict[str, Any]) -> bool:
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


def _is_formal_evidence(item: Dict[str, Any]) -> bool:
    if _is_context_only_evidence(item):
        return False
    if str(item.get("source_type") or "").strip().lower() == "internal":
        return False
    if str(item.get("source_tier") or "").strip().lower() == "t4":
        return False
    if str(item.get("final_eligibility") or "").strip().lower() == "requires_external_evidence":
        return False
    return True


def _is_high_quality_evidence(item: Dict[str, Any]) -> bool:
    if str(item.get("source_tier") or "").strip().lower() in {"t1", "t2"}:
        return True
    if float(item.get("authority_score", 0) or 0) >= 0.72:
        return True
    reliability = item.get("reliability_scores") or {}
    return float(reliability.get("authority", 0) or 0) >= 0.72


def _is_official_evidence(item: Dict[str, Any], official_domains_any: List[str]) -> bool:
    source_type = str(item.get("source_type") or "").strip().lower()
    source_domain = _normalized_domain(item.get("source_domain"))
    if source_type in OFFICIAL_SOURCE_TYPES:
        return True
    return any(source_domain == domain or source_domain.endswith(f".{domain}") for domain in official_domains_any)


def _expectation(case: Dict[str, Any], key: str, default: Any = None) -> Any:
    expectations = case.get("expectations") or {}
    return expectations.get(key, default)


def _evidence_matches_case(item: Dict[str, Any], case: Dict[str, Any]) -> bool:
    text = _normalized_text(
        item.get("title"),
        item.get("summary"),
        item.get("quote"),
        item.get("normalized_fact"),
        item.get("source_url"),
        item.get("source_domain"),
    )
    off_topic_patterns = [str(value).strip().lower() for value in _expectation(case, "off_topic_patterns", []) if str(value).strip()]
    if any(pattern in text for pattern in off_topic_patterns):
        return False
    expected_entities = [str(value).strip().lower() for value in _expectation(case, "expected_entities_any", []) if str(value).strip()]
    if not expected_entities:
        return True
    return any(entity in text for entity in expected_entities)


def _claim_verification_state(claim: Dict[str, Any]) -> str:
    explicit = str(claim.get("verification_state") or "").strip().lower()
    if explicit in {"confirmed", "supported", "directional", "inferred", "conflicted", "open_question"}:
        return explicit
    status = str(claim.get("status") or "").strip().lower()
    if status == "confirmed":
        return "confirmed"
    if status == "verified":
        return "supported"
    if status == "directional":
        return "directional"
    if status == "disputed":
        return "conflicted"
    evidence_ids = claim.get("supporting_evidence_ids") or claim.get("evidence_ids") or []
    return "inferred" if evidence_ids else "open_question"


def _claim_support_ids(claim: Dict[str, Any]) -> List[str]:
    values = claim.get("supporting_evidence_ids") or claim.get("evidence_ids") or []
    support_ids: List[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in support_ids:
            support_ids.append(text)
    return support_ids


def _delta_token_overlap(expected_question: str, actual_question: str) -> float:
    expected_tokens = {
        token for token in re.findall(r"[a-z0-9][a-z0-9_-]+|[\u4e00-\u9fff]{1,}", str(expected_question or "").lower()) if len(token) >= 2
    }
    actual_tokens = {
        token for token in re.findall(r"[a-z0-9][a-z0-9_-]+|[\u4e00-\u9fff]{1,}", str(actual_question or "").lower()) if len(token) >= 2
    }
    if not expected_tokens:
        return 0.0
    return len(expected_tokens & actual_tokens) / float(len(expected_tokens))


def score_precision(case: Dict[str, Any], bundle: Dict[str, Any]) -> Dict[str, Any]:
    assets = bundle.get("assets") or {}
    top_evidence = _ranked_evidence(assets.get("evidence") or [])[:5]
    matched_count = sum(1 for item in top_evidence if _evidence_matches_case(item, case))
    off_topic_count = len(top_evidence) - matched_count
    official_domains_any = [
        _normalized_domain(item)
        for item in _expectation(case, "official_domains_any", [])
        if _normalized_domain(item)
    ]
    official_count = sum(1 for item in top_evidence if _is_official_evidence(item, official_domains_any))
    high_quality_count = sum(1 for item in top_evidence if _is_high_quality_evidence(item))
    official_ratio = round(official_count / max(1, len(top_evidence)), 2)
    high_quality_ratio = round(high_quality_count / max(1, len(top_evidence)), 2)
    passed = bool(top_evidence) and off_topic_count <= int(_expectation(case, "allow_off_topic_top5", 0)) and official_ratio >= float(
        _expectation(case, "min_top5_official_ratio", 0.4)
    ) and high_quality_ratio >= float(_expectation(case, "min_top5_high_quality_ratio", 0.6))
    return {
        "passed": passed,
        "metrics": {
            "top5_count": len(top_evidence),
            "top5_matched_count": matched_count,
            "top5_off_topic_count": off_topic_count,
            "top5_official_ratio": official_ratio,
            "top5_high_quality_ratio": high_quality_ratio,
        },
    }


def score_claim_support(case: Dict[str, Any], bundle: Dict[str, Any]) -> Dict[str, Any]:
    assets = bundle.get("assets") or {}
    formal_ids = {
        str(item.get("id") or "").strip()
        for item in (assets.get("evidence") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip() and _is_formal_evidence(item)
    }
    supported_claim_ids: List[str] = []
    unsupported_claim_ids: List[str] = []
    for claim in assets.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("id") or "").strip()
        if not claim_id:
            continue
        support_ids = set(_claim_support_ids(claim))
        verification_state = _claim_verification_state(claim)
        if verification_state in {"supported", "confirmed"} and support_ids & formal_ids:
            supported_claim_ids.append(claim_id)
        else:
            unsupported_claim_ids.append(claim_id)
    min_supported_claims = int(_expectation(case, "min_supported_claims", 3))
    passed = len(supported_claim_ids) >= min_supported_claims
    return {
        "passed": passed,
        "metrics": {
            "supported_claim_count": len(supported_claim_ids),
            "unsupported_claim_count": len(unsupported_claim_ids),
            "supported_claim_ids": supported_claim_ids,
            "unsupported_claim_ids": unsupported_claim_ids,
        },
    }


def score_report_quality(case: Dict[str, Any], bundle: Dict[str, Any]) -> Dict[str, Any]:
    assets = bundle.get("assets") or {}
    report = assets.get("report") or {}
    formal_evidence = [item for item in (assets.get("evidence") or []) if isinstance(item, dict) and _is_formal_evidence(item)]
    formal_domains = {
        _normalized_domain(item.get("source_domain") or item.get("source_url"))
        for item in formal_evidence
        if _normalized_domain(item.get("source_domain") or item.get("source_url"))
    }
    claim_support = score_claim_support(case, bundle)
    passed = bool(str(report.get("markdown") or "").strip())
    passed = passed and len(formal_evidence) >= int(_expectation(case, "min_formal_evidence", 5))
    passed = passed and len(formal_domains) >= int(_expectation(case, "min_formal_domains", 3))
    passed = passed and int(claim_support["metrics"]["supported_claim_count"]) >= int(_expectation(case, "min_supported_claims", 3))
    return {
        "passed": passed,
        "metrics": {
            "formal_evidence_count": len(formal_evidence),
            "formal_domain_count": len(formal_domains),
            "traceable_claim_count": int(claim_support["metrics"]["supported_claim_count"]),
            "report_stage": str(report.get("stage") or ""),
        },
    }


def score_delta_usefulness(case: Dict[str, Any], bundle: Dict[str, Any]) -> Dict[str, Any]:
    delta_question = str(case.get("delta_question") or "").strip()
    if not delta_question:
        return {"passed": True, "skipped": True, "metrics": {"delta_expected": False}}

    job = bundle.get("job") or {}
    assets = bundle.get("assets") or {}
    session = bundle.get("chat_session") or {}
    active_version_id = str(job.get("active_report_version_id") or job.get("report_version_id") or "").strip()
    stable_version_id = str(job.get("stable_report_version_id") or "").strip()
    active_snapshot = next(
        (
            item
            for item in (assets.get("report_versions") or [])
            if isinstance(item, dict) and str(item.get("version_id") or "").strip() == active_version_id
        ),
        {},
    )
    latest_assistant = next(
        (
            item
            for item in reversed(session.get("messages") or [])
            if isinstance(item, dict) and str(item.get("role") or "").strip() == "assistant"
        ),
        {},
    )
    draft_version_id = str(latest_assistant.get("draft_version_id") or "").strip()
    generated_from_question = str(
        active_snapshot.get("generated_from_question") or (assets.get("report") or {}).get("generated_from_question") or ""
    ).strip()
    question_overlap = round(_delta_token_overlap(delta_question, generated_from_question), 2)
    created_new_draft = bool(active_version_id and stable_version_id and active_version_id != stable_version_id)
    metadata_present = bool(draft_version_id and latest_assistant.get("requires_finalize"))
    passed = created_new_draft and metadata_present and question_overlap >= 0.35
    return {
        "passed": passed,
        "skipped": False,
        "metrics": {
            "delta_expected": True,
            "active_version_id": active_version_id,
            "stable_version_id": stable_version_id,
            "created_new_draft": created_new_draft,
            "assistant_metadata_present": metadata_present,
            "question_overlap": question_overlap,
        },
    }


def evaluate_case(case: Dict[str, Any], bundle: Dict[str, Any]) -> Dict[str, Any]:
    precision = score_precision(case, bundle)
    claim_support = score_claim_support(case, bundle)
    report_quality = score_report_quality(case, bundle)
    delta_usefulness = score_delta_usefulness(case, bundle)
    scores = {
        "precision": precision,
        "claim_support": claim_support,
        "report_quality": report_quality,
        "delta_usefulness": delta_usefulness,
    }
    overall_passed = all(section.get("passed") for section in scores.values() if not section.get("skipped"))
    return {
        "case_id": case["id"],
        "topic": case.get("topic"),
        "language": case.get("language"),
        "scenario": case.get("scenario"),
        "passed": overall_passed,
        "scores": scores,
    }


def run_benchmark(
    cases_path: Path | str = DEFAULT_CASES_PATH,
    results_path: Path | str = DEFAULT_RESULTS_PATH,
    require_all_cases: bool = False,
    minimum_scored_cases: int = 1,
) -> Dict[str, Any]:
    cases = load_benchmark_cases(cases_path)
    result_by_case = load_benchmark_results(results_path)
    case_results: List[Dict[str, Any]] = []
    missing_case_ids: List[str] = []
    for case in cases:
        case_id = str(case.get("id") or "").strip()
        bundle = result_by_case.get(case_id)
        if not bundle:
            missing_case_ids.append(case_id)
            continue
        case_results.append(evaluate_case(case, bundle))

    category_totals = {"precision": 0, "claim_support": 0, "report_quality": 0, "delta_usefulness": 0}
    category_passes = {"precision": 0, "claim_support": 0, "report_quality": 0, "delta_usefulness": 0}
    for result in case_results:
        for name, section in result["scores"].items():
            if section.get("skipped"):
                continue
            category_totals[name] += 1
            if section.get("passed"):
                category_passes[name] += 1

    scored_case_count = len(case_results)
    passed_case_count = sum(1 for item in case_results if item.get("passed"))
    summary = {
        "total_case_count": len(cases),
        "scored_case_count": scored_case_count,
        "missing_case_count": len(missing_case_ids),
        "missing_case_ids": missing_case_ids,
        "passed_case_count": passed_case_count,
        "failed_case_count": max(0, scored_case_count - passed_case_count),
        "section_pass_rates": {
            key: round(category_passes[key] / category_totals[key], 2) if category_totals[key] else None
            for key in category_totals
        },
    }
    overall_passed = scored_case_count >= int(minimum_scored_cases)
    overall_passed = overall_passed and all(item.get("passed") for item in case_results)
    if require_all_cases and missing_case_ids:
        overall_passed = False
    return {
        "passed": overall_passed,
        "summary": summary,
        "cases": case_results,
    }


def render_markdown_report(report: Dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Research Quality Benchmark",
        "",
        f"- Overall: {'PASS' if report['passed'] else 'FAIL'}",
        f"- Cases: {summary['scored_case_count']} scored / {summary['total_case_count']} total",
        f"- Missing cases: {summary['missing_case_count']}",
        "",
        "## Section pass rates",
    ]
    for key, value in summary["section_pass_rates"].items():
        percent = "n/a" if value is None else f"{int(round(value * 100))}%"
        lines.append(f"- {key}: {percent}")
    if summary["missing_case_ids"]:
        lines.extend(
            [
                "",
                "## Missing cases",
                ", ".join(summary["missing_case_ids"]),
            ]
        )
    lines.extend(
        [
            "",
            "## Case results",
            "| Case | Overall | Precision | Claim support | Report quality | Delta usefulness |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for result in report["cases"]:
        scores = result["scores"]
        lines.append(
            "| {case_id} | {overall} | {precision} | {claim_support} | {report_quality} | {delta} |".format(
                case_id=result["case_id"],
                overall="PASS" if result["passed"] else "FAIL",
                precision="PASS" if scores["precision"]["passed"] else "FAIL",
                claim_support="PASS" if scores["claim_support"]["passed"] else "FAIL",
                report_quality="PASS" if scores["report_quality"]["passed"] else "FAIL",
                delta="SKIP" if scores["delta_usefulness"].get("skipped") else ("PASS" if scores["delta_usefulness"]["passed"] else "FAIL"),
            )
        )
    return "\n".join(lines)


def save_json_report(report: Dict[str, Any], path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _slugify(value: Any) -> str:
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", str(value or "").strip().lower()).strip("-")
    return text or "benchmark"


def _case_entities(case: Dict[str, Any]) -> List[str]:
    entities = [str(item).strip() for item in _expectation(case, "expected_entities_any", []) if str(item).strip()]
    if entities:
        return entities[:4]
    topic = str(case.get("topic") or "").strip()
    return [topic] if topic else [case["id"]]


def _scenario_source_types(case: Dict[str, Any]) -> List[str]:
    scenario = str(case.get("scenario") or "").strip()
    return list(SCENARIO_SOURCE_TYPES.get(scenario, ("web", "article", "community", "documentation", "review")))


def _scenario_market_step(case: Dict[str, Any]) -> str:
    scenario = str(case.get("scenario") or "").strip()
    return SCENARIO_STEP.get(scenario, "market-trends")


def _evidence_title(case: Dict[str, Any], index: int, entity: str, source_type: str) -> str:
    topic = str(case.get("topic") or "").strip()
    if source_type == "pricing":
        return f"{entity} pricing and packaging for {topic}"
    if source_type == "documentation":
        return f"{entity} workflow documentation for {topic}"
    if source_type == "community":
        return f"{entity} user discussion on {topic}"
    if source_type == "review":
        return f"{entity} hands-on review for {topic}"
    if index == 1:
        return f"{entity} official overview for {topic}"
    return f"{entity} research signal for {topic}"


def _evidence_summary(case: Dict[str, Any], entity: str, source_type: str, index: int) -> str:
    topic = str(case.get("topic") or "").strip()
    scenario = str(case.get("scenario") or "").strip()
    if scenario == "pricing_and_business_model":
        return f"{entity} explains pricing, packaging, and purchase considerations for {topic}."
    if scenario == "product_experience_teardown":
        return f"{entity} describes workflow details, product friction, and experience tradeoffs for {topic}."
    if scenario == "reviews_and_sentiment":
        return f"{entity} captures user praise, complaints, and tradeoffs for {topic}."
    if scenario == "competitor_landscape":
        return f"{entity} helps compare the competitive landscape and differentiation for {topic}."
    if scenario == "acquisition_and_distribution":
        return f"{entity} highlights distribution signals, growth loops, and adoption cues for {topic}."
    if scenario == "opportunities_and_risks":
        return f"{entity} surfaces execution constraints, opportunity windows, and decision risks for {topic}."
    if scenario == "user_jobs_and_pains":
        return f"{entity} captures real usage context, high-frequency jobs, and pain points for {topic}."
    return f"{entity} provides market signals, product context, and benchmark evidence for {topic}."


def _evidence_quote(case: Dict[str, Any], entity: str, index: int) -> str:
    scenario = str(case.get("scenario") or "").strip()
    topic = str(case.get("topic") or "").strip()
    templates = {
        "market_trends": f"{entity} shows that {topic} is gaining traction but still depends on stronger repeat-use behavior.",
        "user_jobs_and_pains": f"{entity} shows that users still hit repeated friction and decision anxiety around {topic}.",
        "competitor_landscape": f"{entity} makes the direct-vs-substitute split clearer for {topic}.",
        "product_experience_teardown": f"{entity} shows where the experience wins and where workflow friction still blocks adoption in {topic}.",
        "reviews_and_sentiment": f"{entity} captures why users praise some moments in {topic} but still complain about reliability and value.",
        "pricing_and_business_model": f"{entity} shows that pricing value depends on packaging, workflow depth, and team rollout for {topic}.",
        "acquisition_and_distribution": f"{entity} shows that growth depends on repeatable channels rather than one-off spikes for {topic}.",
        "opportunities_and_risks": f"{entity} shows that {topic} still needs stronger proof before teams scale rollout.",
    }
    return templates.get(scenario, f"{entity} provides directly relevant evidence for {topic}.")


def _source_url(domain: str, source_type: str, case: Dict[str, Any], index: int) -> str:
    slug = _slugify(case.get("topic"))
    if source_type == "pricing":
        return f"https://{domain}/pricing/{slug}/"
    if source_type == "documentation":
        return f"https://{domain}/docs/{slug}/"
    if source_type == "community":
        return f"https://{domain}/community/{slug}/{index}"
    if source_type == "review":
        return f"https://{domain}/reviews/{slug}/{index}"
    return f"https://{domain}/{slug}/{index}"


def build_sample_bundle(case: Dict[str, Any]) -> Dict[str, Any]:
    case_id = str(case["id"])
    job_id = f"{case_id}-sample-job"
    topic = str(case.get("topic") or case_id)
    entities = _case_entities(case)
    scenario = str(case.get("scenario") or "").strip()
    market_step = _scenario_market_step(case)
    domains = [_normalized_domain(item) for item in _expectation(case, "official_domains_any", []) if _normalized_domain(item)]
    while len(domains) < 3:
        domains.append(f"{_slugify(entities[0])}-{len(domains)+1}.example.com")
    source_types = _scenario_source_types(case)

    evidence: List[Dict[str, Any]] = []
    for index in range(5):
        entity = entities[min(index, len(entities) - 1)]
        domain = domains[min(index, len(domains) - 1)]
        source_type = source_types[min(index, len(source_types) - 1)]
        tier = "t1" if index in {0, 1, 4} else "t2"
        authority = round(0.95 - (index * 0.03), 2)
        freshness = round(0.9 - (index * 0.02), 2)
        confidence = round(0.9 - (index * 0.025), 2)
        summary = _evidence_summary(case, entity, source_type, index + 1)
        quote = _evidence_quote(case, entity, index + 1)
        evidence.append(
            {
                "id": f"e{index + 1}",
                "source_url": _source_url(domain, source_type, case, index + 1),
                "source_domain": domain,
                "source_type": source_type,
                "source_tier": tier,
                "title": _evidence_title(case, index + 1, entity, source_type),
                "summary": summary,
                "quote": quote,
                "normalized_fact": quote,
                "authority_score": authority,
                "freshness_score": freshness,
                "confidence": confidence,
            }
        )

    claims = [
        {
            "id": "claim-1",
            "claim_text": f"{topic} should be framed around the strongest repeat-use value signal rather than broad feature coverage.",
            "market_step": market_step,
            "supporting_evidence_ids": ["e1", "e2"],
            "verification_state": "supported",
            "status": "verified",
        },
        {
            "id": "claim-2",
            "claim_text": f"The clearest competitive or workflow difference in {topic} comes from execution depth and decision confidence, not surface messaging.",
            "market_step": market_step,
            "supporting_evidence_ids": ["e2", "e3"],
            "verification_state": "supported",
            "status": "verified",
        },
        {
            "id": "claim-3",
            "claim_text": f"PM decisions for {topic} should prioritize provable user value, traceable evidence, and rollout constraints.",
            "market_step": "recommendations",
            "supporting_evidence_ids": ["e3", "e4", "e5"],
            "verification_state": "supported",
            "status": "verified",
        },
    ]

    delta_question = str(case.get("delta_question") or "").strip()
    if delta_question:
        stable_version_id = f"{job_id}-report-v2"
        active_version_id = f"{job_id}-report-v3"
        report = {
            "markdown": f"## Draft update\n- {topic} now includes a delta draft with additional decision evidence.",
            "stage": "feedback_pending",
            "generated_from_question": delta_question,
        }
        report_versions = [
            {"version_id": stable_version_id, "kind": "final", "generated_from_question": None},
            {"version_id": active_version_id, "kind": "draft", "generated_from_question": delta_question},
        ]
        chat_session = {
            "messages": [
                {
                    "id": "m1",
                    "role": "assistant",
                    "content": f"已补入新的追问证据，并生成 {active_version_id} 草稿。",
                    "answer_mode": "delta_draft",
                    "draft_version_id": active_version_id,
                    "requires_finalize": True,
                }
            ]
        }
        report_readiness = "draft"
        report_quality_score = 90.0
    else:
        stable_version_id = active_version_id = f"{job_id}-report-v2"
        report = {
            "markdown": f"## Stable report\n- {topic} benchmark bundle contains traceable findings and formal evidence.",
            "stage": "final",
        }
        report_versions = [{"version_id": active_version_id, "kind": "final", "generated_from_question": None}]
        chat_session = {"messages": []}
        report_readiness = "stable"
        report_quality_score = 93.0

    return {
        "case_id": case_id,
        "job": {
            "id": job_id,
            "report_version_id": active_version_id,
            "active_report_version_id": active_version_id,
            "stable_report_version_id": stable_version_id,
            "quality_score_summary": {
                "report_readiness": report_readiness,
                "report_quality_score": report_quality_score,
            },
        },
        "assets": {
            "claims": claims,
            "evidence": evidence,
            "report": report,
            "report_versions": report_versions,
        },
        "chat_session": chat_session,
    }


def build_sample_result_catalog(cases_path: Path | str = DEFAULT_CASES_PATH) -> List[Dict[str, Any]]:
    return [build_sample_bundle(case) for case in load_benchmark_cases(cases_path)]
