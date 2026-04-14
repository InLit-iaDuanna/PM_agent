import os
from typing import Optional

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from pm_agent_api.repositories import create_state_repository
from pm_agent_api.repositories.base import StateRepositoryProtocol
from pm_agent_api.schemas.auth_dto import AuthUserDto
from pm_agent_api.schemas.research_dto import HealthStatusDto
from pm_agent_api.services.auth_service import AuthService, SESSION_COOKIE_NAME
from pm_agent_api.services.chat_service import ChatService
from pm_agent_api.services.research_job_service import ResearchJobService
from pm_agent_api.services.runtime_service import RuntimeService
from pm_agent_api.services.system_update_service import SystemUpdateService

DEFAULT_CORS_ORIGIN_REGEX = r"https?://(localhost|127\.0\.0\.1)(:\d{1,5})?$"


def _parse_cors_origins() -> list[str]:
    raw_value = os.getenv("PM_AGENT_CORS_ORIGINS", "")
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def get_research_job_service(request: Request) -> ResearchJobService:
    return request.app.state.research_job_service


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_runtime_service(request: Request) -> RuntimeService:
    return request.app.state.runtime_service


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_system_update_service(request: Request) -> SystemUpdateService:
    return request.app.state.system_update_service


def get_optional_current_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    authorization: Optional[str] = Header(default=None),
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Optional[AuthUserDto]:
    resolved_token = auth_service.resolve_session_token(authorization, session_token)
    user = auth_service.get_user_for_session_token(resolved_token)
    if not user:
        return None
    return AuthUserDto(**user)


def get_current_user(current_user: Optional[AuthUserDto] = Depends(get_optional_current_user)) -> AuthUserDto:
    if current_user:
        return current_user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录。")


def create_app(
    repository: StateRepositoryProtocol | None = None,
    research_job_service: ResearchJobService | None = None,
    chat_service: ChatService | None = None,
    runtime_service: RuntimeService | None = None,
    auth_service: AuthService | None = None,
    system_update_service: SystemUpdateService | None = None,
) -> FastAPI:
    repository = repository or create_state_repository()
    background_mode = str(os.getenv("PM_AGENT_BACKGROUND_MODE", "subprocess") or "subprocess").strip().lower()
    research_job_service = research_job_service or ResearchJobService(repository, background_mode=background_mode)
    chat_service = chat_service or ChatService(repository)
    runtime_service = runtime_service or RuntimeService(repository)
    auth_service = auth_service or AuthService(repository)
    system_update_service = system_update_service or SystemUpdateService()

    app = FastAPI(title="PM Research Agent API", version="0.1.0")
    app.state.repository = repository
    app.state.research_job_service = research_job_service
    app.state.chat_service = chat_service
    app.state.runtime_service = runtime_service
    app.state.auth_service = auth_service
    app.state.system_update_service = system_update_service

    cors_origins = _parse_cors_origins()
    cors_origin_regex = os.getenv("PM_AGENT_CORS_ORIGIN_REGEX", DEFAULT_CORS_ORIGIN_REGEX).strip() or None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root():
        return {"name": "pm-research-agent-api", "status": "ok"}

    @app.get("/api/health", response_model=HealthStatusDto)
    def api_health(request: Request, current_user: Optional[AuthUserDto] = Depends(get_optional_current_user)):
        owner_user_id = current_user.id if current_user else None
        runtime_status = request.app.state.runtime_service.get_status(owner_user_id=owner_user_id)
        return request.app.state.research_job_service.get_health_status(
            runtime_status.get("configured", False),
            owner_user_id=owner_user_id,
        )

    from pm_agent_api.routes.admin import router as admin_router
    from pm_agent_api.routes.auth import router as auth_router
    from pm_agent_api.routes.chat_sessions import router as chat_router
    from pm_agent_api.routes.research_jobs import router as research_router
    from pm_agent_api.routes.runtime import router as runtime_router
    from pm_agent_api.routes.streams import router as stream_router

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(research_router)
    app.include_router(chat_router)
    app.include_router(runtime_router)
    app.include_router(stream_router)
    return app


app = create_app()
