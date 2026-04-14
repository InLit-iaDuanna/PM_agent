from fastapi import APIRouter, Depends, HTTPException, status

from pm_agent_api.main import get_auth_service, get_current_user, get_system_update_service
from pm_agent_api.schemas.auth_dto import (
    AdminResetPasswordDto,
    AuthPublicConfigDto,
    AuthUserDto,
    CreateInviteDto,
    DisableUserDto,
    InviteDto,
    UpdateRegistrationPolicyDto,
    UpdateUserRoleDto,
)
from pm_agent_api.schemas.system_update_dto import (
    SystemUpdateJobDto,
    SystemUpdateStatusDto,
    TriggerSystemUpdateDto,
)
from pm_agent_api.services.auth_service import AuthService, PermissionDeniedError
from pm_agent_api.services.system_update_service import SystemUpdateService

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin_user(current_user: AuthUserDto) -> None:
    role = str(getattr(current_user, "role", "") or "").strip()
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有管理员可以执行这个操作。")


@router.post("/registration-policy", response_model=AuthPublicConfigDto)
def update_registration_policy(
    payload: UpdateRegistrationPolicyDto,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return auth_service.update_registration_policy(current_user.id, payload.registration_mode)
    except PermissionDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/users", response_model=list[AuthUserDto])
def list_users(
    auth_service: AuthService = Depends(get_auth_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return auth_service.list_users(current_user.id)
    except PermissionDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from error


@router.get("/invites", response_model=list[InviteDto])
def list_invites(
    auth_service: AuthService = Depends(get_auth_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return auth_service.list_invites(current_user.id)
    except PermissionDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from error


@router.post("/invites", response_model=InviteDto)
def create_invite(
    payload: CreateInviteDto,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return auth_service.create_invite(current_user.id, payload.note)
    except PermissionDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post("/invites/{invite_id}/disable", response_model=InviteDto)
def disable_invite(
    invite_id: str,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return auth_service.disable_invite(current_user.id, invite_id)
    except PermissionDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀请码不存在。") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post("/users/{user_id}/role", response_model=AuthUserDto)
def update_user_role(
    user_id: str,
    payload: UpdateUserRoleDto,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return auth_service.update_user_role(current_user.id, user_id, payload.role)
    except PermissionDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post("/users/{user_id}/disable", response_model=AuthUserDto)
def disable_user(
    user_id: str,
    payload: DisableUserDto | None = None,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return auth_service.disable_user(current_user.id, user_id, payload.reason if payload else None)
    except PermissionDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post("/users/{user_id}/enable", response_model=AuthUserDto)
def enable_user(
    user_id: str,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return auth_service.enable_user(current_user.id, user_id)
    except PermissionDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post("/users/{user_id}/reset-password", response_model=AuthUserDto)
def admin_reset_password(
    user_id: str,
    payload: AdminResetPasswordDto,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        return auth_service.admin_reset_password(current_user.id, user_id, payload.new_password)
    except PermissionDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/system-update", response_model=SystemUpdateStatusDto)
def get_system_update_status(
    update_service: SystemUpdateService = Depends(get_system_update_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    _require_admin_user(current_user)
    return update_service.get_status()


@router.post("/system-update", response_model=SystemUpdateJobDto)
def trigger_system_update(
    payload: TriggerSystemUpdateDto,
    update_service: SystemUpdateService = Depends(get_system_update_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    _require_admin_user(current_user)
    try:
        return update_service.trigger_update(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
