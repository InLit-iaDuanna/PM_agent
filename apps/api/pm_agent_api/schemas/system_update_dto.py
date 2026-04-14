from typing import Literal, Optional

from pydantic import BaseModel, Field


class SystemVersionOptionDto(BaseModel):
    ref: str
    kind: Literal["branch", "tag"]
    commit: str = ""
    label: Optional[str] = None


class SystemUpdateJobDto(BaseModel):
    job_id: str
    ref: str
    use_prod: bool = False
    project_name: Optional[str] = None
    skip_backup: bool = False
    skip_pull: bool = False
    skip_build: bool = False
    status: Literal["running", "succeeded", "failed", "unknown"] = "unknown"
    pid: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    log_path: Optional[str] = None
    command: Optional[str] = None


class SystemUpdateStatusDto(BaseModel):
    supported: bool
    can_execute: bool
    execution_enabled: bool
    reason: Optional[str] = None
    repo_root: str
    current_ref: str
    current_tag: Optional[str] = None
    current_branch: Optional[str] = None
    current_commit: str
    build_time: Optional[str] = None
    default_ref: str = "main"
    compose_project_name: Optional[str] = None
    options: list[SystemVersionOptionDto] = Field(default_factory=list)
    suggested_command: str
    active_job: Optional[SystemUpdateJobDto] = None
    recent_jobs: list[SystemUpdateJobDto] = Field(default_factory=list)
    remote_name: str = "origin"
    remote_url: Optional[str] = None
    remote_main_commit: Optional[str] = None
    latest_tag: Optional[str] = None
    update_available: bool = False
    last_sync_at: Optional[str] = None
    last_sync_ok: Optional[bool] = None
    last_sync_message: Optional[str] = None


class TriggerSystemUpdateDto(BaseModel):
    ref: str = "main"
    use_prod: bool = False
    project_name: Optional[str] = None
    skip_backup: bool = False
    skip_pull: bool = False
    skip_build: bool = False
    admin_email: Optional[str] = None
    admin_password: Optional[str] = None
    admin_name: Optional[str] = None
