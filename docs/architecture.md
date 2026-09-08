# Architecture — TillFlow (devops-g3)

## Request path
WEB → API Gateway → VPC Link → internal ALB → ECS Fargate services (private subnets, 2 AZs)

## Services
- **web** — frontend / API shell
- **pos** — POS API (sale creation, idempotency, sale state)
- **payments** — Daraja owner (auth, STK, callbacks, query, B2C, reconciliation)
- **commission** — daily close worker (calc from paid sales → ledger → B2C via Payments API)
- **_shared** — M-Pesa adapter interface + fake, OTel setup, Docker base

## State & edges
RDS PostgreSQL (per-service schemas/roles) · ElastiCache Redis/Valkey (cache-aside) ·
SQS + DLQ · EventBridge (daily schedule) · S3 (state/artifacts/logs/backups/evidence) · Daraja sandbox

## Observability
Each task = app + ADOT sidecar → OTLP to localhost sidecar → Amazon Managed Prometheus + CloudWatch;
X-Ray traces; **self-hosted Grafana on ECS** (Amazon Managed Grafana is unavailable in us-west-1).

## Diagram
> TODO: embed architecture diagram here (draw.io / excalidraw export in evidence/).
