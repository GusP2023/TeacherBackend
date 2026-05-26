-- ============================================================
-- Migración 012: Agregar modelo de Eventos
-- ============================================================
-- SEGURA: Solo crea tablas nuevas. No modifica tablas existentes.
--
-- Crea:
--   events         → Evento institucional (ensayo, workshop, masterclass, etc.)
--   event_teachers → M2M: profesores titulares de un evento
--   event_students → M2M: alumnos participantes de un evento
--
-- Tipos de evento soportados (almacenados como VARCHAR, sin enum):
--   rehearsal | workshop | masterclass | external | other
--
-- Notas:
--   - room_id nullable: un evento puede no tener sala asignada
--   - created_by_id SET NULL: si el teacher se elimina, el evento persiste
--   - guest_name + guest_email: invitado externo (no es teacher de la institución)
--   - La sucursal se deriva de room.branch_id cuando room_id no es null
-- ============================================================

BEGIN;

-- 1. Tabla principal de eventos
CREATE TABLE events (
    id              SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    room_id         INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    title           VARCHAR(200) NOT NULL,
    description     TEXT,
    event_type      VARCHAR(50) NOT NULL DEFAULT 'other',
    date            DATE NOT NULL,
    time_start      TIME NOT NULL,
    duration        INTEGER NOT NULL,
    guest_name      VARCHAR(200),
    guest_email     VARCHAR(255),
    notes           TEXT,
    created_by_id   INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_events_organization_date ON events(organization_id, date);
CREATE INDEX ix_events_room_date         ON events(room_id, date);
CREATE INDEX ix_events_date              ON events(date);
CREATE INDEX ix_events_created_by        ON events(created_by_id);

COMMENT ON COLUMN events.event_type IS
    'Tipo de evento: rehearsal | workshop | masterclass | external | other';
COMMENT ON COLUMN events.guest_email IS
    'Email del invitado externo para invitación de Google Calendar';
COMMENT ON COLUMN events.duration IS
    'Duración del evento en minutos';

-- 2. Profesores titulares del evento (M2M)
CREATE TABLE event_teachers (
    event_id   INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, teacher_id)
);

CREATE INDEX ix_event_teachers_teacher_id ON event_teachers(teacher_id);

-- 3. Alumnos participantes del evento (M2M)
CREATE TABLE event_students (
    event_id   INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, student_id)
);

CREATE INDEX ix_event_students_student_id ON event_students(student_id);

-- Verificación
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'events')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'event_teachers')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'event_students')
    THEN
        RAISE NOTICE 'OK: tablas events, event_teachers y event_students creadas correctamente.';
    ELSE
        RAISE EXCEPTION 'ERROR: una o más tablas no fueron creadas.';
    END IF;
END;
$$;

COMMIT;

-- ROLLBACK (en caso de necesitar revertir):
-- DROP TABLE IF EXISTS event_students;
-- DROP TABLE IF EXISTS event_teachers;
-- DROP TABLE IF EXISTS events;
