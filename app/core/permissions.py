"""
Sistema de permisos de ProfesorSYS
====================================

Filosofía:
  - Los permisos viven en código (PERMISSION_DEFAULTS), NO en la BD.
  - La BD solo guarda las *diferencias* respecto al default (custom_permissions en JSONB).
  - Agregar una nueva acción = solo tocar este archivo, sin migraciones.

Reglas de resolución:
  1. organization_id es NULL (profesor independiente) → acceso total siempre.
  2. Cualquier otro caso → defaults del rol + custom_permissions del teacher (sin restricciones).

El sistema no tiene opinión sobre qué permisos son "importantes" o "protegidos".
Eso lo decide el org_admin de cada institución. El sistema solo ejecuta.

Namespace de claves (usar siempre "dominio.accion"):
  students.*   → operaciones sobre alumnos
  classes.*    → operaciones sobre clases/asistencia/recuperaciones
  finances.*   → acceso a información financiera
  org.*        → operaciones administrativas de la organización
"""

# ── Defaults del sistema ──────────────────────────────────────────────────────
#
# Define el comportamiento BASE de cada rol al ser creado.
# El org_admin puede sobreescribir cualquier permiso de cualquier miembro
# sin restricciones, usando custom_permissions en la BD.

PERMISSION_DEFAULTS: dict[str, dict[str, bool]] = {

    "org_admin": {
        # Acceso total por default — dueño/director de la institución.
        # Un org_admin puede configurar los permisos de otro org_admin.
        "students.create":            True,
        "students.view_enrollment":   True,
        "students.edit_personal":     True,
        "students.edit_enrollment":   True,
        "students.edit_schedule":     True,
        "students.suspend":           True,
        "students.delete":            True,
        "classes.mark_attendance":    True,
        "classes.create_recovery":    True,
        "classes.delete":             True,
        "finances.view_own":          True,
        "finances.view_all":          True,
        "org.manage_users":           True,
        "org.invite_teacher":         True,
        "org.change_teacher_role":    True,
        "org.configure_permissions":  True,
        "org.reset_total":            True,
    },

    "teacher": {
        # Defaults para un profesor dentro de una institución.
        "students.create":            False,
        "students.view_enrollment":   True,
        "students.edit_personal":     True,
        "students.edit_enrollment":   False,
        "students.edit_schedule":     False,
        "students.suspend":           False,
        "students.delete":            False,
        "classes.mark_attendance":    True,
        "classes.create_recovery":    True,
        "classes.delete":             False,
        "finances.view_own":          True,
        "finances.view_all":          False,
        "org.manage_users":           False,
        "org.invite_teacher":         False,
        "org.change_teacher_role":    False,
        "org.configure_permissions":  False,
        "org.reset_total":            False,
    },

    "coordinator": {
        # Solo lectura de alumnos y agenda global.
        "students.create":            False,
        "students.view_enrollment":   True,
        "students.edit_personal":     False,
        "students.edit_enrollment":   False,
        "students.edit_schedule":     False,
        "students.suspend":           False,
        "students.delete":            False,
        "classes.mark_attendance":    False,
        "classes.create_recovery":    False,
        "classes.delete":             False,
        "finances.view_own":          False,
        "finances.view_all":          False,
        "org.manage_users":           False,
        "org.invite_teacher":         False,
        "org.change_teacher_role":    False,
        "org.configure_permissions":  False,
        "org.reset_total":            False,
    },

    "administrative": {
        # Secretaria/Admin: registra alumnos, maneja agenda y finanzas.
        "students.create":            True,
        "students.view_enrollment":   True,
        "students.edit_personal":     True,
        "students.edit_enrollment":   True,
        "students.edit_schedule":     True,
        "students.suspend":           True,
        "students.delete":            False,
        "classes.mark_attendance":    False,
        "classes.create_recovery":    True,
        "classes.delete":             False,
        "finances.view_own":          True,
        "finances.view_all":          True,
        "org.manage_users":           False,
        "org.invite_teacher":         False,
        "org.change_teacher_role":    False,
        "org.configure_permissions":  False,
        "org.reset_total":            False,
    },
}


# ── Función principal ─────────────────────────────────────────────────────────

def resolve_permissions(
    role: str,
    organization_id: int | None,
    custom_permissions: dict | None,
) -> dict[str, bool]:
    """
    Resuelve los permisos efectivos para un teacher.

    Dos capas:
      1. Defaults del rol (PERMISSION_DEFAULTS)
      2. Overrides individuales del teacher (custom_permissions en BD)

    El org_admin puede sobreescribir cualquier clave sin restricciones.

    Caso especial:
      - organization_id is None → profesor independiente → acceso total siempre.
    """
    # Profesor independiente (sin organización) → acceso total
    if organization_id is None:
        return dict(PERMISSION_DEFAULTS.get("org_admin", {}))

    # Base: defaults del rol (fallback a teacher si el rol no existe)
    base = dict(PERMISSION_DEFAULTS.get(role, PERMISSION_DEFAULTS["teacher"]))

    # Aplicar overrides individuales sin filtros — el admin decide todo
    if custom_permissions and isinstance(custom_permissions, dict):
        for key, value in custom_permissions.items():
            if key not in base:
                continue  # Ignorar claves desconocidas (forward compatibility)
            base[key] = bool(value)

    return base
