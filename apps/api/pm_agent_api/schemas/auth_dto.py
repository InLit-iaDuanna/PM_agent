from typing import Optional

from pydantic import BaseModel, Field


class AuthSchemaModel(BaseModel):
    class Config:
        extra = "allow"


class AuthUserDto(AuthSchemaModel):
    id: str
    email: str
    display_name: Optional[str] = None
    role: str = "member"
    is_disabled: bool = False
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None
    disabled_at: Optional[str] = None
    disabled_reason: Optional[str] = None


class RegisterUserDto(AuthSchemaModel):
    email: str
    password: str = Field(min_length=8)
    display_name: Optional[str] = None
    invite_code: Optional[str] = None


class LoginUserDto(AuthSchemaModel):
    email: str
    password: str = Field(min_length=8)


class AuthSessionDto(AuthSchemaModel):
    user: AuthUserDto


class LogoutResultDto(AuthSchemaModel):
    ok: bool = True


class AuthPublicConfigDto(AuthSchemaModel):
    registration_enabled: bool = True
    invite_code_required: bool = False
    first_user_will_be_admin: bool = False
    registration_mode: str = "open"
    registration_mode_source: str = "default"
    configured_registration_mode: str = "default"


class ChangePasswordDto(AuthSchemaModel):
    current_password: str = Field(min_length=8)
    new_password: str = Field(min_length=8)


class DeleteAccountDto(AuthSchemaModel):
    current_password: str = Field(min_length=8)


class CreateInviteDto(AuthSchemaModel):
    note: Optional[str] = None


class InviteDto(AuthSchemaModel):
    id: str
    code: str
    note: Optional[str] = None
    issued_by_user_id: Optional[str] = None
    issued_by_email: Optional[str] = None
    created_at: Optional[str] = None
    used_at: Optional[str] = None
    used_by_user_id: Optional[str] = None
    used_by_email: Optional[str] = None
    disabled_at: Optional[str] = None
    disabled_reason: Optional[str] = None
    active: bool = True


class UpdateUserRoleDto(AuthSchemaModel):
    role: str = "member"


class DisableUserDto(AuthSchemaModel):
    reason: Optional[str] = None


class AdminResetPasswordDto(AuthSchemaModel):
    new_password: str = Field(min_length=8)


class UpdateRegistrationPolicyDto(AuthSchemaModel):
    registration_mode: str = "default"
