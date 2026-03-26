-- ============================================================
-- Migración 007: Agregar role_permissions a organizations
-- ============================================================
-- SEGURA: Solo agrega una columna nullable. No modifica datos existentes.
--
-- QUÉ HACE:
--   Agrega la columna role_permissions (JSONB, nullable) a organizations.
--   Esta columna guarda SOLO las diferencias respecto a los defaults del sistema.
--   Si es NULL → la organización usa los defaults tal cual (sin restricciones).
--
-- FORMATO DEL JSONB:
--   {
--     "teacher": {
--       "students.create": false,
--       "students.edit_enrollment": false,
--       "classes.create_recovery": false
--     }
--   }
--   Solo se guardan las claves que difieren del default — no todas.
--
-- CÓMO EJECUTAR:
--   psql -U postgres -d music_school -f migrations/007_add_role_permissions.sql
-- ============================================================

BEGIN;

ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS role_permissions JSONB DEFAULT NULL;

COMMENT ON COLUMN organizations.role_permissions IS
    'Overrides de permisos por rol. NULL = usa defaults del sistema (sin restricciones). '
    'Formato: {"teacher": {"students.create": false, ...}}. '
    'Las claves protegidas (students.edit_personal, classes.mark_attendance) se ignoran aunque se incluyan.';

-- Verificación
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'organizations' AND column_name = 'role_permissions'
    ) THEN
        RAISE NOTICE 'OK: columna role_permissions agregada a organizations.';
    ELSE
        RAISE EXCEPTION 'ERROR: la columna role_permissions no fue creada.';
    END IF;
END;
$$;

COMMIT;

-- ROLLBACK:
-- ALTER TABLE organizations DROP COLUMN IF EXISTS role_permissions;
