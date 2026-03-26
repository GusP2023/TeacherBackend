"""
CRUD operations for Invitation model
"""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.invitation import Invitation
from app.schemas.invitation import InvitationCreate


async def create(
    db: AsyncSession,
    data: InvitationCreate,
    organization_id: int,
    invited_by_id: int,
    expires_hours: int = 48,
) -> Invitation:
    """
    Crea una invitación con token único y expiración.

    Args:
        data: Email y rol del invitado
        organization_id: Organización que invita
        invited_by_id: Teacher org_admin que crea la invitación
        expires_hours: Horas de validez (default 48)
    """
    # Código corto y legible: 8 chars hex en mayúsculas, formato XXXX-XXXX
    # Suficientemente seguro para invitaciones de 48h en una app privada
    raw = secrets.token_hex(4).upper()
    token = f"{raw[:4]}-{raw[4:]}"  # ej: A3K9-PX2M
    expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

    invitation = Invitation(
        organization_id=organization_id,
        email=data.email,
        role=data.role,
        token=token,
        expires_at=expires_at,
        invited_by_id=invited_by_id,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    return invitation


async def get_by_token(db: AsyncSession, token: str) -> Invitation | None:
    """Obtiene una invitación por su token."""
    result = await db.execute(
        select(Invitation).where(Invitation.token == token)
    )
    return result.scalar_one_or_none()


async def mark_used(db: AsyncSession, invitation: Invitation) -> Invitation:
    """Marca una invitación como usada."""
    invitation.used_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(invitation)
    return invitation


async def list_by_org(
    db: AsyncSession,
    organization_id: int,
    only_pending: bool = False,
) -> list[Invitation]:
    """Lista las invitaciones de una organización."""
    query = select(Invitation).where(Invitation.organization_id == organization_id)
    if only_pending:
        now = datetime.now(timezone.utc)
        query = query.where(
            Invitation.used_at.is_(None),
            Invitation.expires_at > now,
        )
    result = await db.execute(query.order_by(Invitation.created_at.desc()))
    return list(result.scalars().all())
