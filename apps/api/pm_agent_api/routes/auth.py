import os
from typing import Literal, Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status

from pm_agent_api.main import get_auth_service, get_current_user
from pm_agent_api.schemas.auth_dto import (
    AuthPublicConfigDto,
    AuthSessionDto,
    AuthUserDto,
    ChangePasswordDto,
    DeleteAccountDto,
    LoginUserDto,
    LogoutResultDto,
    RegisterUserDto,
)
from pm_agent_api.services.auth_service import (
    AuthService,
    DisabledUserError,
    DuplicateUserError,
    InvalidCredentialsError,
    InvalidInviteCodeError,
    RegistrationDisabledError,
    SESSION_COOKIE_NAME,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _cookie_secure(request: Request) -> bool:
    raw_value = str(os.getenv("PM_AGENT_AUTH_COOKIE_SECURE", "") or "").strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    return request.url.scheme == "https"


def _cookie_same_site() -> Literal["lax", "strict", "none"]:
    raw_value = str(os.getenv("PM_AGENT_AUTH_COOKIE_SAMESITE", "lax") or "").strip().lower()
    if raw_value in {"strict", "none"}:
        return raw_value  # type: ignore[return-value]
    return "lax"


def _set_session_cookie(response: Response, request: Request, session_token: str, auth_service: AuthService) -> None:
    max_age = auth_service._session_max_age_seconds()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=_cookie_secure(request),
        samesite=_cookie_same_site(),
        max_age=max_age,
        expires=max_age,
        path="/",
    )


@router.get("/public-config", response_model=AuthPublicConfigDto)
def get_public_auth_config(auth_service: AuthService = Depends(get_auth_service)):
    return auth_service.get_registration_policy()


@router.post("/register", response_model=AuthSessionDto)
def register_user(payload: RegisterUserDto, request: Request, response: Response, auth_service: AuthService = Depends(get_auth_service)):
    try:
        session = auth_service.register(payload.email, payload.password, payload.display_name, payload.invite_code)
    except DuplicateUserError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except RegistrationDisabledError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except InvalidInviteCodeError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    _set_session_cookie(response, request, session["session_token"], auth_service)
    return {"user": session["user"]}


@router.post("/login", response_model=AuthSessionDto)
def login_user(payload: LoginUserDto, request: Request, response: Response, auth_service: AuthService = Depends(get_auth_service)):
    try:
        session = auth_service.login(payload.email, payload.password)
    except DisabledUserError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    _set_session_cookie(response, request, session["session_token"], auth_service)
    return {"user": session["user"]}


@router.get("/me", response_model=AuthUserDto)
def get_current_auth_user(current_user: AuthUserDto = Depends(get_current_user)):
    return current_user


@router.post("/change-password", response_model=AuthSessionDto)
def change_password(
    payload: ChangePasswordDto,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        session = auth_service.change_password(current_user.id, payload.current_password, payload.new_password)
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    _set_session_cookie(response, request, session["session_token"], auth_service)
    return {"user": session["user"]}


@router.post("/delete-account", response_model=LogoutResultDto)
def delete_account(
    payload: DeleteAccountDto,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    current_user: AuthUserDto = Depends(get_current_user),
):
    try:
        auth_service.delete_account(current_user.id, payload.current_password)
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=_cookie_secure(request),
        samesite=_cookie_same_site(),
    )
    return {"ok": True}


@router.post("/logout", response_model=LogoutResultDto)
def logout_user(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    authorization: Optional[str] = Header(default=None),
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    resolved_token = auth_service.resolve_session_token(authorization, session_token)
    auth_service.logout(resolved_token)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=_cookie_secure(request),
        samesite=_cookie_same_site(),
    )
    return {"ok": True}
