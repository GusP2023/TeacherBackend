"""
Script de gestión de organización — ProfesorSYS
================================================

Comandos disponibles:
    status          → Ver estado actual de tu org y teachers
    rename          → Renombrar tu organización
    set-admin       → Asegurarse de que un teacher sea org_admin

Uso:
    cd C:\\ProfesorSYS\\backend
    venv\\Scripts\\activate
    python -m app.scripts.manage_org status
    python -m app.scripts.manage_org rename "Escuela de Música Armonía"
"""

import asyncio
import sys
from sqlalchemy import select, update
from app.core.database import async_session_maker
from app.models.teacher import Teacher
from app.models.organization import Organization


async def status():
    """Muestra el estado completo de organizaciones y teachers."""
    async with async_session_maker() as db:
        # Organizaciones
        orgs = (await db.execute(select(Organization).order_by(Organization.id))).scalars().all()
        teachers = (await db.execute(select(Teacher).order_by(Teacher.id))).scalars().all()

        print("\n" + "="*60)
        print("  ESTADO DE LA BASE DE DATOS — ProfesorSYS")
        print("="*60)

        print(f"\n📁 ORGANIZACIONES ({len(orgs)} total)\n")
        if not orgs:
            print("  ⚠️  No hay ninguna organización creada.")
        for org in orgs:
            members = [t for t in teachers if t.organization_id == org.id]
            admins  = [t for t in members if t.role == 'org_admin']
            status_icon = "✅" if org.active else "❌"
            print(f"  {status_icon} [{org.id}] {org.name}")
            print(f"       slug: {org.slug}")
            print(f"       permisos custom: {'sí' if org.role_permissions else 'no (usa defaults)'}")
            print(f"       miembros: {len(members)} | admins: {len(admins)}")
            for t in members:
                role_icon = "👑" if t.role == 'org_admin' else "👤"
                active_str = "" if t.active else " [INACTIVO]"
                print(f"         {role_icon} [{t.id}] {t.name} <{t.email}> — {t.role}{active_str}")
            print()

        # Teachers sin org
        sin_org = [t for t in teachers if t.organization_id is None]
        if sin_org:
            print(f"⚠️  TEACHERS SIN ORGANIZACIÓN ({len(sin_org)})\n")
            for t in sin_org:
                print(f"  🔴 [{t.id}] {t.name} <{t.email}> — {t.role}")
            print()

        print("="*60)
        print(f"  Total teachers: {len(teachers)} | Sin org: {len(sin_org)}")
        print("="*60 + "\n")


async def rename(new_name: str, org_id: int | None = None):
    """
    Renombra la organización.
    Si hay una sola, la renombra directamente.
    Si hay varias, requiere --org-id.
    """
    async with async_session_maker() as db:
        orgs = (await db.execute(select(Organization).order_by(Organization.id))).scalars().all()

        if not orgs:
            print("❌ No hay ninguna organización en la BD. Ejecutá 'status' para diagnosticar.")
            return

        # Elegir la org a renombrar
        if org_id:
            target = next((o for o in orgs if o.id == org_id), None)
            if not target:
                print(f"❌ No existe una organización con id={org_id}")
                return
        elif len(orgs) == 1:
            target = orgs[0]
        else:
            print(f"⚠️  Hay {len(orgs)} organizaciones. Especificá con --org-id N cuál renombrar:")
            for o in orgs:
                print(f"   [{o.id}] {o.name}")
            return

        # Generar slug desde el nombre
        import re
        slug = re.sub(r'[^a-z0-9]+', '-', new_name.lower()).strip('-')
        # Verificar unicidad del slug
        existing_slug = (await db.execute(
            select(Organization).where(Organization.slug == slug, Organization.id != target.id)
        )).scalar_one_or_none()
        if existing_slug:
            slug = f"{slug}-{target.id}"

        old_name = target.name
        target.name = new_name
        target.slug = slug
        await db.commit()

        print(f"\n✅ Organización renombrada:")
        print(f"   Antes: {old_name}")
        print(f"   Ahora: {new_name}  (slug: {slug})\n")


async def set_admin(email: str):
    """Establece un teacher como org_admin (útil si necesitás promover a alguien)."""
    async with async_session_maker() as db:
        teacher = (await db.execute(
            select(Teacher).where(Teacher.email == email)
        )).scalar_one_or_none()

        if not teacher:
            print(f"❌ No existe un teacher con email: {email}")
            return

        if not teacher.organization_id:
            print(f"❌ El teacher '{teacher.name}' no tiene organización asignada.")
            return

        old_role = teacher.role
        teacher.role = 'org_admin'
        await db.commit()

        print(f"\n✅ Rol actualizado:")
        print(f"   Teacher: {teacher.name} <{email}>")
        print(f"   Antes: {old_role}")
        print(f"   Ahora: org_admin\n")


def main():
    args = sys.argv[1:]

    if not args or args[0] == 'status':
        asyncio.run(status())

    elif args[0] == 'rename':
        if len(args) < 2:
            print("❌ Uso: python -m app.scripts.manage_org rename \"Nombre de mi Escuela\"")
            sys.exit(1)
        org_id = None
        if '--org-id' in args:
            idx = args.index('--org-id')
            org_id = int(args[idx + 1])
        asyncio.run(rename(args[1], org_id=org_id))

    elif args[0] == 'set-admin':
        if len(args) < 2:
            print("❌ Uso: python -m app.scripts.manage_org set-admin email@ejemplo.com")
            sys.exit(1)
        asyncio.run(set_admin(args[1]))

    else:
        print(f"❌ Comando desconocido: {args[0]}")
        print("Comandos: status | rename \"Nombre\" | set-admin email@ejemplo.com")
        sys.exit(1)


if __name__ == '__main__':
    main()
