-- ============================================================
-- Migración 005: Crear tabla security_logs
-- ============================================================
-- SEGURA: Solo agrega una tabla nueva. Sin impacto en datos existentes.
--
-- CÓMO EJECUTAR:
--   psql -U postgres -d music_school -f migrations/005_add_security_logs.sql
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS security_logs (
    id          SERIAL PRIMARY KEY,
    teacher_id  INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    action      VARCHAR(60)  NOT NULL,
    resource    VARCHAR(60),
    resource_id INTEGER,
    ip_address  VARCHAR(45),
    user_agent  VARCHAR(300),
    success     BOOLEAN      NOT NULL DEFAULT TRUE,
    detail      TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_security_logs_teacher_id ON security_logs(teacher_id);
CREATE INDEX IF NOT EXISTS ix_security_logs_action     ON security_logs(action);
CREATE INDEX IF NOT EXISTS ix_security_logs_created_at ON security_logs(created_at DESC);

COMMENT ON TABLE security_logs IS
    'Registro inmutable de eventos de seguridad. Solo INSERT, nunca UPDATE/DELETE.';

DO $$
BEGIN
    RAISE NOTICE '=== Migración 005 completada: tabla security_logs creada ===';
END;
$$;

COMMIT;
