-- Shared tillflow DB (same container as POS/payments). Run as superuser once.
-- Role name matches migrations' tillflow_commission grants; local password is demo-only.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tillflow_commission') THEN
    CREATE ROLE tillflow_commission LOGIN PASSWORD 'secret';
  END IF;
END
$$;

GRANT CONNECT ON DATABASE tillflow TO tillflow_commission;
GRANT CREATE ON DATABASE tillflow TO tillflow_commission;

GRANT USAGE ON SCHEMA payments TO tillflow_commission;
GRANT USAGE ON SCHEMA pos TO tillflow_commission;

GRANT SELECT ON payments.v_paid_sales_for_commission TO tillflow_commission;
GRANT SELECT ON pos.v_sales_for_commission TO tillflow_commission;
GRANT SELECT ON pos.v_commission_rates_current TO tillflow_commission;
GRANT SELECT ON pos.v_attendants_for_payout TO tillflow_commission;

-- Alias used by .env.example (commission:secret@...)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'commission') THEN
    CREATE ROLE commission LOGIN PASSWORD 'secret' IN ROLE tillflow_commission;
  END IF;
END
$$;

GRANT CONNECT, CREATE ON DATABASE tillflow TO commission;
GRANT tillflow_commission TO commission;
