output "canary_name" {
  value = aws_synthetics_canary.edge_health.name
}

output "canary_arn" {
  value = aws_synthetics_canary.edge_health.arn
}

output "health_url" {
  value = local.health_url
}

output "ready_url" {
  value = local.ready_url
}
