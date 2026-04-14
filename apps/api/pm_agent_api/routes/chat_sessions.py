from fastapi import APIRouter, Depends, HTTPException, Query

from pm_agent_api.main import get_chat_service, get_current_user
from pm_agent_api.schemas.auth_dto import AuthUserDto
from pm_agent_api.schemas.chat_dto import ChatSessionDto, CreateChatSessionDto, SendChatMessageDto, SendChatMessageResultDto
from pm_agent_api.services.chat_service import ChatService

router = APIRouter(prefix="/api/chat/sessions", tags=["chat"])


@router.get("", response_model=list[ChatSessionDto])
def list_chat_sessions(
    research_job_id: str = Query(...),
    service: ChatService = Depends(get_chat_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.list_sessions(research_job_id, current_user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Research job not found") from error


@router.post("", response_model=ChatSessionDto)
def create_chat_session(
    payload: CreateChatSessionDto,
    service: ChatService = Depends(get_chat_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.create_session(payload.research_job_id, current_user.id, payload.reuse_existing)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Research job not found") from error


@router.get("/{session_id}", response_model=ChatSessionDto)
def get_chat_session(
    session_id: str,
    service: ChatService = Depends(get_chat_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.get_session(session_id, current_user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Chat session not found") from error


@router.get("/{session_id}/messages", response_model=ChatSessionDto)
def get_chat_messages(
    session_id: str,
    service: ChatService = Depends(get_chat_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.get_session(session_id, current_user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Chat session not found") from error


@router.post("/{session_id}/messages", response_model=SendChatMessageResultDto)
async def post_chat_message(
    session_id: str,
    payload: SendChatMessageDto,
    service: ChatService = Depends(get_chat_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return await service.send_message(session_id, payload.content, current_user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Chat session not found") from error
