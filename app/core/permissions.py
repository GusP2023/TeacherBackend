"""
Sistema de permisos de ProfesorSYS
====================================

Filosofía:
  - Los permisos viven en código (PERMISSION_DEFAULTS), NO en la BD.
  - La BD solo guarda las *diferencias* respecto al default (en JSONB).
  - Agregar una nueva acción = solo tocar este archivo, sin migraciones.

Reglas de resolución:
  1. organization_id es NULL (profesor independiente) → acceso total, igual que org_admin.
  2. role == 'org_admin' → acceso total, los overrides de la org NO aplican.
  3. Cualquier otro rol en una organización → defaults del rol + overrides de la org.

Namespace de claves (usar siempre "dominio.accion"):
  students.*   → operaciones sobre alumnos
  classes.*    → operaciones sobre clases/asistencia/recuperaciones
  finances.*   → acceso a información financiera
  org.*        → operaciones administrativas de la organización

  Lectura vs escritura en students:
    students.view_enrollment  → solo ver inscripción (nivel, instrumento, créditos)
    students.edit_enrollment  → modificar inscripción (implica view)
"""

# ── Defaults del sistema ──────────────────────────────────────────────────────
#
# Define el comportamiento base de cada rol.
# Los overrides de la organización solo pueden cambiar valores de 'teacher'.
# 'org_admin' y profesores independientes NUNCA se restringen.

PERMISSION_DEFAULTS: dict[str, dict[str, bool]] = {

    "org_admin": {
        # Acceso total — nunca se restringe, es el dueño/directora
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
        # La institución puede ajustar cualquiera mediante overrides
        # excepto los protegidos por ALWAYS_ALLOWED_KEYS.
        "students.create":            False,  # No registra alumnos nuevos
        "students.view_enrollment":   True,   # Puede ver inscripción (nivel, créditos)
        "students.edit_personal":     True,   # Protegido: siempre puede editar datos personales
        "students.edit_enrollment":   False,  # No modifica inscripción
        "students.edit_schedule":     False,  # No modifica horarios
        "students.suspend":           False,  # No suspende alumnos
        "students.delete":            False,  # No puede borrar alumnos
        "classes.mark_attendance":    True,   # Protegido: función principal del profesor
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
        # Asistente académico: solo lectura de alumnos y agenda global.
        # No edita datos, no tiene acceso a finanzas.
        "students.create":            False,
        "students.view_enrollment":   True,   # Puede ver inscripción
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
        # No marca asistencias (eso es del profesor en la app mobile).
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

# Roles que NUNCA reciben restricciones, sin importar los overrides de la org
UNRESTRICTED_ROLES = {"org_admin"}

# Claves que NUNCA se pueden restringir para ningún rol
# (evitan que una org deje la app del profesor completamente inutilizable)
ALWAYS_ALLOWED_KEYS = {"students.edit_personal", "classes.mark_attendance"}


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

    Casos especiales:
      - organization_id is None → profesor independiente → acceso total
      - role in UNRESTRICTED_ROLES → acceso total sin restricciones
    """
    # Acceso total: independiente o rol sin restricciones
    if organization_id is None or role in UNRESTRICTED_ROLES:
        return dict(PERMISSION_DEFAULTS["org_admin"])

    # Base: defaults del rol
    base = dict(PERMISSION_DEFAULTS.get(role, PERMISSION_DEFAULTS["teacher"]))

    # Aplicar overrides individuales del teacher
    if custom_permissions and isinstance(custom_permissions, dict):
        for key, value in custom_permissions.items():
            if key not in base:
                continue  # Ignora claves desconocidas
            if key in ALWAYS_ALLOWED_KEYS:
                continue  # Nunca se puede restringir una clave protegida
            base[key] = bool(value)

    return base


def get_overridable_keys_for_role(role: str) -> list[str]:
    """
    Retorna las claves que la organización puede configurar para un rol dado.
    Excluye las claves protegidas (ALWAYS_ALLOWED_KEYS).

    Útil para el endpoint que muestra qué permisos puede configurar el org_admin
    en la app Admin web.
    """
    defaults = PERMISSION_DEFAULTS.get(role, {})
    return [k for k in defaults if k not in ALWAYS_ALLOWED_KEYS]
