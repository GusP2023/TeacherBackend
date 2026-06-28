"""Schemas Pydantic v2 para EnrollmentNote."""

from datetime import date as datetime_date, datetime as datetime_type
from decimal import Decimal
from typing import Optional
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ConfigDict, Field

from app.models.enrollment_note import NoteType


# ── Create ───────────────────────────────────────────────────────────────────

class EnrollmentNoteCreate(BaseModel):
    enrollment_id: int
    type: NoteType
    content: str = Field(..., min_length=1, max_length=2000)
    due_date: Optional[datetime_type] = None   # solo reminder/evaluation
    score: Optional[Decimal] = Field(None, ge=0, le=100)  # solo evaluation
    notification_offset_minutes: Optional[int] = 0


# ── Update ───────────────────────────────────────────────────────────────────

class EnrollmentNoteUpdate(BaseModel):
    """Todos los campos opcionales. Solo el autor puede actualizar."""
    content:      Optional[str]            = Field(None, min_length=1, max_length=2000)
    due_date:     Optional[datetime_type]  = None
    score:        Optional[Decimal]        = Field(None, ge=0, le=100)
    is_completed: Optional[bool]           = None
    notification_offset_minutes: Optional[int] = None


# ── Response ─────────────────────────────────────────────────────────────────

class EnrollmentNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:            int
    enrollment_id: int
    teacher_id:    int
    type:          NoteType
    content:       str
    due_date:      Optional[datetime_type]
    score:         Optional[Decimal]
    is_completed:  bool
    notification_offset_minutes: Optional[int] = 0
    created_at:    datetime_type
    updated_at:    datetime_type
