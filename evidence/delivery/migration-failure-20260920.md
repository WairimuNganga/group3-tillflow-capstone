# Payments and Commission migration failure — 2026-09-20

## AWS execution

- Pipeline: `devops-g3-pipeline`
- Execution: `b422cdac-03a8-4f32-849a-4e16ee083e82`
- Started: `2026-09-20T23:32:39+03:00`
- Finished: `2026-09-20T23:38:58+03:00`
- Result: `Failed` in `MigrateDb`

| Action | Result | External execution |
|---|---|---|
| `pos-alembic` | Succeeded | `devops-g3-pos-migrations:efbb1d08-f66c-473d-8e78-eaa029a67931` |
| `payments-alembic` | Failed | `devops-g3-payments-migrations:7b7c05b8-0321-4cdd-ba37-086a208efe13` |
| `commission-alembic` | Failed | `devops-g3-commission-migrations:47ead5aa-0a93-4a18-81aa-fb38c55e7037` |

Both failed CodeBuild executions reached their `BUILD` phase and ran the service image. The failing command was `/opt/venv/bin/python -m alembic upgrade head`; CodeBuild reported `COMMAND_EXECUTION_ERROR` with exit status 1.

## Exact CloudWatch errors

Payments (`/devops-g3/codebuild/payments-migrations`, stream `migrate/7b7c05b8-0321-4cdd-ba37-086a208efe13`):

```text
psycopg.errors.InsufficientPrivilege: permission denied for database tillflow
op.execute("CREATE SCHEMA IF NOT EXISTS payments")
sqlalchemy.exc.ProgrammingError: (psycopg.errors.InsufficientPrivilege)
[SQL: CREATE SCHEMA IF NOT EXISTS payments]
```

Commission (`/devops-g3/codebuild/commission-migrations`, stream `migrate/47ead5aa-0a93-4a18-81aa-fb38c55e7037`):

```text
psycopg.errors.InsufficientPrivilege: permission denied for database tillflow
op.execute("CREATE SCHEMA IF NOT EXISTS commission")
sqlalchemy.exc.ProgrammingError: (psycopg.errors.InsufficientPrivilege)
[SQL: CREATE SCHEMA IF NOT EXISTS commission]
```

## Root cause

The database connection and RDS Proxy authentication succeeded. Alembic then correctly executed `SET ROLE tillflow_<service>_owner`. These least-privilege owner roles own their existing schemas but deliberately do not have database-level `CREATE` permission.

The first Payments and Commission revisions still execute `CREATE SCHEMA IF NOT EXISTS`. PostgreSQL checks database `CREATE` permission before evaluating whether the schema already exists, so these statements fail even though db-bootstrap already created and assigned both schemas.

POS succeeded because its Alembic revisions rely on db-bootstrap for schema creation and do not execute `CREATE SCHEMA`.

## Remediation

Treat schema creation and ownership as a db-bootstrap responsibility. Make the `upgrade()` and `downgrade()` functions in the Payments and Commission `0001_create_*_schema.py` revisions no-ops, with comments documenting that ownership is established by db-bootstrap. Retain `SET ROLE` for all table, index, view, and Alembic-version objects.

After deploying the correction, rerun the pipeline and retain successful migration logs as recovery evidence.

## Reproduction commands

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws codepipeline get-pipeline-state \
  --name devops-g3-pipeline

AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws logs get-log-events \
  --log-group-name /devops-g3/codebuild/payments-migrations \
  --log-stream-name migrate/7b7c05b8-0321-4cdd-ba37-086a208efe13 \
  --start-from-head

AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws logs get-log-events \
  --log-group-name /devops-g3/codebuild/commission-migrations \
  --log-stream-name migrate/47ead5aa-0a93-4a18-81aa-fb38c55e7037 \
  --start-from-head
```
