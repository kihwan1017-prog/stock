from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


def _normalize_email(value: str) -> str:
    cleaned = value.strip().lower()
    if (
        "@" not in cleaned
        or cleaned.startswith("@")
        or cleaned.endswith("@")
        or "." not in cleaned.split("@", 1)[-1]
    ):
        raise ValueError("올바른 이메일을 입력하세요.")
    if len(cleaned) > 255:
        raise ValueError("이메일이 너무 깁니다.")
    return cleaned


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    password_confirm: str = Field(min_length=8, max_length=128)
    terms_accepted: bool

    @field_validator("username")
    @classmethod
    def username_format(cls, value: str) -> str:
        cleaned = value.strip().lower()
        allowed = cleaned.replace("_", "").replace("-", "")
        if not allowed.isalnum():
            raise ValueError(
                "아이디는 영문·숫자·-_ 만 사용할 수 있습니다."
            )
        if cleaned[0].isdigit():
            raise ValueError("아이디는 숫자로 시작할 수 없습니다.")
        return cleaned

    @field_validator("name")
    @classmethod
    def name_strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("이름을 입력하세요.")
        return cleaned

    @field_validator("email")
    @classmethod
    def email_format(cls, value: str) -> str:
        return _normalize_email(value)

    @model_validator(mode="after")
    def passwords_match(self) -> SignupRequest:
        if self.password != self.password_confirm:
            raise ValueError("비밀번호와 비밀번호 확인이 일치하지 않습니다.")
        if not self.terms_accepted:
            raise ValueError("약관에 동의해야 회원가입할 수 있습니다.")
        return self


class LoginRequest(BaseModel):
    """username 또는 email 로 로그인."""

    username: str = Field(
        min_length=1,
        max_length=255,
        description="아이디 또는 이메일",
    )
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AuthUserResponse(BaseModel):
    id: str
    username: str
    email: str | None = None
    display_name: str | None = None
    roles: list[str]
    permissions: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUserResponse


class AvailabilityResponse(BaseModel):
    available: bool
    field: str
    value: str


class MemberCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=100)
    roles: list[str] = Field(default_factory=lambda: ["viewer"])
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def optional_email(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        return _normalize_email(str(value))


class RoleResponse(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None
    is_system: bool
    permissions: list[str]


class PermissionResponse(BaseModel):
    id: int
    code: str
    name: str
    category: str
    description: str | None = None


class RolePermissionUpdateRequest(BaseModel):
    permissions: list[str] = Field(min_length=0)


class UserRolesUpdateRequest(BaseModel):
    roles: list[str] = Field(min_length=1)


class MemberUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    roles: list[str] | None = None
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def optional_email(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        return _normalize_email(str(value))


class MemberResetPasswordRequest(BaseModel):
    new_password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
    )


class MemberResponse(BaseModel):
    id: str
    username: str
    email: str | None = None
    display_name: str | None = None
    roles: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    password_changed_at: datetime
    deleted_at: datetime | None = None


class MemberListResponse(BaseModel):
    items: list[MemberResponse]
    total: int
    limit: int
    offset: int


class MemberResetPasswordResponse(BaseModel):
    user: MemberResponse
    temporary_password: str
