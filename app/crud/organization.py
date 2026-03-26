"""
CRUD operations for Organization model
"""
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.organization import Organization
from app.schemas.organization import OrganizationCreate


def _slugify(name: str) -> str:
    """Convierte un nombre en slug URL-friendly."""
    slug = name.lower().strip()
    slug = re.sub(r'[àáâãäåā]', 'a', slug)
    slug = re.sub(r'[èéêëē]', 'e', slug)
    slug = re.sub(r'[ìíîïī]', 'i', slug)
    slug = re.sub(r'[òóôõöō]', 'o', slug)
    slug = re.sub(r'[ùúûüū]', 'u', slug)
    slug = re.sub(r'[ñ]', 'n', slug)
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:80]  # máximo 80 chars del slug base


async def create(db: AsyncSession, data: OrganizationCreate) -> Organization:
    """
    Crea una organización nueva con slug único.
    Si el slug base ya existe, agrega sufijo numérico.
    """
    base_slug = _slugify(data.name)

    # Garantizar slug único
    slug = base_slug
    counter = 1
    while True:
        existing = await get_by_slug(db, slug)
        if not existing:
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    org = Organization(name=data.name, slug=slug)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def get(db: AsyncSession, org_id: int) -> Organization | None:
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    return result.scalar_one_or_none()


async def get_by_slug(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(select(Organization).where(Organization.slug == slug))
    return result.scalar_one_or_none()
