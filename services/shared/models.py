"""Shared Pydantic v2 data models used across all agent services."""
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


# ── Auth Models ────────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    engineer = "engineer"
    admin = "admin"


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: Optional[str] = None
    role: UserRole = UserRole.engineer
    is_active: bool = True
    created_at: datetime
    last_login: Optional[datetime] = None


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v: str) -> str:
        return v.lower().strip()


class UserLogin(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    engineer_id: str
    role: str


class TokenPayload(BaseModel):
    sub: str   # email
    role: str
    exp: int   # unix timestamp


# ── Business Unit ──────────────────────────────────────────────────────────────


class BusinessUnit(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: Optional[str] = None


# ── Ticket & Incident ──────────────────────────────────────────────────────────


class Ticket(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    jira_id: str
    business_unit: Optional[str] = None
    ticket_type: Optional[str] = None
    summary: str
    description: Optional[str] = None
    status: Optional[str] = None
    resolution: Optional[str] = None
    discussion: Optional[list[dict]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # embedding excluded from serialization by default
    raw_json: Optional[dict] = None


class Incident(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    jira_id: Optional[str] = None
    business_unit: Optional[str] = None
    title: str
    description: Optional[str] = None
    root_cause: Optional[str] = None
    long_term_fix: Optional[str] = None
    related_tickets: Optional[list[str]] = None
    severity: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    raw_json: Optional[dict] = None


# ── Chat & Session ─────────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: Optional[datetime] = None
    metadata: Optional[dict] = None


class BusinessUnitScope(BaseModel):
    business_units: list[str]
    include_incidents: bool = False

    @field_validator("business_units")
    @classmethod
    def at_least_one_bu(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least one business unit must be selected")
        return v


class ChatSession(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    engineer_id: str
    title: Optional[str] = None
    context_scope: Optional[BusinessUnitScope] = None
    messages: Optional[list[ChatMessage]] = None
    created_at: datetime
    updated_at: datetime


class SessionSummary(BaseModel):
    id: uuid.UUID
    title: Optional[str] = None
    last_message_preview: Optional[str] = None
    updated_at: datetime


# ── Feedback ───────────────────────────────────────────────────────────────────


class FeedbackRating(str, Enum):
    correct = "correct"
    can_be_better = "can_be_better"
    incorrect = "incorrect"


class EngineerFeedback(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    session_id: uuid.UUID
    message_index: int
    rating: FeedbackRating
    comment: Optional[str] = None
    created_at: Optional[datetime] = None


class FeedbackInput(BaseModel):
    session_id: uuid.UUID
    message_index: int
    rating: FeedbackRating
    comment: Optional[str] = None


class FeedbackSummary(BaseModel):
    total: int
    correct: int
    can_be_better: int
    incorrect: int
    accuracy_pct: float


# ── Agent & Search ─────────────────────────────────────────────────────────────


class ToolResult(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None


class SearchResult(BaseModel):
    jira_id: str
    title: str
    summary: Optional[str] = None
    score: float
    result_type: Literal["ticket", "incident"]
    status: Optional[str] = None
    business_unit: Optional[str] = None
    metadata: Optional[dict] = None


class SearchQuery(BaseModel):
    query_text: str
    business_units: list[str]
    include_incidents: bool = False
    top_k: int = 10

    @field_validator("top_k")
    @classmethod
    def top_k_range(cls, v: int) -> int:
        if not 1 <= v <= 50:
            raise ValueError("top_k must be between 1 and 50")
        return v


class AgentRequest(BaseModel):
    session_id: Optional[uuid.UUID] = None
    engineer_id: str
    message: str
    context_scope: BusinessUnitScope
    conversation_history: Optional[list[ChatMessage]] = None


class AgentResponse(BaseModel):
    session_id: Optional[uuid.UUID] = None
    response_text: str
    sources: Optional[list[SearchResult]] = None
    usage_metadata: Optional[dict] = None
