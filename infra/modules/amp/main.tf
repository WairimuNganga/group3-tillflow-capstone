# Amazon Managed Prometheus (ADR-001: AMP is available in us-west-1).
# Metrics flow: app OTLP -> ADOT sidecar -> AMP remote write -> Grafana.

resource "aws_prometheus_workspace" "this" {
  alias = coalesce(var.alias, var.name_prefix)

  tags = merge(var.tags, {
    Name    = "${var.name_prefix}-amp"
    service = "telemetry"
  })
}

locals {
  # ADOT on ECS reads AWS_PROMETHEUS_ENDPOINT (see modules/ecs-service).
  prometheus_endpoint = trimsuffix(aws_prometheus_workspace.this.prometheus_endpoint, "/")
  remote_write_url    = "${local.prometheus_endpoint}/api/v1/remote_write"
}
