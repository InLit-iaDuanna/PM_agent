from fastapi import APIRouter, Depends, HTTPException

from pm_agent_api.main import get_current_user, get_runtime_service
from pm_agent_api.schemas.auth_dto import AuthUserDto
from pm_agent_api.schemas.runtime_dto import (
    RuntimeStatusDto,
    RuntimeValidationRequestDto,
    RuntimeValidationResultDto,
    UpdateRuntimeSettingsDto,
)
from pm_agent_api.services.runtime_service import RuntimeService

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.get("", response_model=RuntimeStatusDto)
def get_runtime_status(
    service: RuntimeService = Depends(get_runtime_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    return service.get_status(owner_user_id=current_user.id)


@router.post("", response_model=RuntimeStatusDto)
def save_runtime_settings(
    payload: UpdateRuntimeSettingsDto,
    service: RuntimeService = Depends(get_runtime_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return service.save_settings(payload.runtime_config.model_dump(), payload.replace_api_key, current_user.id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/validate", response_model=RuntimeValidationResultDto)
def validate_runtime_settings(
    payload: RuntimeValidationRequestDto,
    service: RuntimeService = Depends(get_runtime_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    return service.validate(payload.runtime_config.model_dump(), current_user.id)
