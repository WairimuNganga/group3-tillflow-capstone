output "workspace_id" {
  description = "AMP workspace ID (ws-...)."
  value       = aws_prometheus_workspace.this.id
}

output "workspace_arn" {
  description = "AMP workspace ARN for IAM scoping."
  value       = aws_prometheus_workspace.this.arn
}

output "prometheus_endpoint" {
  description = "Query endpoint base URL for Grafana/Explore."
  value       = local.prometheus_endpoint
}

output "remote_write_url" {
  description = "Remote-write URL for the ADOT sidecar (AWS_PROMETHEUS_ENDPOINT)."
  value       = local.remote_write_url
}
