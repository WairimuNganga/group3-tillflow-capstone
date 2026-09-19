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
  description = "payments (Daraja) and grafana (AMP query API). Threat model T2.4 / AR-7."
  value       = ["payments", "grafana"]
}

output "grafana_url" {
  description = "Public Grafana UI (admin auth; anonymous disabled)."
  value       = "${trimsuffix(module.apigw.api_endpoint, "/")}/grafana/"
}

output "grafana_admin_secret_arn" {
  description = "Populate with a plain-string password before the first Grafana login."
  value       = module.secrets.secret_arns["grafana-admin"]
}

output "db_proxy_endpoint" {
  value = module.rds.proxy_endpoint
}

output "db_name" {
  value = module.rds.database_name
}

output "db_secret_arn" {
  description = "Application DB credentials secret. Values are populated by the G2 DB bootstrap job."
  value       = module.secrets.secret_arns["db"]
}

output "db_bootstrap_project_name" {
  description = "Run this CodeBuild project after apply to create G2 schemas, DB roles and service credentials."
  value       = module.db_bootstrap.project_name
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

output "delivery_pipeline_name" {
  value = module.delivery.pipeline_name
}

output "delivery_github_connection_arn" {
  description = "Authorize this CodeConnections connection once before the first pipeline run."
  value       = module.delivery.github_connection_arn
}

output "delivery_codebuild_project_names" {
  value = module.delivery.codebuild_project_names
}

output "availability_zones" {
  description = "Pinned, not discovered. Verify against the account before first apply."
  value       = module.network.availability_zones
}

output "amp_workspace_id" {
  description = "Amazon Managed Prometheus workspace for Grafana and ADOT remote write."
  value       = module.amp.workspace_id
}

output "amp_prometheus_endpoint" {
  description = "AMP query endpoint base URL (Grafana data source)."
  value       = module.amp.prometheus_endpoint
}

output "amp_remote_write_url" {
  description = "Injected on ADOT sidecars as AWS_PROMETHEUS_ENDPOINT after apply + ECS rollout."
  value       = module.amp.remote_write_url
  sensitive   = false
}
