# ADR-008: Telemetry conventions

- **Status:** Accepted
- **DRI:** Minage
- **Date:** 2026-09-08

## Context
Every task already runs an app container plus an ADOT collector sidecar (`docs/architecture.md`),
feeding Amazon Managed Prometheus, CloudWatch, and X-Ray. Without a shared naming and boundary
convention across five services, dashboards and traces won't line up, and the
[SLOs](ADR-006-slos-and-error-budgets.md) they're built from won't be comparable service to service.

## Decision
- **Instrumentation**: OpenTelemetry SDK in every service, exporting OTLP to the local ADOT sidecar
  (`localhost:4317`), which forwards metrics to AMP (remote-write) and CloudWatch, and traces to
  X-Ray. No service talks to AMP/X-Ray directly.
- **Span boundaries**: one root span per inbound request; a child span per outbound call (DB query,
  Daraja call, inter-service call). Span names: `<service>.<verb_noun>`, e.g. `payments.stk_push`,
  `pos.create_sale`.
- **Span attributes**: every span carries `service.name` and `tenant_id`. Money-path spans
  additionally carry `idempotency_key`. Phone numbers and other PII are **never** attached to a span
  attribute or log field in raw form — hashed or redacted by the shared instrumentation wrapper
  before anything leaves the process, per `docs/threat-model.md`.
- **Metrics** (RED per service, plus business counters):
  `<service>_requests_total{route,method,status}`,
  `<service>_request_duration_seconds{route,method}` (histogram),
  `payments_stk_initiated_total`, `payments_callback_processed_total{result}`,
  `commission_reconciliation_variance_total`.
- **Logs**: structured JSON, one line per event, required fields `ts, level, service, trace_id,
  span_id, tenant_id, msg` — `trace_id`/`span_id` are what let a CloudWatch Logs Insights query and
  an X-Ray trace be correlated.
- **Sampling**: 100% head-based sampling for money-path spans (`payments`, `commission` — low
  volume, high value, and the ones [ADR-004](ADR-004-idempotency-and-money-integrity.md) needs a
  full trace for). Read-heavy `pos`/`web` routes sample probabilistically at 10%. Any span carrying
  an error is always sampled, regardless of route.
- **Grafana hierarchy** (self-hosted on ECS, [ADR-001](ADR-001-aws-region.md)): folders
  `Platform / <service>`, one "Service overview" dashboard per service (RED metrics + SLO burn from
  [ADR-006](ADR-006-slos-and-error-budgets.md)), one cross-cutting "Money path" dashboard
  (`payments` + `commission`), one "Region & cost" dashboard. Dashboards are provisioned as JSON
  checked into the repo, not built by hand in the UI, so they're reproducible evidence.

## Alternatives considered
- **Vendor-specific SDKs per service** — rejected: locks each service to a specific backend and
  produces five different instrumentation styles; OTel keeps the AMP/CloudWatch/X-Ray choice
  swappable and centralizes the instrumentation code in `services/_shared`.
- **100% sampling everywhere** — rejected: not justified by volume/cost on `pos`/`web` read routes;
  reserved for the money-path spans where completeness actually matters.
- **Unstructured/plain-text logs** — rejected: can't be reliably correlated to a `trace_id` or
  queried in CloudWatch Logs Insights the way structured JSON can.

## Consequences
- Every service adopts the shared OTel bootstrap helper in `services/_shared` — this is a hard
  dependency at service startup, not an opt-in library.
- PII redaction is enforced centrally in that shared wrapper; a service can't "forget" to redact a
  phone number because it never sees the raw value reach the tracing/logging call.
- 10% sampling on `pos`/`web` means routine incident investigation on those services sometimes lacks
  a trace for the specific request in question — the always-sample-on-error rule is what keeps
  actual failures traceable despite the lower base rate.
- Dashboard-as-code means a dashboard change is a PR, reviewable and diffable, not a silent UI edit.

## Required proof (from brief)
Dashboard export + traces: Grafana dashboard JSON exports and example trace captures, filed under
`evidence/reliability/`.
