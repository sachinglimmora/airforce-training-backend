import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)


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

    model_config = {"from_attributes": True}
