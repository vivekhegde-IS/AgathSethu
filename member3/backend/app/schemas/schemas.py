"""
AGHAT SETHU — Pydantic Schemas for Request/Response Validation
"""

import re
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator


# ── Auth Schemas ──────────────────────────────────────────────────────────────────

class CitizenRegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    # Vehicle plate for initial registration (optional in this phase)
    vehicle_plate: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("full_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Full name cannot be empty")
        return v.strip()


class AuthorityRegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    badge_number: str
    jurisdiction: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("badge_number")
    @classmethod
    def badge_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Badge number cannot be empty")
        return v.strip().upper()


class LoginRequest(BaseModel):
    # Username (seeded demo accounts, e.g. "arjun.rao") or email address
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def identifier_present(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 255:
            raise ValueError("Enter your username or email")
        return v


class ProfileUpdateRequest(BaseModel):
    """Self-service profile edit (name, email, mobile)."""
    full_name: str
    email: EmailStr
    phone: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 2 <= len(v) <= 100:
            raise ValueError("Full name must be 2-100 characters")
        if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", v):
            raise ValueError("Full name may contain only letters, spaces and . ' -")
        return v

    @field_validator("phone")
    @classmethod
    def phone_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        digits = re.sub(r"[\s-]", "", v.strip())
        match = re.fullmatch(r"(?:\+91|91|0)?([6-9]\d{9})", digits)
        if not match:
            raise ValueError("Enter a valid 10-digit Indian mobile number")
        return f"+91{match.group(1)}"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    status: str
    badge_number: Optional[str] = None
    phone: Optional[str] = None
    jurisdiction: Optional[str] = None
    created_at: datetime
    username: Optional[str] = None
    google_email: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def convert_uuid(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v


class RegisterResponse(BaseModel):
    message: str
    user_id: str
    status: str


class MessageResponse(BaseModel):
    message: str


# ── Vehicle Schemas (scaffold for future) ─────────────────────────────────────────
class VehicleResponse(BaseModel):
    id: str
    plate_number: str
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    color: Optional[str] = None
    vehicle_type: Optional[str] = None
    fastag_id: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def convert_uuid(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v
