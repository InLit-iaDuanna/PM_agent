import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from pm_agent_api.repositories.base import StateRepositoryProtocol

SESSION_COOKIE_NAME = "pm_agent_session"
PASSWORD_HASH_DIGEST = "sha256"
PASSWORD_HASH_ITERATIONS = 200_000
REGISTRATION_MODE_DEFAULT = "default"
REGISTRATION_MODE_BOOTSTRAP = "bootstrap"
REGISTRATION_MODE_OPEN = "open"
REGISTRATION_MODE_INVITE_ONLY = "invite_only"
REGISTRATION_MODE_CLOSED = "closed"
REGISTRATION_MODE_SOURCE_BOOTSTRAP = "bootstrap"
REGISTRATION_MODE_SOURCE_DEFAULT = "default"
REGISTRATION_MODE_SOURCE_ADMIN_OVERRIDE = "admin_override"
REGISTRATION_OVERRIDE_MODES = {
    REGISTRATION_MODE_OPEN,
    REGISTRATION_MODE_INVITE_ONLY,
    REGISTRATION_MODE_CLOSED,
}
REGISTRATION_SETTING_MODES = {
    REGISTRATION_MODE_DEFAULT,
    *REGISTRATION_OVERRIDE_MODES,
}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DuplicateUserError(ValueError):
    pass


class InvalidCredentialsError(ValueError):
    pass


class RegistrationDisabledError(ValueError):
    pass


class InvalidInviteCodeError(ValueError):
    pass


class PermissionDeniedError(PermissionError):
    pass


class DisabledUserError(PermissionError):
    pass


class AuthService:
    def __init__(self, repository: StateRepositoryProtocol) -> None:
        self.repository = repository

    def _session_max_age_seconds(self) -> int:
        raw_value = str(os.getenv("PM_AGENT_SESSION_MAX_AGE_SECONDS", "2592000") or "").strip()
        try:
            max_age_seconds = int(raw_value)
        except ValueError:
            max_age_seconds = 2_592_000
        return max(3_600, max_age_seconds)

    def _normalize_email(self, email: str) -> str:
        normalized = str(email or "").strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("请输入有效的邮箱地址。")
        return normalized

    def _normalize_display_name(self, display_name: Optional[str], email: str) -> str:
        normalized = str(display_name or "").strip()
        if normalized:
            return normalized[:80]
        return email.split("@", 1)[0][:80]

    def _public_registration_enabled(self) -> bool:
        raw_value = str(os.getenv("PM_AGENT_ALLOW_PUBLIC_REGISTRATION", "true") or "").strip().lower()
        return raw_value not in {"0", "false", "no", "off"}

    def _configured_invite_code(self) -> str:
        return str(os.getenv("PM_AGENT_REGISTRATION_INVITE_CODE", "") or "").strip()

    def _normalize_registration_setting_mode(self, registration_mode: Optional[str]) -> str:
        normalized = str(registration_mode or REGISTRATION_MODE_DEFAULT).strip().lower()
        if normalized not in REGISTRATION_SETTING_MODES:
            raise ValueError("注册策略必须是 default、open、invite_only 或 closed。")
        return normalized

    def _get_configured_registration_mode(self) -> str:
        auth_policy = self.repository.get_auth_policy() or {}
        normalized = str(auth_policy.get("registration_mode_override") or "").strip().lower()
        if normalized in REGISTRATION_OVERRIDE_MODES:
            return normalized
        return REGISTRATION_MODE_DEFAULT

    def _is_first_user(self) -> bool:
        return self.repository.count_users() == 0

    def _active_invites_exist(self) -> bool:
        return bool(self.repository.list_invites(active_only=True))

    def _require_admin(self, user_id: str) -> Dict[str, Any]:
        user = self.repository.get_user(user_id)
        if not user:
            raise KeyError(user_id)
        if str(user.get("role") or "member").strip() != "admin":
            raise PermissionDeniedError("只有管理员可以执行这个操作。")
        if user.get("disabled_at"):
            raise PermissionDeniedError("已停用账号不能执行这个操作。")
        return user

    def _is_user_disabled(self, user: Optional[Dict[str, Any]]) -> bool:
        if not user:
            return False
        return bool(str(user.get("disabled_at") or "").strip())

    def _assert_user_active(self, user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not user:
            raise InvalidCredentialsError("邮箱或密码不正确。")
        if self._is_user_disabled(user):
            raise DisabledUserError("账号已被管理员停用，请联系管理员。")
        return user

    def get_registration_policy(self) -> Dict[str, Any]:
        first_user = self._is_first_user()
        configured_registration_mode = self._get_configured_registration_mode()
        default_invite_code_required = bool(self._configured_invite_code()) or self._active_invites_exist()
        public_registration_enabled = self._public_registration_enabled()

        if first_user:
            registration_mode = REGISTRATION_MODE_BOOTSTRAP
            registration_mode_source = REGISTRATION_MODE_SOURCE_BOOTSTRAP
            invite_code_required = bool(self._configured_invite_code())
            registration_enabled = True
        elif configured_registration_mode in REGISTRATION_OVERRIDE_MODES:
            registration_mode = configured_registration_mode
            registration_mode_source = REGISTRATION_MODE_SOURCE_ADMIN_OVERRIDE
            invite_code_required = registration_mode == REGISTRATION_MODE_INVITE_ONLY
            registration_enabled = registration_mode != REGISTRATION_MODE_CLOSED
        else:
            registration_mode_source = REGISTRATION_MODE_SOURCE_DEFAULT
            registration_mode = (
                REGISTRATION_MODE_INVITE_ONLY
                if default_invite_code_required
                else REGISTRATION_MODE_OPEN
                if public_registration_enabled
                else REGISTRATION_MODE_CLOSED
            )
            invite_code_required = registration_mode == REGISTRATION_MODE_INVITE_ONLY
            registration_enabled = registration_mode != REGISTRATION_MODE_CLOSED

        return {
            "registration_enabled": registration_enabled,
            "invite_code_required": invite_code_required,
            "first_user_will_be_admin": first_user,
            "registration_mode": registration_mode,
            "registration_mode_source": registration_mode_source,
            "configured_registration_mode": configured_registration_mode,
        }

    def _validate_password(self, password: str) -> str:
        normalized = str(password or "")
        if len(normalized) < 8:
            raise ValueError("密码至少需要 8 位。")
        return normalized

    def _validate_registration(self, invite_code: Optional[str]) -> None:
        policy = self.get_registration_policy()
        if not policy["registration_enabled"]:
            raise RegistrationDisabledError("当前已关闭公开注册，请联系管理员。")
        if not policy["invite_code_required"]:
            return

        expected_invite_code = self._configured_invite_code()
        normalized_invite_code = str(invite_code or "").strip()
        if expected_invite_code:
            if normalized_invite_code != expected_invite_code:
                raise InvalidInviteCodeError("邀请码不正确。")
            return
        if not self.repository.find_invite_by_code(normalized_invite_code):
            raise InvalidInviteCodeError("邀请码不正确。")

    def _hash_password(self, password: str, salt_hex: str) -> str:
        salt = bytes.fromhex(salt_hex)
        derived_key = hashlib.pbkdf2_hmac(
            PASSWORD_HASH_DIGEST,
            password.encode("utf-8"),
            salt,
            PASSWORD_HASH_ITERATIONS,
        )
        return derived_key.hex()

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _public_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(user.get("id") or "").strip(),
            "email": str(user.get("email") or "").strip(),
            "display_name": str(user.get("display_name") or "").strip() or None,
            "role": str(user.get("role") or "member").strip() or "member",
            "is_disabled": self._is_user_disabled(user),
            "created_at": user.get("created_at"),
            "last_login_at": user.get("last_login_at"),
            "disabled_at": user.get("disabled_at"),
            "disabled_reason": user.get("disabled_reason"),
        }

    def _issue_session(self, user: Dict[str, Any]) -> Dict[str, Any]:
        session_token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(session_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._session_max_age_seconds())
        auth_session = {
            "id": str(uuid.uuid4()),
            "token_hash": token_hash,
            "user_id": str(user["id"]),
            "created_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        self.repository.create_auth_session(auth_session)
        return {
            "session_token": session_token,
            "user": self._public_user(user),
        }

    def register(
        self,
        email: str,
        password: str,
        display_name: Optional[str] = None,
        invite_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_email = self._normalize_email(email)
        normalized_password = self._validate_password(password)
        self._validate_registration(invite_code)
        if self.repository.find_user_by_email(normalized_email):
            raise DuplicateUserError("这个邮箱已经注册过了，请直接登录。")

        salt_hex = secrets.token_hex(16)
        role = "admin" if self._is_first_user() else "member"
        user = {
            "id": str(uuid.uuid4()),
            "email": normalized_email,
            "display_name": self._normalize_display_name(display_name, normalized_email),
            "role": role,
            "password_salt": salt_hex,
            "password_hash": self._hash_password(normalized_password, salt_hex),
            "password_hash_digest": PASSWORD_HASH_DIGEST,
            "password_hash_iterations": PASSWORD_HASH_ITERATIONS,
            "last_login_at": iso_now(),
        }
        self.repository.create_user(user)
        invite_record = self.repository.find_invite_by_code(str(invite_code or "").strip())
        if invite_record:
            invite_record["used_at"] = iso_now()
            invite_record["used_by_user_id"] = user["id"]
            invite_record["used_by_email"] = normalized_email
            self.repository.update_invite(str(invite_record["id"]), invite_record)
        return self._issue_session(self.repository.get_user(user["id"]) or user)

    def bootstrap_admin(self, email: str, password: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        normalized_email = self._normalize_email(email)
        normalized_password = self._validate_password(password)
        existing_user = self.repository.find_user_by_email(normalized_email)
        if existing_user:
            if str(existing_user.get("role") or "").strip() == "admin":
                return self._public_user(existing_user)
            raise DuplicateUserError("这个邮箱已经注册过了，但不是管理员账号。")
        if not self._is_first_user():
            raise ValueError("系统中已存在账号，不能再执行首个管理员初始化。")

        salt_hex = secrets.token_hex(16)
        user = {
            "id": str(uuid.uuid4()),
            "email": normalized_email,
            "display_name": self._normalize_display_name(display_name, normalized_email),
            "role": "admin",
            "password_salt": salt_hex,
            "password_hash": self._hash_password(normalized_password, salt_hex),
            "password_hash_digest": PASSWORD_HASH_DIGEST,
            "password_hash_iterations": PASSWORD_HASH_ITERATIONS,
            "last_login_at": None,
        }
        self.repository.create_user(user)
        return self._public_user(self.repository.get_user(user["id"]) or user)

    def login(self, email: str, password: str) -> Dict[str, Any]:
        normalized_email = self._normalize_email(email)
        normalized_password = self._validate_password(password)
        user = self.repository.find_user_by_email(normalized_email)
        user = self._assert_user_active(user)

        expected_hash = str(user.get("password_hash") or "")
        salt_hex = str(user.get("password_salt") or "")
        actual_hash = self._hash_password(normalized_password, salt_hex)
        if not expected_hash or not hmac.compare_digest(expected_hash, actual_hash):
            raise InvalidCredentialsError("邮箱或密码不正确。")

        user["last_login_at"] = iso_now()
        self.repository.update_user(str(user["id"]), user)
        return self._issue_session(self.repository.get_user(str(user["id"])) or user)

    def resolve_session_token(self, authorization: Optional[str], session_token: Optional[str]) -> Optional[str]:
        bearer_value = str(authorization or "").strip()
        if bearer_value.lower().startswith("bearer "):
            token = bearer_value[7:].strip()
            if token:
                return token
        normalized_cookie = str(session_token or "").strip()
        return normalized_cookie or None

    def get_user_for_session_token(self, session_token: Optional[str]) -> Optional[Dict[str, Any]]:
        normalized_token = str(session_token or "").strip()
        if not normalized_token:
            return None

        token_hash = self._hash_token(normalized_token)
        auth_session = self.repository.get_auth_session(token_hash)
        if not auth_session:
            return None

        expires_at = str(auth_session.get("expires_at") or "").strip()
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
                    self.repository.delete_auth_session(token_hash)
                    return None
            except ValueError:
                self.repository.delete_auth_session(token_hash)
                return None

        user_id = str(auth_session.get("user_id") or "").strip()
        user = self.repository.get_user(user_id)
        if not user:
            self.repository.delete_auth_session(token_hash)
            return None
        if self._is_user_disabled(user):
            self.repository.delete_auth_sessions_for_user(user_id)
            return None

        auth_session["last_seen_at"] = iso_now()
        self.repository.update_auth_session(token_hash, auth_session)
        return self._public_user(user)

    def logout(self, session_token: Optional[str]) -> None:
        normalized_token = str(session_token or "").strip()
        if not normalized_token:
            return
        self.repository.delete_auth_session(self._hash_token(normalized_token))

    def change_password(self, user_id: str, current_password: str, new_password: str) -> Dict[str, Any]:
        user = self.repository.get_user(user_id)
        if not user:
            raise KeyError(user_id)
        self._assert_user_active(user)

        normalized_current_password = self._validate_password(current_password)
        normalized_new_password = self._validate_password(new_password)
        expected_hash = str(user.get("password_hash") or "")
        salt_hex = str(user.get("password_salt") or "")
        actual_hash = self._hash_password(normalized_current_password, salt_hex)
        if not expected_hash or not hmac.compare_digest(expected_hash, actual_hash):
            raise InvalidCredentialsError("当前密码不正确。")

        next_salt_hex = secrets.token_hex(16)
        user["password_salt"] = next_salt_hex
        user["password_hash"] = self._hash_password(normalized_new_password, next_salt_hex)
        user["last_login_at"] = iso_now()
        user["password_changed_at"] = iso_now()
        self.repository.update_user(user_id, user)
        self.repository.delete_auth_sessions_for_user(user_id)
        return self._issue_session(self.repository.get_user(user_id) or user)

    def delete_account(self, user_id: str, current_password: str) -> None:
        user = self.repository.get_user(user_id)
        if not user:
            raise KeyError(user_id)
        self._assert_user_active(user)

        normalized_current_password = self._validate_password(current_password)
        expected_hash = str(user.get("password_hash") or "")
        salt_hex = str(user.get("password_salt") or "")
        actual_hash = self._hash_password(normalized_current_password, salt_hex)
        if not expected_hash or not hmac.compare_digest(expected_hash, actual_hash):
            raise InvalidCredentialsError("当前密码不正确。")

        current_role = str(user.get("role") or "member").strip() or "member"
        if current_role == "admin":
            users = self.repository.list_users()
            remaining_active_admin_count = sum(
                1
                for item in users
                if str(item.get("id") or "").strip() != user_id
                and str(item.get("role") or "").strip() == "admin"
                and not self._is_user_disabled(item)
            )
            other_user_exists = any(str(item.get("id") or "").strip() != user_id for item in users)
            if remaining_active_admin_count <= 0 and other_user_exists:
                raise ValueError("当前仅剩最后一个可用管理员，不能删除账号。")

        self.repository.delete_auth_sessions_for_user(user_id)
        self.repository.delete_chat_sessions_for_user(user_id)
        self.repository.delete_jobs_for_user(user_id)
        self.repository.delete_runtime_config(user_id)
        self.repository.delete_user(user_id)

    def list_users(self, admin_user_id: str) -> list[Dict[str, Any]]:
        self._require_admin(admin_user_id)
        return [self._public_user(user) for user in self.repository.list_users()]

    def update_registration_policy(self, admin_user_id: str, registration_mode: str) -> Dict[str, Any]:
        self._require_admin(admin_user_id)
        normalized_registration_mode = self._normalize_registration_setting_mode(registration_mode)
        auth_policy = self.repository.get_auth_policy() or {}
        auth_policy["registration_mode_override"] = (
            None if normalized_registration_mode == REGISTRATION_MODE_DEFAULT else normalized_registration_mode
        )
        auth_policy["updated_at"] = iso_now()
        auth_policy["updated_by_user_id"] = admin_user_id
        self.repository.set_auth_policy(auth_policy)
        return self.get_registration_policy()

    def list_invites(self, admin_user_id: str) -> list[Dict[str, Any]]:
        admin_user = self._require_admin(admin_user_id)
        invites = []
        for invite in self.repository.list_invites():
            payload = dict(invite)
            payload["active"] = not bool(payload.get("disabled_at") or payload.get("used_at"))
            payload["issued_by_email"] = admin_user["email"] if payload.get("issued_by_user_id") == admin_user_id else (
                self.repository.get_user(str(payload.get("issued_by_user_id") or "")) or {}
            ).get("email")
            invites.append(payload)
        return invites

    def create_invite(self, admin_user_id: str, note: Optional[str] = None) -> Dict[str, Any]:
        admin_user = self._require_admin(admin_user_id)
        invite = {
            "id": str(uuid.uuid4()),
            "code": secrets.token_urlsafe(12),
            "note": str(note or "").strip() or None,
            "issued_by_user_id": admin_user_id,
            "issued_by_email": admin_user["email"],
        }
        self.repository.create_invite(invite)
        payload = self.repository.get_invite(invite["id"]) or invite
        payload["active"] = True
        return payload

    def disable_invite(self, admin_user_id: str, invite_id: str) -> Dict[str, Any]:
        self._require_admin(admin_user_id)
        invite = self.repository.get_invite(invite_id)
        if not invite:
            raise KeyError(invite_id)
        if not invite.get("used_at") and not invite.get("disabled_at"):
            invite["disabled_at"] = iso_now()
            invite["disabled_reason"] = "disabled_by_admin"
            self.repository.update_invite(invite_id, invite)
        payload = self.repository.get_invite(invite_id) or invite
        payload["active"] = not bool(payload.get("disabled_at") or payload.get("used_at"))
        return payload

    def update_user_role(self, admin_user_id: str, target_user_id: str, role: str) -> Dict[str, Any]:
        normalized_role = str(role or "").strip()
        if normalized_role not in {"admin", "member"}:
            raise ValueError("角色必须是 admin 或 member。")

        self._require_admin(admin_user_id)
        target_user = self.repository.get_user(target_user_id)
        if not target_user:
            raise KeyError(target_user_id)

        current_role = str(target_user.get("role") or "member").strip() or "member"
        if current_role == normalized_role:
            return self._public_user(target_user)

        if current_role == "admin" and normalized_role != "admin":
            admin_count = sum(1 for user in self.repository.list_users() if str(user.get("role") or "").strip() == "admin")
            if admin_count <= 1:
                raise ValueError("至少需要保留一个管理员。")

        target_user["role"] = normalized_role
        self.repository.update_user(target_user_id, target_user)
        return self._public_user(self.repository.get_user(target_user_id) or target_user)

    def disable_user(self, admin_user_id: str, target_user_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        self._require_admin(admin_user_id)
        target_user = self.repository.get_user(target_user_id)
        if not target_user:
            raise KeyError(target_user_id)

        current_role = str(target_user.get("role") or "member").strip() or "member"
        if current_role == "admin" and not self._is_user_disabled(target_user):
            active_admin_count = sum(
                1
                for user in self.repository.list_users()
                if str(user.get("role") or "").strip() == "admin" and not self._is_user_disabled(user)
            )
            if active_admin_count <= 1:
                raise ValueError("至少需要保留一个可用管理员。")

        if not self._is_user_disabled(target_user):
            target_user["disabled_at"] = iso_now()
            target_user["disabled_reason"] = str(reason or "").strip() or "disabled_by_admin"
            self.repository.update_user(target_user_id, target_user)
        self.repository.delete_auth_sessions_for_user(target_user_id)
        return self._public_user(self.repository.get_user(target_user_id) or target_user)

    def enable_user(self, admin_user_id: str, target_user_id: str) -> Dict[str, Any]:
        self._require_admin(admin_user_id)
        target_user = self.repository.get_user(target_user_id)
        if not target_user:
            raise KeyError(target_user_id)

        if self._is_user_disabled(target_user):
            target_user["disabled_at"] = None
            target_user["disabled_reason"] = None
            self.repository.update_user(target_user_id, target_user)
        return self._public_user(self.repository.get_user(target_user_id) or target_user)

    def admin_reset_password(self, admin_user_id: str, target_user_id: str, new_password: str) -> Dict[str, Any]:
        self._require_admin(admin_user_id)
        target_user = self.repository.get_user(target_user_id)
        if not target_user:
            raise KeyError(target_user_id)

        normalized_new_password = self._validate_password(new_password)
        next_salt_hex = secrets.token_hex(16)
        target_user["password_salt"] = next_salt_hex
        target_user["password_hash"] = self._hash_password(normalized_new_password, next_salt_hex)
        target_user["password_changed_at"] = iso_now()
        target_user["password_reset_by_admin_at"] = iso_now()
        self.repository.update_user(target_user_id, target_user)
        self.repository.delete_auth_sessions_for_user(target_user_id)
        return self._public_user(self.repository.get_user(target_user_id) or target_user)
