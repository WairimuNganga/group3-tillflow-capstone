# Reliability + operations — evidence

**DRI:** Minage · **Cross-review:** Product · **ADRs:** [ADR-008](../../docs/adr/ADR-008-telemetry-conventions.md), [amendment](../../docs/adr/ADR-008-amendment-sampling-and-probes.md)

Capstone evidence lives in **this file only** (exact reproduction commands; screenshots alone earn no credit).

## Checklist

- [x] Commits / PRs — Phase A + AMP: #40, #41, #42; bootstrap IAM applied locally 2026-09-19
- [x] Tests — `services/_shared/tests/otel/`; `terraform test` in `infra/envs/dev`
- [x] B0 runtime — AMP ACTIVE, ADOT remote-write URL, Slack secret value set
- [x] B1 — AMP query after traffic (record in §B1)
- [x] B3 — edge probe + k6 smoke (2026-09-19); **baseline + soak (2026-09-20)** — [k6-analysis.md](./k6-analysis.md); spike optional
- [x] B2 — Grafana ECS + TillFlow dashboards (2026-09-20); AMP datasource + evidence row §B2
- [x] B2 follow-up — **payments** RED in AMP (2026-09-20); refresh Grafana panels; **web/pos** RED still 0 until counted traffic
- [ ] E — Slack secret + CLI webhook OK; Grafana **Test contact point** + §Phase E row after tillflow2 ECS roll

## Phases A–H (where we are)

Letter phases map to this evidence pack and [how-to-reproduce.md](./how-to-reproduce.md). **G3/G4** in filenames = grading gates for load and resilience, not the same as letter **G**.

| Phase | Scope | Status | Next action |
|-------|--------|--------|-------------|
| **A** | OTel instrumentation (shared lib, ADOT on ECS, local traces) | **Mostly done** — A1–A4 ✓; A5 E2E trace sale→callback open | Product path deploy + X-Ray trace capture for ADR-008 |
| **B** | Observability stack (AMP, Grafana, probes) | **B0–B1, B3 ✓**; **B2 ✓**; **payments RED in AMP ✓** (2026-09-20) | Grafana screenshot with payments RED; pos/web traffic follow-up |
| **C** | External synthetics (CloudWatch canary on `/health`) | **Not started** (TF TODO) | Edge probe is stand-in until canary in Terraform |
| **D** | k6 capacity envelope (**G3**) | **Smoke, baseline, soak ✓** (2026-09-20) | Optional: `spike.js`; cite logs in [k6-analysis.md](./k6-analysis.md) |
| **E** | Alerting (Grafana → `devops-g3/slack-webhook`) | **In progress** — rules in `infra/grafana/provisioning/alerting/` | Apply + pipeline + **Test contact point**; record §Phase E |
| **F** | ADR-008 proof (dashboard JSON + trace captures in evidence) | **JSON in** `evidence/reliability/phase-f/` | Screenshots + X-Ray trace ID table in phase-f README |
| **G** | Ops drills (Drill 3: fail→alert→runbook→recover; platform G1/G2) | **Not recorded** | Execute Drill 3; document in how-to-reproduce §Drill 3 |
| **H** | Resilience / rollback (**G4**, multi-AZ when enabled) | **Drill 4 log exists** in delivery evidence | Tie rollback rehearsal to reliability narrative if required |

**You are here:** end of **Phase B** → start **E** (alerts) and **D** (k6 envelope) in parallel; **C** when Platform adds canary TF.

## Phase status (detail)

| Phase | Status | Where in this doc |
|-------|--------|-------------------|
| A — instrumentation | Local + code done; AWS E2E trace open | §Phase A, §Telemetry walkthrough |
| B0 — align (AMP, ADOT, Slack) | Done in AWS | §Phase B0 |
| B1 — metrics in AMP | Verified 2026-09-19 | §Phase B1 |
| B2 — Grafana + dashboards | Live 2026-09-20; RED panels empty | §Phase B2 |
| B3 — probe + k6 smoke | Done 2026-09-19 | §Phase B3 |

**Concurrency:** Alert rules (Phase **E**) need B1 + B2. k6 baseline/soak (Phase **D**) must not overlap `spike.js` (T1.3).

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
- [x] Custom ADOT config on ECS (`infra/adot/tillflow-collector.yaml` → ECR **tillflow4**)
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
| ADOT → AMP | Sidecar `tillflow-collector.yaml` in `devops-g3/adot:v0.43.3-tillflow4` | SigV4 + `${env:AWS_*}` (#46, #47); ECS container metrics + OTLP pipelines. **Supersedes tillflow1–3.** |
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
| 2026-09-19 | Minage | OK (`reliability-edge-probe.sh`) | **Yes** — `count({__name__=~".+"})` = **208** | ADOT **tillflow4** on all services; `ecs_task_*` in AMP; PR **#46** (SigV4 + pipeline `ADOT_IMAGE_TAG`), **#47** (`${env:...}` + `awsecscontainermetrics`). |
| 2026-09-20 | Minage | OK (edge + `otlp-red-amp-verify.sh`) | **Yes** — `count` = **358**; `sum(payments_requests_total)` = **15** | Non-probe traffic via `/api/payments/stk`; `pos`/`web` RED **0** (no counted routes hit). Use script, not `/demo/boom` (web scaffold). |

**Verification commands (2026-09-19, after apply green → CodePipeline Release change → tillflow4 in ECR):**

```bash
export AWS_REGION=us-west-1
export AMP_WORKSPACE_ID=ws-40261a89-bf51-45ee-a25b-e5fdfa21b69d
export API_ENDPOINT="$(terraform -chdir=infra/envs/dev output -raw api_endpoint)"

aws ecr describe-images --repository-name devops-g3/adot --image-ids imageTag=v0.43.3-tillflow4 \
  --query 'imageDetails[0].imagePushedAt' --output text
# 2026-09-19T23:02:27+03:00

# PRIMARY task defs: web :57, pos/payments :55, commission :56 → adot:v0.43.3-tillflow4

bash infra/scripts/reliability-edge-probe.sh
curl -sS -o /dev/null -w "%{http_code}\n" "${API_ENDPOINT%/}/demo/boom"   # 500 (counted route, not probe)

sleep 90
python3 infra/scripts/amp_promql_query.py "$AMP_WORKSPACE_ID" 'count({__name__=~".+"})'
# result value "208"

python3 infra/scripts/amp_promql_query.py "$AMP_WORKSPACE_ID" '{__name__=~"ecs_task_.*"}'
# e.g. ecs_task_cpu_usage_usermode_Nanoseconds (payments task, devops-g3 cluster)
```

**B1 script note:** `b1-amp-validate.sh` uses `sum({svc}_requests_total) or vector(0)` — **"0" with empty `metric` is not proof of RED series.** Probes are excluded from RED. **2026-09-19:** RED looked empty after `/demo/boom` (route not on prod web). **2026-09-20:** `bash infra/scripts/otlp-red-amp-verify.sh` → `payments_requests_total` present. **B1 ingest gate:** non-empty `count({__name__=~".+"})` and `ecs_task_*` remote write; RED proof needs non-probe API traffic.

**Ops note:** On infra merges, run **terraform apply (dev) before** (or immediately then) **CodePipeline Release change**, so `mirror-adot` builds the new `adot_image_tag` (e.g. tillflow4); otherwise ECR keeps the previous tag while Terraform points at the new one.

**Troubleshooting:** empty `count({__name__=~".+"})` → wrong/missing ADOT image, `${VAR}` vs `${env:VAR}` on ADOT ≥0.41, or apply/pipeline race; empty RED only → probe paths, no counted traffic, or OTLP metric naming; SigV4 403 on **query** → IAM/`amp_promql_query.py` encoding.

---

## Phase B2 — Grafana

Dashboard JSON: `infra/grafana/dashboards/` · datasource example: `infra/grafana/provisioning/datasources/amp.yaml.example` · README: `infra/grafana/README.md`.

**Platform:** Grafana on ECS (private, auth) — **Lwam**. **Reliability (Minage):** AMP datasource + import dashboards; alert rules → Slack secret (see [runbook § Observability alerts](../../docs/runbook.md)).

### B2 checklist (run in parallel with B3 — no k6 in this terminal)

- [x] AMP query URL: `terraform -chdir=infra/envs/dev output amp_prometheus_endpoint`
- [x] Grafana ECS (self-hosted, `…/v1/grafana/`, admin from `devops-g3/grafana-admin`)
- [x] Prometheus datasource **AMP** (uid `AMP`, SigV4, provisioned in image)
- [x] Dashboards **TillFlow** folder — `web-service-overview`, `payments-service-overview` (baked in ECR image)
- [x] Panels load; **payments** RED should populate after 2026-09-20 AMP verify (re-open dashboard)
- [ ] **Explore:** `sum(rate(payments_requests_total[5m]))` or `count({__name__=~".+"})` screenshot for Phase F
- [ ] Phase **E:** Grafana contact point **Test** (CLI webhook to `# group-3-alerts` OK 2026-09-20); rules after tillflow2

### Recorded run

| Date | Grafana URL | Dashboards imported | AMP datasource OK | Notes |
|------|-------------|---------------------|---------------------|-------|
| 2026-09-20 | `https://w6m0ja1aic.execute-api.us-west-1.amazonaws.com/v1/grafana/` | TillFlow / web + payments (provisioned) | Yes | APIGW `/v1/grafana/` (#52+). **Payments RED in AMP** after `otlp-red-amp-verify.sh` — confirm panels + screenshot (Phase F). |

---

## Phase E — Grafana alerts → Slack

**Code:** `infra/grafana/provisioning/alerting/` + Slack URL via ECS secret `SLACK_WEBHOOK_URL` → entrypoint contact point `slack-tillflow`.

**Rules (runbook):** PaymentsHigh5xxRate, PaymentsLatencyP95, EdgeProbeFailed (AMP `count({__name__=~".+"})` proxy until Phase C synthetics).

### Checklist

- [x] `devops-g3/slack-webhook` AWSCURRENT full incoming webhook (posts to `# group-3-alerts`)
- [ ] `grafana_image_tag` **11.4.0-tillflow2** applied + image in ECR + ECS on new task
- [ ] Force new Grafana ECS deployment after secret update
- [ ] Grafana → Alerting → Contact points → **Test** slack-tillflow (CLI webhook test OK 2026-09-20)
- [ ] Alert rules in folder **TillFlow Alerts** (3 rules)
- [ ] Evidence: Slack screenshot or message ID + date below

### Recorded run

| Date | Contact point test | Rules provisioned | Slack message link / note |
|------|-------------------|-------------------|---------------------------|
| 2026-09-20 | CLI incoming-webhook → `# group-3-alerts` | Pending tillflow2 ECS | Grafana UI Test pending; Phase E merged **main @5746ab0** |

---

## Phase B3 — Synthetic probe + k6

Edge probe **passed 2026-09-19** (same session as B1 tillflow4 verification). Full k6 matrix: [how-to-reproduce.md](./how-to-reproduce.md) · analysis: [k6-analysis.md](./k6-analysis.md).

**Run B3 while doing B2** (Terminal A = k6, Terminal B = Grafana UI):

```bash
export AWS_REGION=us-west-1
export API_ENDPOINT="$(terraform -chdir=infra/envs/dev output -raw api_endpoint)"
bash infra/scripts/reliability-edge-probe.sh
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/smoke.js | tee evidence/reliability/k6-smoke.log
```

Longer runs (off-hours; do not overlap with `spike.js`):

```bash
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/baseline.js | tee evidence/reliability/k6-baseline.log
k6 run -e API_ENDPOINT="$API_ENDPOINT" --out json=evidence/reliability/k6-soak.json reliability/k6/soak.js
```

Spike: `reliability/k6/spike.js` — manual, team notified (T1.3).

### Checklist

- [x] Edge probe output (2026-09-19 — OK /health, /ready)
- [x] k6 smoke thresholds pass — 0% failed, p(95)=287.6ms, checks 100%; log `evidence/reliability/k6-smoke.log`
- [ ] baseline + soak (optional G3 envelope; update k6-analysis table)
- [ ] Spike summary when run

### Recorded smoke run (2026-09-19)

| Metric | Value |
|--------|-------|
| Script | `reliability/k6/smoke.js` |
| VUs / duration | 2 / 30s |
| Thresholds | `http_req_failed` ✓ rate&lt;0.05; `http_req_duration` ✓ p(95)&lt;2000ms |
| http_reqs | 78 (~2.48/s) |
| Checks | health 2xx, ready 2xx — all passed |

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
- [x] ADOT tillflow image on ECS (AMP remote write + tail_sampling in baked config)
- [x] Self-hosted Grafana on ECS + AMP datasource (Phase B2)
- [ ] Non-zero `{service}_requests_total` in AMP after counted edge traffic (OTLP follow-up)
- [ ] DB driver spans when driver chosen
- [ ] Private Grafana operator access (G0 feedback)
- [ ] Live alert rules (Phase E); k6 baseline/soak **done** (Phase D)

---

## Next steps (priority order)

1. **Phase E — Deploy alerts (today):** Merge `11.4.0-tillflow2` → terraform apply → pipeline `build-grafana` → Grafana **Test contact point**; fill §Phase E table.
2. **Phase D — k6 envelope:** Run `baseline.js` then `soak.js` off-hours; update [k6-analysis.md](./k6-analysis.md) table.
3. **OTLP RED follow-up (unblocks dashboard panels):** Debug why `{service}_requests_total` absent in AMP after `/demo/boom` while `ecs_task_*` present — ADOT OTLP pipeline or metric export naming.
4. **Phase F:** Save Grafana dashboard JSON exports + one X-Ray trace screenshot/ID under `evidence/reliability/`.
5. **Phase C:** Platform Terraform for CloudWatch Synthetics on `$API_ENDPOINT/health`.
6. **Phase G / H:** Drill 3 write-up; link [evidence/delivery/rollback-log.md](../delivery/rollback-log.md) for G4 if graders ask rollback proof.

---

*End of reliability + operations evidence pack.*
