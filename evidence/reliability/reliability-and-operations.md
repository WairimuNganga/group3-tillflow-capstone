# Reliability + operations — evidence

**DRI:** Minage · **Cross-review:** Product · **ADRs:** [ADR-008](../../docs/adr/ADR-008-telemetry-conventions.md), [amendment](../../docs/adr/ADR-008-amendment-sampling-and-probes.md)

Capstone evidence lives in **this file only** (exact reproduction commands; screenshots alone earn no credit).

## Checklist

- [x] Commits / PRs — Phase A + AMP: #40, #41, #42; bootstrap IAM applied locally 2026-09-19
- [x] Tests — `services/_shared/tests/otel/`; `terraform test` in `infra/envs/dev`
- [x] B0 runtime — AMP ACTIVE, ADOT remote-write URL, Slack secret value set
- [ ] B1 — AMP query after traffic (record in §B1)
- [ ] B3 — edge probe + k6 summaries (record in §B3; scripts: smoke/baseline/soak/spike — [how-to-reproduce.md](./how-to-reproduce.md))
- [ ] B2 — Grafana ECS (Platform) + dashboard import from `infra/grafana/dashboards/`

## Phase status

| Phase | Status | Where in this doc |
|-------|--------|-------------------|
| A — instrumentation | Local + code done | §Phase A, §Telemetry walkthrough |
| B0 — align (AMP, ADOT, Slack) | Done in AWS | §Phase B0 |
| B1 — metrics in AMP | Scripts ready | §Phase B1 |
| B2 — Grafana + dashboards | JSON in repo; ECS = Lwam | §Phase B2 |
| B3 — probe + k6 | Scaffold in repo | §Phase B3 |

**Concurrency:** B1 (Minage, after traffic), B2b dashboard JSON (Minage now), B2a Grafana ECS (Lwam), B3 probe/k6 (Minage). Alert rules need B1 + B2 wired to `devops-g3/slack-webhook`.

**Account / region:** `240462142849`, `us-west-1` · SSO: `aws login` / profile `group3`.

---

## Phase A — instrumentation verification

**Gate:** foundation for dashboards, k6, and traces.

### A1 — Unit tests (SDK + middleware)

```bash
cd services/_shared
rm -rf .venv
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install -U pip setuptools wheel
pip install -r requirements.lock.txt
pip install -e . --no-deps
pip install 'pytest>=9.0.3' 'pytest-asyncio>=0.24,<2.0'
export TILLFLOW_TELEMETRY_EXPORT=none
pytest tests/otel/ -q
```

**Expected:** all pass (including `/health` and `/ready` excluded from RED metrics).

### A2 — POS and Payments wire the shared library

```bash
grep -l setup_telemetry services/pos/pos/main.py services/payments/payments/main.py
grep -l instrument_fastapi services/pos/pos/main.py services/payments/payments/main.py
```

### A3 — Local trace + JSON logs (Docker)

```bash
cd services/_shared/local
export TILLFLOW_PII_HASH_SALT=local-dev-salt
docker compose up -d
cd ../examples
pip install -q -e ..
export TILLFLOW_TELEMETRY_EXPORT=otlp OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 SERVICE_NAME=payments
python -m uvicorn demo_service:app --host 127.0.0.1 --port 9099 &
sleep 2
curl -sS -X POST http://127.0.0.1:9099/demo/stk -H 'Content-Type: application/json' \
  -d '{"amount_minor": 12500, "msisdn": "+254712345678"}'
```

Jaeger: http://localhost:16686 — service `payments`, span `payments.stk_push`. Log line must have `trace_id`; MSISDN not in clear text.

### A4 — ECS telemetry env (AWS)

```bash
export AWS_REGION=us-west-1
aws ecs describe-task-definition --task-definition devops-g3-payments \
  --query 'taskDefinition.containerDefinitions[?name==`payments`].environment' --output json
aws ecs describe-task-definition --task-definition devops-g3-payments \
  --query 'taskDefinition.containerDefinitions[?name==`adot`].environment' --output json
aws logs tail /devops-g3/payments --since 10m --filter-pattern adot
```

**Expected (app):** `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`, `TILLFLOW_ENVIRONMENT`, `GIT_COMMIT_SHA` when infra applied. **Expected (adot):** non-empty `AWS_PROMETHEUS_ENDPOINT`.

### A5 — Phase A exit criteria

- [x] POS + Payments: `setup_telemetry` + `instrument_fastapi`
- [x] Probe routes excluded from RED (tests)
- [x] ADR-008 amendment; local collector `tail_sampling`
- [ ] Custom ADOT config on ECS (`infra/adot/collector-config.reference.yaml`) — Platform
- [ ] End-to-end AWS trace sale → payment → callback — after product deploy

---

## Phase B0 — AMP, ADOT, Slack

**Status:** Complete 2026-09-19.

### Workflow (Terraform-first)

- **Dev stack** (`infra/envs/dev`): `module.amp` creates workspace; ECS ADOT gets remote-write URL.
- **Bootstrap** (`infra/bootstrap`): `ManagedPrometheus` on `devops-g3-ci-deploy` (`aps:` create/tag/logging). Apply with **local** `terraform.tfstate` (not S3). Coordinate state file with Lwam.
- **Merge →** GitHub **terraform apply (dev)** on `main` (not PR plan-only runs).
- **Slack:** `aws secretsmanager put-secret-value --secret-id devops-g3/slack-webhook` — never commit URL.

### Recorded verification

| Check | Command | Result (2026-09-19) |
|-------|---------|---------------------|
| AMP workspace | `aws amp list-workspaces --region us-west-1 --output table` | **`devops-g3`**, ACTIVE, `ws-40261a89-bf51-45ee-a25b-e5fdfa21b69d` |
| ADOT env | `aws ecs describe-task-definition --task-definition devops-g3-payments --query '...adot...environment'` | `AWS_PROMETHEUS_ENDPOINT` → workspace `/api/v1/remote_write` |
| ADOT → AMP | Sidecar `--config=/etc/ecs/tillflow-collector.yaml` in image `devops-g3/adot:v0.43.3-tillflow1` | Replaces stock `ecs-default-config` (EMF-only metrics). **Apply PR + mirror build + ECS rollout.** |
| Slack | `aws secretsmanager get-secret-value --secret-id devops-g3/slack-webhook --query 'length(SecretString)'` | AWSCURRENT, length > 0 |
| PR trail | — | #40 AMP; #41/#42 bootstrap IAM; terraform **#67** on `main` after bootstrap apply |

```bash
cd infra/envs/dev && terraform output amp_workspace_id amp_remote_write_url
aws ecs update-service --cluster devops-g3 --service devops-g3-payments --force-new-deployment  # if stale revision
```

---

## Phase B1 — AMP + ADOT validation

```bash
pip install boto3   # AMP query; after `aws login`, script exports CLI creds (or: pip install "botocore[crt]")
export AWS_REGION=us-west-1
export AMP_WORKSPACE_ID=ws-40261a89-bf51-45ee-a25b-e5fdfa21b69d
export API_ENDPOINT="$(terraform -chdir=infra/envs/dev output -raw api_endpoint)"
bash infra/scripts/b1-amp-validate.sh
```

Manual PromQL (ADR-008 names):

```bash
python3 infra/scripts/amp_promql_query.py "$AMP_WORKSPACE_ID" 'sum(rate(payments_requests_total[5m]))'
```

Use **non-probe** routes for SLI-style traffic; `/health` and `/ready` are excluded from RED counters.

### Recorded run

| Date | Operator | Edge probe | AMP series visible | Notes |
|------|----------|------------|-------------------|-------|
| | | | | |

**Troubleshooting:** empty `count({__name__=~".+"})` → ADOT still on stock config (no AMP remote write); empty RED only → probe/k6 paths or wait export interval; SigV4 403 with signature message → fixed in `amp_promql_query.py` (`%20` query encoding); edge 404 → routing vs smoke contract.

**After ADOT AMP fix (merge + apply):**

```bash
# ADOT mirror is CodePipeline-only (not `codebuild start-build`):
aws codepipeline start-pipeline-execution --name devops-g3-pipeline
# Or Console: CodePipeline → devops-g3-pipeline → Release change (runs mirror-adot first).
cd infra/envs/dev && terraform apply   # task def: tillflow-collector + new adot tag
for s in web pos payments commission; do
  aws ecs update-service --cluster devops-g3 --service "devops-g3-${s}" --force-new-deployment
done
sleep 45
python3 infra/scripts/amp_promql_query.py "$AMP_WORKSPACE_ID" 'count({__name__=~".+"})'
```

---

## Phase B2 — Grafana

Dashboard JSON: `infra/grafana/dashboards/` · datasource example: `infra/grafana/provisioning/datasources/amp.yaml.example` · README: `infra/grafana/README.md`.

**Platform:** Grafana on ECS (private, auth). **Reliability:** import JSON; alert rules → Slack secret (see [runbook § Observability alerts](../../docs/runbook.md)).

---

## Phase B3 — Synthetic probe + k6

```bash
export API_ENDPOINT="$(terraform -chdir=infra/envs/dev output -raw api_endpoint)"
bash infra/scripts/reliability-edge-probe.sh
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/smoke.js
# baseline / soak: see evidence/reliability/how-to-reproduce.md
```

Spike: `reliability/k6/spike.js` — manual, team notified (T1.3).

### Checklist

- [ ] Edge probe output (commands + OK lines, no secrets)
- [ ] k6 smoke thresholds pass
- [ ] Spike summary pasted below when run

---

## Telemetry library walkthrough

**Covers:** `services/_shared/tillflow_shared/otel/` (implementation plan §4).

### What this is

Five services report the same way so dashboards and SLOs reuse one query model. Services call `setup_telemetry` + `instrument_fastapi`; JSON logs, trace IDs, tenant ID, RED metrics, and MSISDN redaction are centralized (ADR-008).

### Mental model

```
app → OTLP localhost:4317 → ADOT sidecar → AMP (metrics) + X-Ray (traces)
```

Apps never talk to AMP/X-Ray directly.

### Vocabulary

| Term | Meaning |
|------|---------|
| OTel | Open standard for traces/metrics/logs |
| RED | Rate, errors, duration — per-service SLIs |
| ADOT | AWS OTel collector (ECS sidecar) |
| AMP | Amazon Managed Prometheus |

### Key modules (summary)

- **context.py** — tenant + idempotency in context vars (RLS + logs).
- **pii.py** — MSISDN hashing/redaction; fail closed without salt.
- **logging.py** — JSON formatter with trace/tenant; redact before emit.
- **sampling.py** — 100% payments/commission, 10% pos/web; money paths ignore parent sampling.
- **metrics.py** — `{service}_requests_total`, `{service}_request_duration_seconds`.
- **bootstrap.py** — `setup_telemetry()`, export toggle via `TILLFLOW_TELEMETRY_EXPORT=none`.
- **middleware.py** — RED + tracing; `/health` and `/ready` excluded from SLI denominators.
- **http_client.py** — trace + tenant propagation to downstream services.

Local stack: `services/_shared/local/docker-compose.yml` (Jaeger, Prometheus, Grafana for dev).

### Tests

```bash
cd services/_shared && pytest tests/otel/ -q
```

### Team contract (frozen)

```python
from tillflow_shared import setup_telemetry, get_logger
from tillflow_shared.otel.middleware import instrument_fastapi, traced

setup_telemetry("pos")
instrument_fastapi(app, service_name="pos")
```

### Environment variables

| Variable | Purpose |
|----------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Collector (default localhost:4317) |
| `GIT_COMMIT_SHA` | `service.version` |
| `TILLFLOW_PII_HASH_SALT` | MSISDN hashing |
| `TILLFLOW_ENVIRONMENT` | Resource attribute |
| `TILLFLOW_TELEMETRY_EXPORT` | `none` in CI/tests |

### Still open (telemetry area)

- [x] ADR-008 amendment; B0 AMP + ADOT endpoint
- [ ] Mount `infra/adot/collector-config.reference.yaml` on ECS (tail_sampling)
- [ ] DB driver spans when driver chosen
- [ ] Private Grafana operator access (G0 feedback)
- [ ] Live alert rules + k6 envelope evidence

---

*End of reliability + operations evidence pack.*
