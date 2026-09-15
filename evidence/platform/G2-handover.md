# G2 platform handover

## Scope

This handover covers the platform database foundation for G2. The goal is to
give product and service owners a safe PostgreSQL base for migrations, tenant
isolation tests, payment state handling, and commission logic.

## What platform provides

- AWS RDS PostgreSQL database: `tillflow`
- RDS Proxy endpoint for service connections:
  `devops-g3-db-proxy.proxy-chgiwkc8muat.us-west-1.rds.amazonaws.com`
- Application DB credentials secret: `devops-g3/db`
- Terraform-managed CodeBuild bootstrap project: `devops-g3-db-bootstrap`
- Per-service schemas:
  - `web`
  - `pos`
  - `payments`
  - `commission`
- Per-service runtime roles:
  - `tillflow_web`
  - `tillflow_pos`
  - `tillflow_payments`
  - `tillflow_commission`
- Per-service owner roles:
  - `tillflow_web_owner`
  - `tillflow_pos_owner`
  - `tillflow_payments_owner`
  - `tillflow_commission_owner`

Runtime credentials are generated during the bootstrap build and written
directly to Secrets Manager. They are not stored in Terraform state, committed
to Git, or shared in chat.

## Why the owner/runtime split exists

Runtime service roles must not own tenant tables. PostgreSQL table owners can
bypass row-level-security policy checks unless every table is forced through
RLS. To avoid silent tenant-isolation gaps:

- owner roles own schemas and future migration-created objects
- runtime roles are used by ECS tasks
- runtime roles are `NOBYPASSRLS`
- runtime roles receive application DML grants only
- runtime roles do not receive schema `CREATE`
- runtime role `search_path` is limited to its own schema

Every tenant table migration must include:

```sql
ALTER TABLE <schema>.<table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <schema>.<table> FORCE ROW LEVEL SECURITY;
```

## Migration pattern for service owners

Migrations should run through the controlled migration/admin path and switch to
the matching owner role before creating or altering tables.

Example for POS:

```sql
BEGIN;
SET ROLE tillflow_pos_owner;

-- create or alter POS tables here
-- add tenant_id
-- add tenant-scoped indexes/constraints
-- enable and force RLS
-- create RLS policies

RESET ROLE;
COMMIT;
```

The same pattern applies to:

- `tillflow_web_owner` for `web`
- `tillflow_pos_owner` for `pos`
- `tillflow_payments_owner` for `payments`
- `tillflow_commission_owner` for `commission`

## What service owners can start now

Product and service owners can work in parallel on:

- POS API and sale validation
- payment state machine
- STK request and callback handler logic
- fake Daraja adapter tests
- idempotency tests
- commission calculation logic
- payout ledger logic
- migration files and table design
- unit and contract tests

They do not need direct DB passwords from platform. ECS reads the correct
service-specific JSON key from `devops-g3/db`.

## What platform still needs from the team

### From POS/product

- final sale table design
- tenant, outlet, attendant, and sale validation fields
- sale total invariants
- refund/reversal requirements
- RLS policy expectations for POS-owned tables

### From payments

- payment state names and legal transitions
- idempotency table shape
- callback event table shape
- reconciliation table shape
- required tenant-scoped unique constraints

### From commission

- commission ledger table shape
- payout ledger table shape
- required read-only view from payments
- effective-dated commission rate requirements
- payout period and retry/idempotency invariants

## Apply and bootstrap procedure

After this PR is merged, the dev Terraform apply workflow creates the
`devops-g3-db-bootstrap` project and wires it into the delivery pipeline.
CodePipeline then runs it as the `DbBootstrap` stage before ECS deployment. The
job is idempotent and keeps existing service DB passwords unless
`ROTATE_PASSWORDS=true` is supplied for an intentional rotation.

Rerun: the bootstrap is a **pipeline stage** (`DbBootstrap`, between
`BuildScanPush` and `DeployEcs`), so it cannot be started directly —
`aws codebuild start-build` is rejected on a CODEPIPELINE-source project.
Retry the stage instead:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
EXEC_ID=$(aws codepipeline list-pipeline-executions \
  --pipeline-name devops-g3-pipeline --max-items 1 \
  --query 'pipelineExecutionSummaries[0].pipelineExecutionId' --output text)

AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws codepipeline retry-stage-execution \
  --pipeline-name devops-g3-pipeline \
  --stage-name DbBootstrap \
  --pipeline-execution-id "$EXEC_ID" \
  --retry-mode FAILED_ACTIONS
```

Reruns are safe: existing per-service passwords are reused, so a run with
nothing to do re-asserts schemas, roles and grants and changes no credential.
To deliberately rotate, set `ROTATE_PASSWORDS=true` as a build override — every
task must then restart to pick up the new secret version.

Check the latest bootstrap build:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws codebuild list-builds-for-project \
  --project-name devops-g3-db-bootstrap \
  --sort-order DESCENDING \
  --query 'ids[0]' \
  --output text
```

The expected result is a successful CodeBuild run and an updated
`devops-g3/db` secret containing one JSON key per service.

## Evidence to capture for G2

- Terraform plan/apply showing the DB bootstrap project and security-group rule
- CodeBuild logs showing the DB bootstrap completed
- proof that the schemas exist
- proof that owner roles and runtime roles exist
- proof that runtime roles are `NOBYPASSRLS`
- proof that runtime roles do not own service schemas
- proof that tenant tables created by service migrations use
  `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`

## Notes

- The application DB password value must not be pasted into Slack, GitHub, PR
  comments, screenshots, or evidence files.
- The RDS master secret is for controlled bootstrap/migration use only.
- Application tasks should consume `DB_CREDENTIALS` through ECS secret injection.
