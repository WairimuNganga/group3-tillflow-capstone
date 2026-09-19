# amp

Amazon Managed Prometheus workspace for TillFlow (ADR-001). ADOT sidecars remote-write
here; Grafana uses the query endpoint as a data source.

Created by Terraform only — no console workspace for capstone evidence.

After `terraform apply` in `envs/dev`:

```bash
terraform output amp_workspace_id
terraform output amp_remote_write_url
```

ECS task definitions pick up the remote-write URL on the next apply that touches
services (or force a new deployment after apply).
