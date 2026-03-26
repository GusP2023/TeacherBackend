-- ============================================================
-- Migración 006: Campos de perfil del profesor + tabla teacher_instruments
-- ============================================================
-- QUÉ HACE:
--   1. Agrega birthdate, bio, avatar_url a teachers
--   2. Crea tabla teacher_instruments (many-to-many Teacher <-> Instrument)
--
-- SEGURA: 100% aditiva. No modifica ni elimina datos existentes.
--
-- CÓMO EJECUTAR:
--   psql -U postgres -d music_school -f migrations/006_add_teacher_profile_fields.sql
-- ============================================================

BEGIN;

-- ============================================================
-- PASO 1: Nuevos campos de perfil en teachers
-- ============================================================

ALTER TABLE teachers
    ADD COLUMN IF NOT EXISTS birthdate     DATE,
    ADD COLUMN IF NOT EXISTS bio           TEXT,
    ADD COLUMN IF NOT EXISTS avatar_url    VARCHAR(500);

COMMENT ON COLUMN teachers.birthdate   IS 'Fecha de nacimiento del profesor';
COMMENT ON COLUMN teachers.bio         IS 'Descripción o presentación breve del profesor';
COMMENT ON COLUMN teachers.avatar_url  IS 'URL de la foto de perfil';

-- ============================================================
-- PASO 2: Tabla many-to-many teacher_instruments
-- ============================================================

CREATE TABLE IF NOT EXISTS teacher_instruments (
    teacher_id    INTEGER NOT NULL REFERENCES teachers(id)    ON DELETE CASCADE,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    PRIMARY KEY (teacher_id, instrument_id)
);

CREATE INDEX IF NOT EXISTS ix_teacher_instruments_teacher_id
    ON teacher_instruments(teacher_id);

CREATE INDEX IF NOT EXISTS ix_teacher_instruments_instrument_id
    ON teacher_instruments(instrument_id);

COMMENT ON TABLE teacher_instruments IS
    'Relación many-to-many entre profesores e instrumentos que enseñan';

-- ============================================================
-- VERIFICACIÓN
-- ============================================================

DO $$
BEGIN
    RAISE NOTICE '=== Migración 006 completada ===';
    RAISE NOTICE 'Columnas agregadas: birthdate, bio, avatar_url en teachers';
    RAISE NOTICE 'Tabla creada: teacher_instruments';
END;
$$;

COMMIT;

-- ============================================================
-- ROLLBACK
-- ============================================================
-- BEGIN;
-- DROP TABLE IF EXISTS teacher_instruments;
-- ALTER TABLE teachers
--     DROP COLUMN IF EXISTS birthdate,
--     DROP COLUMN IF EXISTS bio,
--     DROP COLUMN IF EXISTS avatar_url;
-- COMMIT;
