import re
import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)

    @field_validator("new_password")
    @classmethod
    def validate_password_policy(cls, v: str) -> str:
        errors = []
        if not re.search(r"[A-Z]", v):
            errors.append("one uppercase letter")
        if not re.search(r"[a-z]", v):
            errors.append("one lowercase letter")
        if not re.search(r"\d", v):
            errors.append("one digit")
        if not re.search(r"[!@#$%^&*()\-_=+\[\]{}|;:',.<>?/`~\"\\]", v):
            errors.append("one special character")
        if errors:
            raise ValueError(f"Password must contain at least: {', '.join(errors)}")
        return v


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    roles: list[str]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserOut


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    roles: list[str]
    permissions: list[str]


class CurrentUser(BaseModel):
    id: str
    roles: list[str]
    jti: str = ""

    model_config = {"from_attributes": True}
