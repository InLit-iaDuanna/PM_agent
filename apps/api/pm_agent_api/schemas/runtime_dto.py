from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from pm_agent_api.schemas.research_dto import (
    RuntimeConfigDto,
    RuntimeDebugPolicyDto,
    RuntimeLlmProfileDto,
    RuntimeQualityPolicyDto,
    RuntimeRetrievalProfileDto,
)


class RuntimeBackupStatusDto(BaseModel):
    label: str = ""
    base_url: str
    api_key_configured: bool
    api_key_masked: Optional[str] = None
    uses_primary_api_key: bool = True
    priority: int = 1
    is_active: bool = False


class RuntimeProfileDto(BaseModel):
    profile_id: str
    label: Optional[str] = None
    description: Optional[str] = None
    quality_mode: Optional[str] = None
    recommended: bool = False
    runtime_config: RuntimeConfigDto
    llm_profile: RuntimeLlmProfileDto
    retrieval_profile: RuntimeRetrievalProfileDto
    quality_policy: RuntimeQualityPolicyDto
    debug_policy: RuntimeDebugPolicyDto


class RuntimeStatusDto(BaseModel):
    provider: Literal["minimax", "openai_compatible"]
    model: str
    base_url: str
    active_base_url: Optional[str] = None
    timeout_seconds: float
    configured: bool
    api_key_configured: bool
    api_key_masked: Optional[str] = None
    backup_count: int = 0
    backup_configs: list[RuntimeBackupStatusDto] = Field(default_factory=list)
    source: Literal["saved", "environment", "default"] = "default"
    validation_status: Literal["unknown", "valid", "invalid"]
    validation_message: str
    browser_mode: str
    browser_available: bool
    selected_profile_id: str = "premium_default"
    selected_profile_label: Optional[str] = None
    selected_profile: RuntimeProfileDto
    available_profiles: list[RuntimeProfileDto] = Field(default_factory=list)
    runtime_config: RuntimeConfigDto
    resolved_runtime_config: RuntimeConfigDto
    llm_profile: Optional[RuntimeLlmProfileDto] = None
    retrieval_profile: Optional[RuntimeRetrievalProfileDto] = None
    quality_policy: Optional[RuntimeQualityPolicyDto] = None
    debug_policy: Optional[RuntimeDebugPolicyDto] = None
    updated_at: Optional[str] = None


class UpdateRuntimeSettingsDto(BaseModel):
    runtime_config: RuntimeConfigDto
    replace_api_key: bool = False


class RuntimeValidationRequestDto(BaseModel):
    runtime_config: RuntimeConfigDto


class RuntimeValidationResultDto(BaseModel):
    ok: bool
    provider: Literal["minimax", "openai_compatible"]
    model: str
    message: str
    browser_mode: str
    browser_available: bool
    selected_profile_id: Optional[str] = None
