from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ApiSchemaModel(BaseModel):
    class Config:
        extra = "allow"


class RuntimeBackupConfigDto(ApiSchemaModel):
    label: str = ""
    base_url: str
    api_key: Optional[str] = None


class RuntimeLlmProfileDto(ApiSchemaModel):
    profile_id: str = ""
    label: str = ""
    provider: Optional[Literal["minimax", "openai_compatible"]] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    quality_tier: Optional[str] = None


class RuntimeRetrievalProfileDto(ApiSchemaModel):
    profile_id: str = ""
    label: str = ""
    primary_search_provider: Optional[str] = None
    fallback_search_providers: List[str] = Field(default_factory=list)
    reranker: Optional[str] = None
    extractor: Optional[str] = None
    writer_model: Optional[str] = None
    official_domains: List[str] = Field(default_factory=list)
    negative_keywords: List[str] = Field(default_factory=list)
    alias_expansion: bool = True
    official_source_bias: bool = True


class RuntimeQualityPolicyDto(ApiSchemaModel):
    profile_id: str = ""
    min_report_claims: Optional[int] = None
    min_formal_evidence: Optional[int] = None
    min_formal_domains: Optional[int] = None
    require_official_coverage: Optional[bool] = None
    auto_finalize: Optional[bool] = None
    auto_create_draft_on_delta: Optional[bool] = None


class RuntimeDebugPolicyDto(ApiSchemaModel):
    auto_open_mode: Optional[Literal["off", "debug_only", "always"]] = None
    browser_auto_open: Optional[bool] = None
    verbose_diagnostics: Optional[bool] = None
    collect_raw_pages: Optional[bool] = None


class RuntimeConfigDto(ApiSchemaModel):
    profile_id: Optional[str] = None
    provider: Literal["minimax", "openai_compatible"] = "minimax"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    timeout_seconds: Optional[float] = None
    backup_configs: List[RuntimeBackupConfigDto] = Field(default_factory=list)
    llm_profile: Optional[RuntimeLlmProfileDto] = None
    retrieval_profile: Optional[RuntimeRetrievalProfileDto] = None
    quality_policy: Optional[RuntimeQualityPolicyDto] = None
    debug_policy: Optional[RuntimeDebugPolicyDto] = None


class CreateResearchJobDto(ApiSchemaModel):
    topic: str
    industry_template: Literal["industrial_design", "product_design", "saas", "ai_product", "internet", "ecommerce"]
    research_mode: Literal["standard", "deep"] = "standard"
    depth_preset: Literal["light", "standard", "deep"] = "standard"
    failure_policy: Literal["graceful", "strict"] = "graceful"
    workflow_command: Literal[
        "deep_general_scan",
        "competitor_war_room",
        "user_voice_first",
        "pricing_growth_audit",
        "launch_readiness",
    ] = "deep_general_scan"
    project_memory: str = ""
    max_sources: int = 45
    max_subtasks: int = 6
    time_budget_minutes: int = 25
    max_competitors: int = 5
    review_sample_target: int = 150
    geo_scope: List[str] = Field(default_factory=list)
    language: str = "zh-CN"
    output_locale: str = "zh-CN"
    runtime_config: Optional[RuntimeConfigDto] = None


class CancelResearchJobDto(ApiSchemaModel):
    reason: Optional[str] = None


class FinalizeReportDto(ApiSchemaModel):
    source_version_id: Optional[str] = None


class TaskLogDto(ApiSchemaModel):
    id: str
    timestamp: str
    level: Literal["info", "warning", "error"]
    message: str


class VisitedSourceDto(ApiSchemaModel):
    url: str
    title: str
    source_type: str
    snippet: str = ""
    opened_in_browser: Optional[bool] = None
    query: Optional[str] = None
    wave: Optional[str] = None


class ResearchQueryRetryAttemptDto(ApiSchemaModel):
    query: str
    status: Optional[Literal["zero_results", "results_found", "search_error"]] = None
    search_result_count: Optional[int] = None


class ResearchQuerySummaryDto(ApiSchemaModel):
    query: str
    status: Optional[Literal["running", "zero_results", "filtered", "evidence_added", "search_error"]] = None
    search_result_count: Optional[int] = None
    evidence_added: Optional[int] = None
    retry_queries: List[str] = Field(default_factory=list)
    effective_query: Optional[str] = None
    retry_attempts: List[ResearchQueryRetryAttemptDto] = Field(default_factory=list)


class ResearchRoundDiagnosticsDto(ApiSchemaModel):
    search_errors: int = 0
    duplicates: int = 0
    low_signal: int = 0
    host_quota: int = 0
    fetch_fallbacks: int = 0
    browser_opens: int = 0
    rejected: int = 0
    admitted: int = 0
    negative_keyword_blocks: int = 0


class ResearchRoundPipelineDto(ApiSchemaModel):
    retrieval_profile_id: Optional[str] = None
    entity_terms: List[str] = Field(default_factory=list)
    official_domains: List[str] = Field(default_factory=list)
    negative_keywords: List[str] = Field(default_factory=list)
    planned_query_count: int = 0
    recalled_result_count: int = 0
    reranked_result_count: int = 0
    fetch_attempt_count: int = 0
    extracted_page_count: int = 0
    normalized_evidence_count: int = 0
    official_hit_count: int = 0
    negative_keyword_block_count: int = 0


class CoverageStatusDto(ApiSchemaModel):
    required_query_tags: List[str] = Field(default_factory=list)
    covered_query_tags: List[str] = Field(default_factory=list)
    missing_required: List[str] = Field(default_factory=list)
    query_tag_counts: Dict[str, int] = Field(default_factory=dict)
    target_sources: Optional[int] = None
    skill_runtime_active: Optional[bool] = None
    skill_themes: List[str] = Field(default_factory=list)
    skill_coverage_targets: Dict[str, int] = Field(default_factory=dict)
    missing_skill_targets: Dict[str, int] = Field(default_factory=dict)


class ResearchRoundDto(ApiSchemaModel):
    wave: Optional[int] = None
    key: Optional[str] = None
    label: Optional[str] = None
    queries: List[str] = Field(default_factory=list)
    query_summaries: List[ResearchQuerySummaryDto] = Field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    evidence_before: Optional[int] = None
    evidence_added: Optional[int] = None
    result_count: Optional[int] = None
    diagnostics: Optional[ResearchRoundDiagnosticsDto] = None
    pipeline: Optional[ResearchRoundPipelineDto] = None
    coverage: Dict[str, Any] = Field(default_factory=dict)
    gaps: Dict[str, Any] = Field(default_factory=dict)


class PhaseProgressDto(ApiSchemaModel):
    phase: str = ""
    label: str = ""
    progress: float = 0
    status: Literal["pending", "running", "completed"] = "pending"


class RuntimeSummaryDto(ApiSchemaModel):
    provider: str = ""
    model: str = ""
    llm_enabled: bool = False
    validation_status: str = "unknown"
    validation_message: str = ""
    browser_mode: str = ""
    browser_available: bool = False


class BackgroundProcessDto(ApiSchemaModel):
    pid: Optional[int] = None
    active: Optional[bool] = None
    entrypoint: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    cancel_requested_at: Optional[str] = None


class ResearchTaskDto(ApiSchemaModel):
    id: str
    category: str = ""
    title: str = ""
    brief: str = ""
    market_step: str = ""
    command_id: Optional[str] = None
    command_label: Optional[str] = None
    skill_packs: List[str] = Field(default_factory=list)
    orchestration_notes: Optional[str] = None
    covered_steps: List[str] = Field(default_factory=list)
    status: str
    source_count: int
    retry_count: int = 0
    progress: Optional[int] = None
    agent_name: Optional[str] = None
    current_action: Optional[str] = None
    current_url: Optional[str] = None
    browser_mode: Optional[str] = None
    browser_available: Optional[bool] = None
    search_queries: List[str] = Field(default_factory=list)
    visited_sources: List[VisitedSourceDto] = Field(default_factory=list)
    research_rounds: List[ResearchRoundDto] = Field(default_factory=list)
    skill_runtime: Dict[str, Any] = Field(default_factory=dict)
    coverage_status: Optional[CoverageStatusDto] = None
    logs: List[TaskLogDto] = Field(default_factory=list)
    latest_error: Optional[str] = None


class ResearchJobDto(ApiSchemaModel):
    id: str
    topic: str
    industry_template: str
    research_mode: str
    depth_preset: str
    failure_policy: Optional[str] = None
    completion_mode: Optional[str] = None
    workflow_command: Optional[str] = None
    workflow_label: Optional[str] = None
    project_memory: Optional[str] = None
    orchestration_summary: Optional[str] = None
    max_sources: Optional[int] = None
    max_subtasks: Optional[int] = None
    max_competitors: Optional[int] = None
    review_sample_target: Optional[int] = None
    time_budget_minutes: Optional[int] = None
    status: str
    overall_progress: float
    current_phase: str
    eta_seconds: int
    source_count: int
    competitor_count: int
    completed_task_count: int
    running_task_count: int
    failed_task_count: int
    claims_count: int
    report_version_id: Optional[str] = None
    active_report_version_id: Optional[str] = None
    stable_report_version_id: Optional[str] = None
    retrieval_profile_id: Optional[str] = None
    quality_score_summary: Dict[str, Any] = Field(default_factory=dict)
    phase_progress: List[PhaseProgressDto] = Field(default_factory=list)
    tasks: List[ResearchTaskDto] = Field(default_factory=list)
    activity_log: List[TaskLogDto] = Field(default_factory=list)
    runtime_summary: Optional[RuntimeSummaryDto] = None
    latest_error: Optional[str] = None
    latest_warning: Optional[str] = None
    cancel_requested: bool = False
    cancellation_reason: Optional[str] = None
    execution_mode: Optional[str] = None
    background_process: Optional[BackgroundProcessDto] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None


class HealthStatusDto(ApiSchemaModel):
    status: str
    active_job_count: int
    active_detached_worker_count: int
    runtime_configured: bool
    timestamp: str


class EvidenceDto(ApiSchemaModel):
    id: str
    task_id: str
    market_step: str
    source_url: str
    source_domain: Optional[str] = None
    source_type: str
    source_tier: Optional[str] = None
    source_tier_label: Optional[str] = None
    citation_label: Optional[str] = None
    title: str
    published_at: Optional[str] = None
    captured_at: str
    quote: str
    summary: str
    extracted_fact: str
    normalized_fact: Optional[str] = None
    raw_support: Optional[str] = None
    extraction_method: Optional[str] = None
    entity_ids: List[str] = Field(default_factory=list)
    freshness_bucket: Optional[str] = None
    reliability_scores: Dict[str, float] = Field(default_factory=dict)
    authority_score: float
    freshness_score: float
    confidence: float
    injection_risk: float
    tags: List[str] = Field(default_factory=list)
    competitor_name: Optional[str] = None


class ClaimDto(ApiSchemaModel):
    id: str
    claim_text: str
    market_step: str
    evidence_ids: List[str] = Field(default_factory=list)
    counter_evidence_ids: List[str] = Field(default_factory=list)
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    contradicting_evidence_ids: List[str] = Field(default_factory=list)
    confidence: float
    status: str
    verification_state: Optional[Literal["supported", "inferred", "conflicted", "open_question"]] = None
    confidence_reason: Optional[str] = None
    decision_impact: Optional[str] = None
    caveats: List[str] = Field(default_factory=list)
    competitor_ids: List[str] = Field(default_factory=list)
    priority: Optional[str] = None
    actionability_score: Optional[float] = None
    last_verified_at: Optional[str] = None


class ReportFeedbackNoteDto(ApiSchemaModel):
    question: Optional[str] = None
    feedback: Optional[str] = None
    response: Optional[str] = None
    action: Optional[str] = None
    claim_id: Optional[str] = None
    created_at: str


class ReportDecisionSnapshotDto(ApiSchemaModel):
    readiness: str
    readiness_reason: Optional[str] = None
    high_confidence_claims: Optional[int] = None
    inferred_claims: Optional[int] = None
    disputed_claims: Optional[int] = None
    open_questions: Optional[int] = None
    unique_domains: Optional[int] = None
    next_step: Optional[str] = None


class ReportQualityGateDto(ApiSchemaModel):
    pending: Optional[bool] = None
    passed: Optional[bool] = None
    reason: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    checked_at: Optional[str] = None
    policy_version: Optional[str] = None
    thresholds: Dict[str, float] = Field(default_factory=dict)
    metrics: Dict[str, float] = Field(default_factory=dict)


class ReportSupportSnapshotDto(ApiSchemaModel):
    claim_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    source_domains: List[str] = Field(default_factory=list)


class ReportVersionDiffSummaryDto(ApiSchemaModel):
    summary: Optional[str] = None
    added_claim_ids: List[str] = Field(default_factory=list)
    removed_claim_ids: List[str] = Field(default_factory=list)
    added_evidence_ids: List[str] = Field(default_factory=list)
    removed_evidence_ids: List[str] = Field(default_factory=list)
    changed_sections: List[str] = Field(default_factory=list)


class ReportAssetDto(ApiSchemaModel):
    markdown: str
    board_brief_markdown: Optional[str] = None
    executive_memo_markdown: Optional[str] = None
    appendix_markdown: Optional[str] = None
    conflict_summary_markdown: Optional[str] = None
    claim_ids: Optional[List[str]] = None
    evidence_ids: Optional[List[str]] = None
    source_domains: Optional[List[str]] = None
    decision_snapshot: Optional[ReportDecisionSnapshotDto] = None
    generated_at: str
    updated_at: Optional[str] = None
    stage: Optional[str] = None
    section_count: Optional[int] = None
    evidence_count: Optional[int] = None
    revision_count: Optional[int] = None
    feedback_count: Optional[int] = None
    feedback_notes: List[ReportFeedbackNoteDto] = Field(default_factory=list)
    draft_markdown: Optional[str] = None
    long_report_ready: Optional[bool] = None
    quality_gate: Optional[ReportQualityGateDto] = None
    formal_claim_count: Optional[int] = None
    formal_evidence_count: Optional[int] = None
    context_only_evidence_count: Optional[int] = None
    kind: Optional[Literal["draft", "final"]] = None
    parent_version_id: Optional[str] = None
    change_reason: Optional[str] = None
    generated_from_question: Optional[str] = None
    support_snapshot: Optional[ReportSupportSnapshotDto] = None
    diff_summary: Optional[ReportVersionDiffSummaryDto] = None


class ReportVersionDto(ApiSchemaModel):
    version_id: str
    version_number: Optional[int] = None
    label: Optional[str] = None
    stage: Optional[str] = None
    kind: Optional[Literal["draft", "final"]] = None
    parent_version_id: Optional[str] = None
    change_reason: Optional[str] = None
    generated_from_question: Optional[str] = None
    markdown: str
    board_brief_markdown: Optional[str] = None
    executive_memo_markdown: Optional[str] = None
    appendix_markdown: Optional[str] = None
    conflict_summary_markdown: Optional[str] = None
    claim_ids: Optional[List[str]] = None
    evidence_ids: Optional[List[str]] = None
    source_domains: Optional[List[str]] = None
    decision_snapshot: Optional[ReportDecisionSnapshotDto] = None
    generated_at: str
    updated_at: Optional[str] = None
    section_count: Optional[int] = None
    evidence_count: Optional[int] = None
    feedback_count: Optional[int] = None
    revision_count: Optional[int] = None
    long_report_ready: Optional[bool] = None
    quality_gate: Optional[ReportQualityGateDto] = None
    support_snapshot: Optional[ReportSupportSnapshotDto] = None
    diff_summary: Optional[ReportVersionDiffSummaryDto] = None


class CompetitorHighlightDto(ApiSchemaModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    source_type_label: Optional[str] = None
    source_domain: Optional[str] = None
    source_tier_label: Optional[str] = None
    citation_label: Optional[str] = None
    market_step: Optional[str] = None


class CompetitorDto(ApiSchemaModel):
    name: Optional[str] = None
    category: Optional[str] = None
    positioning: Optional[str] = None
    pricing: Optional[str] = None
    differentiation: Optional[str] = None
    coverage_gap: Optional[str] = None
    evidence_count: int = 0
    source_count: int = 0
    source_domains: List[str] = Field(default_factory=list)
    source_types: List[str] = Field(default_factory=list)
    key_sources: List[str] = Field(default_factory=list)
    highlights: List[CompetitorHighlightDto] = Field(default_factory=list)


class ArtifactFileDto(ApiSchemaModel):
    name: str
    path: str
    download_url: str
    content_type: str


class ResearchAssetsDto(ApiSchemaModel):
    report: ReportAssetDto
    claims: List[ClaimDto] = Field(default_factory=list)
    evidence: List[EvidenceDto] = Field(default_factory=list)
    competitors: List[CompetitorDto] = Field(default_factory=list)
    market_map: Dict[str, Any] = Field(default_factory=dict)
    progress_snapshot: Dict[str, Any] = Field(default_factory=dict)
    report_versions: List[ReportVersionDto] = Field(default_factory=list)
    artifacts: List[ArtifactFileDto] = Field(default_factory=list)


class ReportVersionDiffDto(ApiSchemaModel):
    job_id: str
    version_id: str
    base_version_id: str
    summary: str
    version: Optional[ReportVersionDto] = None
    base_version: Optional[ReportVersionDto] = None
    diff_markdown: Optional[str] = None
    added_claim_ids: List[str] = Field(default_factory=list)
    removed_claim_ids: List[str] = Field(default_factory=list)
    added_evidence_ids: List[str] = Field(default_factory=list)
    removed_evidence_ids: List[str] = Field(default_factory=list)
