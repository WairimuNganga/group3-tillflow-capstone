# Execution tracker — Lwam (Platform) + Minage (Reliability)

**You are implementing both lanes.** Work top-to-bottom; do not skip evidence capture on the same day as the code merge.

**Legend:** `[ ]` todo · `[~]` in progress · `[x]` done

**Detailed specs:** [lwam-minage-implementation-plan.md](./lwam-minage-implementation-plan.md)

---

## Phase A — Platform infra (Lwam) — unblock G3 probe

| Step | Task | Owner | Status | Evidence / PR |
|------|------|-------|--------|----------------|
| **A1** | `synthetics-canary` Terraform module + wire in `envs/dev` | Lwam | [x] | PR: platform synthetics |
| **A2** | `observability-alarms` module (DLQ depth + canary SuccessPercent) | Lwam | [x] | same PR |
| **A3** | `terraform test` + plan locally; apply in dev | Lwam | [ ] | `evidence/platform/terraform-plan-*.json` |
| **A4** | Capture naming/tag audit log after plan | Lwam | [ ] | `evidence/platform/naming-tag-audit-*.log` |
| **A5** | `aws synthetics describe-canaries` + one run log | Lwam | [ ] | `evidence/platform/synthetics-*.log` |

---

## Phase B — Platform evidence pack (Lwam)

| Step | Task | Status | Evidence |
|------|------|--------|----------|
| **B1** | `evidence/platform/how-to-reproduce.md` | [x] | this file |
| **B2** | DB bootstrap build log (rerun if needed) | [ ] | `db-bootstrap-build-*.log` |
| **B3** | Schema/roles/RLS proof (no passwords) | [ ] | `db-roles-rls-*.log` |
| **B4** | `evidence/platform/README.md` checkboxes + PR links | [ ] | README |

---

## Phase C — Reliability: alerts & Grafana (Minage)

| Step | Task | Status | Evidence |
|------|------|--------|----------|
| **C1** | Slack contact point: all 9 contract fields | [ ] | `infra/grafana/docker-entrypoint.sh` |
| **C2** | Alert rule annotations (env, service, symptom, …) | [ ] | `rules.yaml` |
| **C3** | Pipeline: bump Grafana image tag + deploy | [ ] | ECS + screenshot |
| **C4** | Test contact point + capture firing/recovery | [ ] | `slack-alert-*.json` |
| **C5** | Retarget EdgeProbeFailed to Synthetics metric (after A3) | [ ] | rules.yaml + runbook |

---

## Phase D — Reliability: dashboards & k6 (Minage)

| Step | Task | Status | Evidence |
|------|------|--------|----------|
| **D1** | SLO/uptime/burn dashboard JSON | [ ] | `infra/grafana/dashboards/tillflow-slo-overview.json` |
| **D2** | Business metrics on payments dashboard | [ ] | dashboard JSON |
| **D3** | Export to `evidence/reliability/phase-f/dashboards/` | [ ] | phase-f README |
| **D4** | Run `k6 spike.js` | [ ] | `k6-spike.log` |
| **D5** | Finish `k6-analysis.md` (RPS, bottleneck, cost) | [ ] | analysis md |
| **D6** | Commit `k6-soak.json` | [ ] | git |

---

## Phase E — Drills & runbook (joint)

| Step | Task | Owner | Status | Evidence |
|------|------|-------|--------|----------|
| **E1** | **Drill 3** — break worker/DLQ → alert → recover (timed) | Minage | [ ] | `drill-3-platform-failure-*.md` |
| **E2** | **Drill 5** — RDS restore → RPO/RTO | Lwam exec | [ ] | `restore-drill-*.md` |
| **E3** | Runbook: RTO/RPO, restore, reconciliation order, drill index | Minage | [ ] | `docs/runbook.md` |
| **E4** | Expand `slo-error-budgets.md` per-SLI rows | Minage | [ ] | docs |
| **E5** | Phase F X-Ray trace (sale→payment→callback) | Minage | [ ] | phase-f/traces/ |

---

## Phase F — G5 release (Lwam + Minage)

| Step | Task | Status |
|------|------|--------|
| **F1** | Root README: bootstrap/deploy/destroy + API URL + demo | [ ] |
| **F2** | `destroy-rebuild` log | [ ] |
| **F3** | `production-readiness.md` stub filled (reliability + platform) | [ ] |
| **F4** | Final evidence checklist in both READMEs | [ ] |

---

## Current focus (start here)

1. **A3 apply** (you) — merge PR, then `./infra/scripts/deploy.sh --apply`.
2. **Immediately after apply:** Minage runs **C5** + **C4** (alerts tied to real canary).
3. **Same day:** Lwam **A4–A5** + **B1** evidence commands.

```bash
# After merge — Lwam apply path
export AWS_REGION=us-west-1
cd ~/capstone/group3-tillflow-capstone
./infra/scripts/deploy.sh --apply

# Evidence
terraform -chdir=infra/envs/dev show -no-color tfplan | tee evidence/platform/terraform-plan-$(date -u +%Y%m%d).txt
../../infra/scripts/audit-naming-tags.sh infra/envs/dev/plan.json | tee evidence/platform/naming-tag-audit-$(date -u +%Y%m%d).log
```

---

## Out of scope for this tracker (other DRIs)

- Commission + Web application code (Joyce)
- Money drills 1–2 (Hunter)
- Broken-release smoke fail (Wairimu)

Coordinate before **E5** and sale-path k6.
