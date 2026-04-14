from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ChatSchemaModel(BaseModel):
    class Config:
        extra = "allow"


class CreateChatSessionDto(ChatSchemaModel):
    research_job_id: str
    reuse_existing: bool = True


class SendChatMessageDto(ChatSchemaModel):
    content: str


class ChatMessageDto(ChatSchemaModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    cited_claim_ids: List[str] = Field(default_factory=list)
    triggered_delta_job_id: Optional[str] = None
    answer_mode: Optional[Literal["report_pending", "report_context", "delta_requested", "delta_draft", "delta_failed"]] = None
    draft_version_id: Optional[str] = None
    requires_finalize: Optional[bool] = None
    created_at: str


class ChatSessionDto(ChatSchemaModel):
    id: str
    research_job_id: str
    messages: List[ChatMessageDto] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SendChatMessageResultDto(ChatSchemaModel):
    session_id: str
    message: ChatMessageDto
    answer_mode: Optional[Literal["report_pending", "report_context", "delta_requested", "delta_draft", "delta_failed"]] = None
    draft_version_id: Optional[str] = None
    requires_finalize: Optional[bool] = None
