-- Payments slice of G2 DB bootstrap (matches infra/modules/db-bootstrap for payments).
-- Run after services/pos/local Postgres is up. Connect as superuser `tillflow`.

CREATE ROLE tillflow_payments_owner NOLOGIN NOBYPASSRLS;
CREATE ROLE tillflow_payments LOGIN PASSWORD 'secret' NOBYPASSRLS;

GRANT tillflow_payments_owner TO tillflow;

CREATE SCHEMA IF NOT EXISTS payments AUTHORIZATION tillflow_payments_owner;
ALTER SCHEMA payments OWNER TO tillflow_payments_owner;

GRANT CONNECT ON DATABASE tillflow TO tillflow_payments;
GRANT USAGE ON SCHEMA payments TO tillflow_payments;

ALTER DEFAULT PRIVILEGES FOR ROLE tillflow_payments_owner IN SCHEMA payments
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tillflow_payments;
ALTER DEFAULT PRIVILEGES FOR ROLE tillflow_payments_owner IN SCHEMA payments
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO tillflow_payments;
ALTER DEFAULT PRIVILEGES FOR ROLE tillflow_payments_owner IN SCHEMA payments
  GRANT EXECUTE ON FUNCTIONS TO tillflow_payments;

ALTER ROLE tillflow_payments SET search_path = payments;
