-- Runs once on first container start. Recreates the pos slice of the G2 DB
-- bootstrap so RLS is genuinely testable locally: the app connects as the
-- NOBYPASSRLS runtime role, migrations run as the owner role.

-- Owner role: owns the schema and the migrated objects (NOLOGIN).
CREATE ROLE tillflow_pos_owner NOLOGIN NOBYPASSRLS;

-- Runtime role: what the app connects as. NOBYPASSRLS -> RLS is enforced.
CREATE ROLE tillflow_pos LOGIN PASSWORD 'pos_secret' NOBYPASSRLS;

CREATE SCHEMA IF NOT EXISTS pos AUTHORIZATION tillflow_pos_owner;

-- The migration/admin role (the superuser `tillflow`) must be able to SET ROLE
-- to the owner. Superuser can already, but be explicit.
GRANT tillflow_pos_owner TO tillflow;

GRANT CONNECT ON DATABASE tillflow TO tillflow_pos;
GRANT USAGE ON SCHEMA pos TO tillflow_pos;

-- Default privileges fire only for objects created BY the owner role — which is
-- why migrations run as tillflow_pos_owner (see alembic/env.py).
ALTER DEFAULT PRIVILEGES FOR ROLE tillflow_pos_owner IN SCHEMA pos
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tillflow_pos;
ALTER DEFAULT PRIVILEGES FOR ROLE tillflow_pos_owner IN SCHEMA pos
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO tillflow_pos;
ALTER DEFAULT PRIVILEGES FOR ROLE tillflow_pos_owner IN SCHEMA pos
  GRANT EXECUTE ON FUNCTIONS TO tillflow_pos;

ALTER ROLE tillflow_pos SET search_path = pos;
