import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    employee_id: str | None = None
    roles: list[str] = ["trainee"]
    temporary_password: str = Field(min_length=12)


class UpdateUserRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    employee_id: str | None = None
    status: str | None = None


class AssignRoleRequest(BaseModel):
    role: str


class UserDetailOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    employee_id: str | None
    status: str
    roles: list[str]
    last_login_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None

    model_config = {"from_attributes": True}


class PermissionOut(BaseModel):
    id: uuid.UUID
    resource: str
    action: str
    description: str | None

    model_config = {"from_attributes": True}
