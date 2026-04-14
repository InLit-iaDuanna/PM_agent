export type IndustryTemplate =
  | "industrial_design"
  | "product_design"
  | "saas"
  | "ai_product"
  | "internet"
  | "ecommerce";

export type ResearchMode = "standard" | "deep";
export type DepthPreset = "light" | "standard" | "deep";
export type FailurePolicy = "graceful" | "strict";
export type CompletionMode = "formal" | "diagnostic";
export type ValidationStatus = "unknown" | "valid" | "invalid";
export type RuntimeProvider = "minimax" | "openai_compatible";
export type ChatAnswerMode = "report_pending" | "report_context" | "delta_requested" | "delta_draft" | "delta_failed";
export type ClaimVerificationState = "supported" | "inferred" | "conflicted" | "open_question";
export type ReportVersionKind = "draft" | "final";
export type WorkflowCommandId =
  | "deep_general_scan"
  | "competitor_war_room"
  | "user_voice_first"
  | "pricing_growth_audit"
  | "launch_readiness";
export type JobStatus =
  | "queued"
  | "planning"
  | "researching"
  | "verifying"
  | "synthesizing"
  | "completed"
  | "failed"
  | "cancelled";

export type ResearchPhase =
  | "scoping"
  | "planning"
  | "collecting"
  | "verifying"
  | "synthesizing"
  | "finalizing";

export type TaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ClaimStatus = "verified" | "disputed" | "inferred";
export type RegistrationMode = "bootstrap" | "invite_only" | "open" | "closed";
export type RegistrationPolicyMode = "default" | "invite_only" | "open" | "closed";

export interface AuthUserRecord {
  id: string;
  email: string;
  display_name?: string;
  role: "admin" | "member";
  is_disabled?: boolean;
  disabled_at?: string;
  disabled_reason?: string;
  created_at?: string;
  last_login_at?: string;
}

export interface RegisterUserDto {
  email: string;
  password: string;
  display_name?: string;
  invite_code?: string;
}

export interface LoginUserDto {
  email: string;
  password: string;
}

export interface AuthSessionRecord {
  user: AuthUserRecord;
}

export interface LogoutResultRecord {
  ok: boolean;
}

export interface CreateInviteDto {
  note?: string;
}

export interface InviteRecord {
  id: string;
  code: string;
  note?: string;
  issued_by_user_id?: string;
  issued_by_email?: string;
  created_at?: string;
  used_at?: string;
  used_by_user_id?: string;
  used_by_email?: string;
  disabled_at?: string;
  disabled_reason?: string;
  active: boolean;
}

export interface UpdateUserRoleDto {
  role: "admin" | "member";
}

export interface AdminResetUserPasswordDto {
  new_password: string;
}

export interface AuthPublicConfigRecord {
  registration_enabled: boolean;
  invite_code_required: boolean;
  first_user_will_be_admin: boolean;
  registration_mode: RegistrationMode;
  registration_mode_source?: "bootstrap" | "default" | "admin_override";
  policy_mode?: RegistrationPolicyMode;
  configured_registration_mode?: RegistrationPolicyMode;
}

export interface UpdateRegistrationPolicyDto {
  registration_mode: RegistrationPolicyMode;
  mode?: RegistrationPolicyMode;
}

export interface SystemVersionOptionRecord {
  ref: string;
  kind: "branch" | "tag";
  commit: string;
  label?: string;
}

export interface SystemUpdateJobRecord {
  job_id: string;
  ref: string;
  use_prod: boolean;
  project_name?: string;
  skip_backup?: boolean;
  skip_pull?: boolean;
  skip_build?: boolean;
  status: "running" | "succeeded" | "failed" | "unknown";
  pid?: number;
  started_at?: string;
  finished_at?: string;
  exit_code?: number;
  log_path?: string;
  command?: string;
}

export interface SystemUpdateStatusRecord {
  supported: boolean;
  can_execute: boolean;
  execution_enabled: boolean;
  reason?: string;
  repo_root: string;
  current_ref: string;
  current_tag?: string;
  current_branch?: string;
  current_commit: string;
  default_ref: string;
  compose_project_name?: string;
  options: SystemVersionOptionRecord[];
  suggested_command: string;
  active_job?: SystemUpdateJobRecord;
  recent_jobs: SystemUpdateJobRecord[];
}

export interface TriggerSystemUpdateDto {
  ref: string;
  use_prod?: boolean;
  project_name?: string;
  skip_backup?: boolean;
  skip_pull?: boolean;
  skip_build?: boolean;
  admin_email?: string;
  admin_password?: string;
  admin_name?: string;
}

export interface ChangePasswordDto {
  current_password: string;
  new_password: string;
}

export interface DeleteAccountDto {
  current_password: string;
}

export interface TaskLogRecord {
  id: string;
  timestamp: string;
  level: "info" | "warning" | "error";
  message: string;
}

export interface VisitedSourceRecord {
  url: string;
  title: string;
  source_type: string;
  snippet: string;
  opened_in_browser?: boolean;
}

export interface ResearchQuerySummaryRecord {
  query: string;
  status: "running" | "zero_results" | "filtered" | "evidence_added" | "search_error";
  search_result_count?: number;
  evidence_added?: number;
  retry_queries?: string[];
  effective_query?: string;
  retry_attempts?: Array<{
    query: string;
    status?: "zero_results" | "results_found" | "search_error";
    search_result_count?: number;
  }>;
}

export interface ResearchRoundRecord {
  wave?: number;
  key?: string;
  label?: string;
  queries?: string[];
  query_summaries?: ResearchQuerySummaryRecord[];
  started_at?: string;
  completed_at?: string;
  evidence_before?: number;
  evidence_added?: number;
  result_count?: number;
  diagnostics?: {
    search_errors?: number;
    duplicates?: number;
    low_signal?: number;
    host_quota?: number;
    fetch_fallbacks?: number;
    browser_opens?: number;
    rejected?: number;
    admitted?: number;
    negative_keyword_blocks?: number;
  };
  pipeline?: {
    retrieval_profile_id?: string;
    entity_terms?: string[];
    official_domains?: string[];
    negative_keywords?: string[];
    planned_query_count?: number;
    recalled_result_count?: number;
    reranked_result_count?: number;
    fetch_attempt_count?: number;
    extracted_page_count?: number;
    normalized_evidence_count?: number;
    official_hit_count?: number;
    negative_keyword_block_count?: number;
  };
  coverage?: Record<string, unknown>;
  gaps?: Record<string, unknown>;
}

export interface RuntimeLlmProfileDto {
  profile_id: string;
  label?: string;
  provider?: RuntimeProvider;
  model?: string;
  base_url?: string;
  quality_tier?: string;
}

export interface RuntimeRetrievalProfileDto {
  profile_id: string;
  label?: string;
  primary_search_provider?: string;
  fallback_search_providers?: string[];
  reranker?: string;
  extractor?: string;
  writer_model?: string;
  official_domains?: string[];
  negative_keywords?: string[];
  alias_expansion?: boolean;
  official_source_bias?: boolean;
}

export interface RuntimeQualityPolicyDto {
  profile_id?: string;
  min_report_claims?: number;
  min_formal_evidence?: number;
  min_formal_domains?: number;
  require_official_coverage?: boolean;
  auto_finalize?: boolean;
  auto_create_draft_on_delta?: boolean;
}

export interface RuntimeDebugPolicyDto {
  auto_open_mode?: "off" | "debug_only" | "always";
  browser_auto_open?: boolean;
  verbose_diagnostics?: boolean;
  collect_raw_pages?: boolean;
}

export interface RuntimeConfigDto {
  profile_id?: string;
  provider: RuntimeProvider;
  api_key?: string;
  base_url?: string;
  model?: string;
  timeout_seconds?: number;
  backup_configs?: RuntimeBackupConfigDto[];
  llm_profile?: RuntimeLlmProfileDto;
  retrieval_profile?: RuntimeRetrievalProfileDto;
  quality_policy?: RuntimeQualityPolicyDto;
  debug_policy?: RuntimeDebugPolicyDto;
}

export interface RuntimeProfileRecord {
  profile_id: string;
  label?: string;
  description?: string;
  quality_mode?: "premium" | "fallback";
  recommended?: boolean;
  runtime_config: RuntimeConfigDto;
  llm_profile?: RuntimeLlmProfileDto;
  retrieval_profile?: RuntimeRetrievalProfileDto;
  quality_policy?: RuntimeQualityPolicyDto;
  debug_policy?: RuntimeDebugPolicyDto;
}

export interface RuntimeBackupConfigDto {
  label?: string;
  base_url: string;
  api_key?: string;
}

export interface RuntimeSummaryRecord {
  provider: RuntimeProvider;
  model: string;
  llm_enabled: boolean;
  validation_status: ValidationStatus;
  validation_message: string;
  browser_mode: string;
  browser_available: boolean;
}

export interface RuntimeStatusRecord {
  provider: RuntimeProvider;
  model: string;
  base_url: string;
  active_base_url?: string;
  timeout_seconds: number;
  configured: boolean;
  api_key_configured: boolean;
  api_key_masked?: string;
  backup_count?: number;
  backup_configs?: RuntimeBackupStatusRecord[];
  source: "saved" | "environment" | "default";
  validation_status: ValidationStatus;
  validation_message: string;
  browser_mode: string;
  browser_available: boolean;
  selected_profile_id: string;
  selected_profile_label?: string;
  available_profiles?: RuntimeProfileRecord[];
  runtime_config: RuntimeConfigDto;
  resolved_runtime_config: RuntimeConfigDto;
  llm_profile?: RuntimeLlmProfileDto;
  retrieval_profile?: RuntimeRetrievalProfileDto;
  quality_policy?: RuntimeQualityPolicyDto;
  debug_policy?: RuntimeDebugPolicyDto;
  updated_at?: string;
}

export interface RuntimeBackupStatusRecord {
  label?: string;
  base_url: string;
  api_key_configured: boolean;
  api_key_masked?: string;
  uses_primary_api_key: boolean;
  priority: number;
  is_active: boolean;
}

export interface RuntimeValidationResultRecord {
  ok: boolean;
  provider: RuntimeProvider;
  model: string;
  message: string;
  browser_mode: string;
  browser_available: boolean;
  selected_profile_id?: string;
}

export interface UpdateRuntimeSettingsDto {
  runtime_config: RuntimeConfigDto;
  replace_api_key?: boolean;
}

export interface ArtifactFileRecord {
  name: string;
  path: string;
  download_url: string;
  content_type: string;
}

export interface CreateResearchJobDto {
  topic: string;
  industry_template: IndustryTemplate;
  research_mode: ResearchMode;
  depth_preset: DepthPreset;
  failure_policy: FailurePolicy;
  workflow_command: WorkflowCommandId;
  project_memory?: string;
  max_sources: number;
  max_subtasks: number;
  time_budget_minutes: number;
  max_competitors: number;
  review_sample_target: number;
  geo_scope: string[];
  language: string;
  output_locale: string;
  runtime_config?: RuntimeConfigDto;
}

export interface CancelResearchJobDto {
  reason?: string;
}

export interface ResearchTaskRecord {
  id: string;
  category: string;
  title: string;
  brief: string;
  market_step: string;
  command_id?: WorkflowCommandId;
  command_label?: string;
  skill_packs?: string[];
  orchestration_notes?: string;
  covered_steps?: string[];
  status: TaskStatus;
  source_count: number;
  retry_count: number;
  progress?: number;
  agent_name?: string;
  current_action?: string;
  current_url?: string;
  browser_mode?: string;
  browser_available?: boolean;
  search_queries?: string[];
  visited_sources?: VisitedSourceRecord[];
  research_rounds?: ResearchRoundRecord[];
  skill_runtime?: Record<string, unknown>;
  coverage_status?: Record<string, unknown>;
  logs?: TaskLogRecord[];
  latest_error?: string;
}

export interface PhaseProgressRecord {
  phase: ResearchPhase;
  label: string;
  progress: number;
  status: "pending" | "running" | "completed";
}

export interface ResearchJobRecord {
  id: string;
  topic: string;
  industry_template: IndustryTemplate;
  research_mode: ResearchMode;
  depth_preset: DepthPreset;
  failure_policy?: FailurePolicy;
  completion_mode?: CompletionMode;
  workflow_command?: WorkflowCommandId;
  workflow_label?: string;
  project_memory?: string;
  orchestration_summary?: string;
  max_sources?: number;
  max_subtasks?: number;
  max_competitors?: number;
  review_sample_target?: number;
  time_budget_minutes?: number;
  status: JobStatus;
  overall_progress: number;
  current_phase: ResearchPhase;
  eta_seconds: number;
  source_count: number;
  competitor_count: number;
  completed_task_count: number;
  running_task_count: number;
  failed_task_count: number;
  claims_count: number;
  report_version_id?: string;
  active_report_version_id?: string;
  stable_report_version_id?: string;
  retrieval_profile_id?: string;
  quality_score_summary?: {
    report_readiness?: string;
    report_quality_score?: number;
    formal_claim_count?: number;
    formal_evidence_count?: number;
    formal_domain_count?: number;
    requires_finalize?: boolean;
  };
  phase_progress: PhaseProgressRecord[];
  tasks: ResearchTaskRecord[];
  activity_log?: TaskLogRecord[];
  runtime_summary?: RuntimeSummaryRecord;
  latest_error?: string;
  latest_warning?: string;
  cancel_requested?: boolean;
  cancellation_reason?: string;
  execution_mode?: string;
  background_process?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  completed_at?: string;
}

export interface HealthStatusRecord {
  status: string;
  active_job_count: number;
  active_detached_worker_count: number;
  runtime_configured: boolean;
  timestamp: string;
}

export interface EvidenceRecord {
  id: string;
  task_id: string;
  market_step: string;
  source_url: string;
  source_domain?: string;
  source_type: string;
  source_tier?: string;
  source_tier_label?: string;
  citation_label?: string;
  title: string;
  published_at?: string;
  captured_at: string;
  quote: string;
  summary: string;
  extracted_fact: string;
  normalized_fact?: string;
  raw_support?: string;
  extraction_method?: string;
  entity_ids?: string[];
  freshness_bucket?: string;
  reliability_scores?: {
    authority?: number;
    freshness?: number;
    relevance?: number;
    corroboration?: number;
  };
  authority_score: number;
  freshness_score: number;
  confidence: number;
  injection_risk: number;
  tags: string[];
  competitor_name?: string;
}

export interface CompetitorHighlightRecord {
  title?: string;
  summary?: string;
  source_url?: string;
  source_type?: string;
  source_type_label?: string;
  source_domain?: string;
  source_tier_label?: string;
  citation_label?: string;
  market_step?: string;
}

export interface ClaimRecord {
  id: string;
  claim_text: string;
  market_step: string;
  evidence_ids: string[];
  counter_evidence_ids: string[];
  supporting_evidence_ids?: string[];
  contradicting_evidence_ids?: string[];
  confidence: number;
  status: ClaimStatus;
  verification_state?: ClaimVerificationState;
  confidence_reason?: string;
  decision_impact?: string;
  caveats: string[];
  competitor_ids: string[];
  priority: "high" | "medium" | "low";
  actionability_score: number;
  last_verified_at: string;
}

export interface ReportFeedbackNoteRecord {
  question?: string;
  feedback?: string;
  response?: string;
  action?: string;
  claim_id?: string;
  created_at: string;
}

export interface ReportDecisionSnapshotRecord {
  readiness: string;
  readiness_reason?: string;
  high_confidence_claims?: number;
  inferred_claims?: number;
  disputed_claims?: number;
  open_questions?: number;
  unique_domains?: number;
  next_step?: string;
}

export interface ReportQualityGateRecord {
  pending?: boolean;
  passed?: boolean;
  reason?: string;
  reasons?: string[];
  checked_at?: string;
  policy_version?: string;
  thresholds?: Record<string, number>;
  metrics?: Record<string, number>;
}

export interface ReportSupportSnapshotRecord {
  claim_ids?: string[];
  evidence_ids?: string[];
  source_domains?: string[];
}

export interface ReportVersionDiffSummaryRecord {
  summary: string;
  added_claim_ids?: string[];
  removed_claim_ids?: string[];
  added_evidence_ids?: string[];
  removed_evidence_ids?: string[];
  changed_sections?: string[];
}

export interface ReportAssetRecord {
  markdown: string;
  board_brief_markdown?: string;
  executive_memo_markdown?: string;
  appendix_markdown?: string;
  conflict_summary_markdown?: string;
  claim_ids?: string[];
  evidence_ids?: string[];
  source_domains?: string[];
  decision_snapshot?: ReportDecisionSnapshotRecord;
  generated_at: string;
  updated_at?: string;
  stage?: string;
  section_count?: number;
  evidence_count?: number;
  revision_count?: number;
  feedback_count?: number;
  feedback_notes?: ReportFeedbackNoteRecord[];
  draft_markdown?: string;
  long_report_ready?: boolean;
  quality_gate?: ReportQualityGateRecord;
  formal_claim_count?: number;
  formal_evidence_count?: number;
  context_only_evidence_count?: number;
}

export interface ReportVersionRecord {
  version_id: string;
  version_number?: number;
  label?: string;
  stage?: string;
  kind?: ReportVersionKind;
  parent_version_id?: string;
  change_reason?: string;
  generated_from_question?: string;
  markdown: string;
  board_brief_markdown?: string;
  executive_memo_markdown?: string;
  appendix_markdown?: string;
  conflict_summary_markdown?: string;
  claim_ids?: string[];
  evidence_ids?: string[];
  source_domains?: string[];
  decision_snapshot?: ReportDecisionSnapshotRecord;
  generated_at: string;
  updated_at?: string;
  section_count?: number;
  evidence_count?: number;
  feedback_count?: number;
  revision_count?: number;
  long_report_ready?: boolean;
  quality_gate?: ReportQualityGateRecord;
  support_snapshot?: ReportSupportSnapshotRecord;
  diff_summary?: ReportVersionDiffSummaryRecord;
}

export interface ResearchAssetsRecord {
  report: ReportAssetRecord;
  claims: ClaimRecord[];
  evidence: EvidenceRecord[];
  competitors: CompetitorRecord[];
  market_map: Record<string, unknown>;
  progress_snapshot: Record<string, unknown>;
  report_versions?: ReportVersionRecord[];
  artifacts?: ArtifactFileRecord[];
}

export interface CompetitorRecord {
  name?: string;
  category?: string;
  positioning?: string;
  pricing?: string;
  differentiation?: string;
  coverage_gap?: string;
  evidence_count?: number;
  source_count?: number;
  source_domains?: string[];
  source_types?: string[];
  key_sources?: string[];
  highlights?: CompetitorHighlightRecord[];
}

export interface ChatMessageRecord {
  id: string;
  role: "user" | "assistant";
  content: string;
  cited_claim_ids: string[];
  triggered_delta_job_id?: string;
  answer_mode?: ChatAnswerMode;
  draft_version_id?: string;
  requires_finalize?: boolean;
  created_at: string;
}

export interface ChatSessionRecord {
  id: string;
  research_job_id: string;
  messages: ChatMessageRecord[];
  created_at?: string;
  updated_at?: string;
}

export interface SendChatMessageResultRecord {
  session_id: string;
  message: ChatMessageRecord;
  answer_mode?: ChatAnswerMode;
  draft_version_id?: string;
  requires_finalize?: boolean;
}

export interface ReportVersionDiffRecord {
  job_id: string;
  version_id: string;
  base_version_id: string;
  summary: string;
  version?: ReportVersionRecord;
  base_version?: ReportVersionRecord;
  diff_markdown?: string;
  added_claim_ids?: string[];
  removed_claim_ids?: string[];
  added_evidence_ids?: string[];
  removed_evidence_ids?: string[];
}
