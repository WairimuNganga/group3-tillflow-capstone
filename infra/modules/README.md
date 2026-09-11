# modules

| Module | What it owns |
|---|---|
| `network` | VPC, three subnet tiers across two AZs, NAT, VPC endpoints, flow logs |
| `s3` | The five project buckets (artifacts, logs, alb-logs, backups, evidence) |
| `secrets` | Secrets Manager containers — ARNs only, never values |
| `ecs-platform` | Cluster, ECR repos, log groups, execution role, Service Connect namespace |
| `ecs-service` | One service = app container + ADOT sidecar, task role, SG |
| `alb` | Internal ALB, target groups, path-based listener rules |
| `apigw` | HTTP API + VPC Link — the only public entry point |
| `rds` | PostgreSQL, RDS Proxy, parameter group with the containment timeouts |
| `redis` | ElastiCache Valkey for cache-aside |
| `messaging` | SQS + DLQ pairs and the EventBridge daily-close schedule |

Each module is consumed only by `envs/dev`. Adding a new service means adding
it to `local.services` in the root module — the SG, task role, log group, ECR
repo and ADOT sidecar all follow from that.
