-- ============================================================
-- Migración 004: Agregar organizaciones y roles (multi-tenant)
-- ============================================================
-- SEGURA: Migración 100% aditiva. No elimina ni modifica datos.
--
-- QUÉ HACE:
--   1. Crea tabla organizations
--   2. Crea tabla invitations
--   3. Agrega organization_id y role a teachers
--   4. Migra datos existentes:
--      - Una organización por cada teacher existente
--      - Todos los teachers existentes pasan a ser org_admin de su org
--
-- CÓMO EJECUTAR (local):
--   psql -U postgres -d music_school -f migrations/004_add_organizations_and_roles.sql
--
-- CÓMO EJECUTAR (Render/Neon - desde psql conectado):
--   \i /ruta/004_add_organizations_and_roles.sql
--
-- ROLLBACK (si es necesario):
--   Ver sección al final del archivo
-- ============================================================

BEGIN;

-- ============================================================
-- PASO 1: Crear tabla organizations
-- ============================================================

CREATE TABLE IF NOT EXISTS organizations (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255)    NOT NULL,
    slug        VARCHAR(100)    NOT NULL UNIQUE,
    active      BOOLEAN         NOT NULL DEFAULT TRUE,
    notes       TEXT,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_organizations_slug ON organizations(slug);

COMMENT ON TABLE organizations IS 'Escuelas/instituciones - tenant raíz del sistema multi-tenant';

-- ============================================================
-- PASO 2: Agregar columnas a teachers (nullable primero)
-- ============================================================

-- organization_id: nullable porque primero necesitamos crear las orgs
ALTER TABLE teachers
    ADD COLUMN IF NOT EXISTS organization_id INTEGER REFERENCES organizations(id) ON DELETE RESTRICT;

-- role: con default org_admin para que los registros existentes sean admins
ALTER TABLE teachers
    ADD COLUMN IF NOT EXISTS role VARCHAR(50) NOT NULL DEFAULT 'org_admin';

CREATE INDEX IF NOT EXISTS ix_teachers_organization_id ON teachers(organization_id);

COMMENT ON COLUMN teachers.organization_id IS 'FK a la organización a la que pertenece el teacher';
COMMENT ON COLUMN teachers.role IS 'Rol: org_admin | teacher | coordinator | administrative';

-- ============================================================
-- PASO 3: Migrar datos existentes
--
-- Estrategia: crear una organización por cada teacher.
-- Cada teacher es el org_admin de su propia escuela.
-- Esto preserva el modelo actual donde cada teacher es independiente.
-- El org_admin puede luego invitar a otros teachers a su organización.
-- ============================================================

-- Crear una organización por cada teacher existente
-- El nombre de la organización se deriva del nombre del teacher
-- El slug se genera desde el id para garantizar unicidad
INSERT INTO organizations (name, slug, created_at, updated_at)
SELECT
    'Escuela de ' || t.name    AS name,
    'org-teacher-' || t.id     AS slug,   -- único por construcción
    t.created_at,
    t.created_at
FROM teachers t
ON CONFLICT (slug) DO NOTHING;

-- Asignar cada teacher a su organización correspondiente
-- Hace match por el slug que creamos arriba
UPDATE teachers t
SET
    organization_id = o.id,
    role = 'org_admin'
FROM organizations o
WHERE o.slug = 'org-teacher-' || t.id::text;

-- ============================================================
-- PASO 4: Crear tabla invitations
-- ============================================================

CREATE TABLE IF NOT EXISTS invitations (
    id              SERIAL PRIMARY KEY,
    organization_id INTEGER         NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email           VARCHAR(255)    NOT NULL,
    role            VARCHAR(50)     NOT NULL DEFAULT 'teacher',
    token           VARCHAR(64)     NOT NULL UNIQUE,
    expires_at      TIMESTAMPTZ     NOT NULL,
    used_at         TIMESTAMPTZ,
    invited_by_id   INTEGER         NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_invitations_token ON invitations(token);
CREATE INDEX IF NOT EXISTS ix_invitations_organization_id ON invitations(organization_id);
CREATE INDEX IF NOT EXISTS ix_invitations_email ON invitations(email);

COMMENT ON TABLE invitations IS 'Invitaciones para unirse a una organización. Reemplaza el registro público.';

-- ============================================================
-- PASO 5: Verificación — mostrar estado final
-- ============================================================

DO $$
DECLARE
    teacher_count INT;
    org_count     INT;
    unlinked      INT;
BEGIN
    SELECT COUNT(*) INTO teacher_count FROM teachers;
    SELECT COUNT(*) INTO org_count FROM organizations;
    SELECT COUNT(*) INTO unlinked FROM teachers WHERE organization_id IS NULL;

    RAISE NOTICE '=== Migración 004 completada ===';
    RAISE NOTICE 'Teachers en BD:          %', teacher_count;
    RAISE NOTICE 'Organizaciones creadas:  %', org_count;
    RAISE NOTICE 'Teachers sin org (debe ser 0): %', unlinked;

    IF unlinked > 0 THEN
        RAISE WARNING 'ATENCIÓN: % teachers quedaron sin organización. Revisar.', unlinked;
    ELSE
        RAISE NOTICE 'OK: Todos los teachers tienen organización asignada.';
    END IF;
END;
$$;

COMMIT;

-- ============================================================
-- ROLLBACK (ejecutar solo si necesitas revertir)
-- ============================================================
-- BEGIN;
-- DROP TABLE IF EXISTS invitations;
-- ALTER TABLE teachers DROP COLUMN IF EXISTS organization_id;
-- ALTER TABLE teachers DROP COLUMN IF EXISTS role;
-- DROP TABLE IF EXISTS organizations;
-- COMMIT;
