output "api_endpoint" {
  description = "Public base URL — the only public entry point."
  value       = module.apigw.api_endpoint
}

output "alb_internal" {
  description = "Must be true. Asserted in tests (ADR-010, threat model T2.1)."
  value       = module.alb.is_internal
}

output "alb_dns_name" {
  description = "Internal only — not resolvable from the internet."
  value       = module.alb.alb_dns_name
}

output "ecs_cluster_name" {
  value = module.ecs_platform.cluster_name
}

output "ecr_repository_urls" {
  value = module.ecs_platform.ecr_repository_urls
}

output "service_task_role_arns" {
  description = "Least-privilege proof: only payments' role can read devops-g3/daraja."
  value       = { for s in local.services : s => module.service[s].task_role_arn }
}

output "service_containers" {
  description = "Two containers per task — app + adot (brief requirement)."
  value       = { for s in local.services : s => module.service[s].container_names }
}

output "services_with_internet_egress" {
  description = "Should be exactly [payments] (threat model T2.4 / AR-7)."
  value       = ["payments"]
}

output "db_proxy_endpoint" {
  value = module.rds.proxy_endpoint
}

output "redis_endpoint" {
  value = module.redis.primary_endpoint
}

output "queue_urls" {
  value = module.messaging.queue_urls
}

output "dlq_names" {
  description = "Alarm on depth — stuck work must be visible, not silently dropped."
  value       = module.messaging.dlq_names
}

output "bucket_ids" {
  value = module.storage.bucket_ids
}

output "availability_zones" {
  description = "Pinned, not discovered. Verify against the account before first apply."
  value       = module.network.availability_zones
}
