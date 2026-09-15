-- Runs once on first container start.
CREATE USER payments WITH PASSWORD 'secret';

-- Needed so Alembic can CREATE SCHEMA / manage objects (Postgres 15+).
GRANT CONNECT, CREATE ON DATABASE tillflow TO payments;

CREATE SCHEMA IF NOT EXISTS payments AUTHORIZATION payments;
GRANT ALL ON SCHEMA payments TO payments;
GRANT ALL ON SCHEMA public TO payments;

ALTER ROLE payments SET search_path TO payments, public;
