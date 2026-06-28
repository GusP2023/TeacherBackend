"""
Endpoints CRUD de EnrollmentNote — usados exclusivamente por mobile.

Visibilidad:
  - GET /?enrollment_id=X  → verifica que enrollment.teacher_id == current_teacher.id,
                              luego devuelve TODAS las notas del enrollment
                              (incluyendo las de profesores anteriores).
  - POST / PATCH / DELETE  → solo el autor (note.teacher_id == current_teacher.id)
                              puede crear/editar/borrar sus propias notas.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.models.teacher import Teacher
from app.models.enrollment import Enrollment
from app.models.enrollment_note import EnrollmentNote
from app.schemas.enrollment_note import (
    EnrollmentNoteCreate,
    EnrollmentNoteUpdate,
    EnrollmentNoteResponse,
)

router = APIRouter()


# ── helpers ──────────────────────────────────────────────────────────────────

async def _get_enrollment_for_teacher(
    enrollment_id: int, teacher_id: int, db: AsyncSession
) -> Enrollment:
    """Obtiene el enrollment verificando que pertenece al teacher. 404 si no."""
    result = await db.execute(
        select(Enrollment).where(
            and_(
                Enrollment.id == enrollment_id,
                Enrollment.teacher_id == teacher_id,
            )
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(404, "Inscripción no encontrada o sin permisos")
    return enrollment


async def _get_own_note(
    note_id: int, teacher_id: int, db: AsyncSession
) -> EnrollmentNote:
    """Obtiene una nota verificando que el teacher es el autor. 404 si no."""
    result = await db.execute(
        select(EnrollmentNote).where(
            and_(
                EnrollmentNote.id == note_id,
                EnrollmentNote.teacher_id == teacher_id,
            )
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(404, "Nota no encontrada o sin permisos")
    return note


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[EnrollmentNoteResponse])
async def list_notes(
    enrollment_id: int = Query(..., description="ID de la inscripción"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """
    Lista TODAS las notas de una inscripción.
    Incluye notas de profesores anteriores (historial completo del alumno).
    Solo accesible si el teacher es el profesor actual de esa inscripción.
    Ordenadas por created_at DESC (más recientes primero).
    """
    await _get_enrollment_for_teacher(enrollment_id, current_teacher.id, db)

    result = await db.execute(
        select(EnrollmentNote)
        .where(EnrollmentNote.enrollment_id == enrollment_id)
        .order_by(EnrollmentNote.created_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=EnrollmentNoteResponse, status_code=201)
async def create_note(
    body: EnrollmentNoteCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """
    Crea una nueva nota. El teacher_id se asigna desde el token JWT.
    Valida que el enrollment pertenece al teacher actual.
    """
    await _get_enrollment_for_teacher(body.enrollment_id, current_teacher.id, db)

    note = EnrollmentNote(
        enrollment_id=body.enrollment_id,
        teacher_id=current_teacher.id,
        type=body.type,
        content=body.content,
        due_date=body.due_date,
        score=body.score,
        is_completed=False,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


@router.patch("/{note_id}", response_model=EnrollmentNoteResponse)
async def update_note(
    note_id: int,
    body: EnrollmentNoteUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """
    Actualiza una nota. Solo el autor puede modificarla.
    Usar para: editar contenido, marcar is_completed, actualizar due_date/score.
    """
    note = await _get_own_note(note_id, current_teacher.id, db)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(note, field, value)

    await db.commit()
    await db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """
    Elimina una nota permanentemente. Solo el autor puede eliminarla.
    """
    note = await _get_own_note(note_id, current_teacher.id, db)
    await db.delete(note)
    await db.commit()
