-- ============================================================
-- Migración 011: Agregar custom_permissions a teachers
-- ============================================================
-- SEGURA: Solo agrega una columna nullable. No modifica datos existentes.
--
-- QUÉ HACE:
--   Agrega la columna custom_permissions (JSONB, nullable) a teachers.
--   Reemplaza el sistema de role_permissions a nivel organización por
--   overrides individuales por teacher.
--
--   Si es NULL → el teacher usa los defaults de su rol sin modificaciones.
--   Si tiene valor → sus permisos efectivos son defaults + estos overrides.
--
-- FORMATO DEL JSONB:
--   {
--     "students.create": false,
--     "classes.delete": false
--   }
--   Solo se guardan las claves que difieren del default del rol.
--
-- RELACIÓN CON MIGRACIÓN 007:
--   La columna role_permissions en organizations queda en BD pero ya no
--   es usada por el sistema (el modelo Organization ya no la expone).
--   Se puede eliminar en una migración futura cuando se confirme que
--   ningún dato histórico la necesita.
-- ============================================================

BEGIN;

ALTER TABLE teachers
    ADD COLUMN IF NOT EXISTS custom_permissions JSONB DEFAULT NULL;

COMMENT ON COLUMN teachers.custom_permissions IS
    'Overrides de permisos individuales del teacher. NULL = usa defaults del rol sin modificaciones. '
    'Formato: {"students.create": false, "classes.delete": true}. '
    'Las claves protegidas (ALWAYS_ALLOWED_KEYS) se ignoran aunque se incluyan.';

-- Verificación
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'teachers' AND column_name = 'custom_permissions'
    ) THEN
        RAISE NOTICE 'OK: columna custom_permissions agregada a teachers.';
    ELSE
        RAISE EXCEPTION 'ERROR: la columna custom_permissions no fue creada.';
    END IF;
END;
$$;

COMMIT;

-- ROLLBACK:
-- ALTER TABLE teachers DROP COLUMN IF EXISTS custom_permissions;
