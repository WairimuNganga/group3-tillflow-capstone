# ElastiCache Valkey, cache-aside (ADR-002).
#
# Threat model M3: this cache must never be the source of truth for a money
# decision. Commission eligibility and settlement checks read PostgreSQL only.
# Nothing in Terraform can enforce that — it is a code-review rule — but the
# cache is deliberately kept small and short-TTL so it cannot quietly become a
# durable store someone starts trusting.

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name_prefix}-cache"
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-cache"
  description = "Valkey — reachable only from named service security groups"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-cache" }
}

resource "aws_vpc_security_group_ingress_rule" "from_services" {
  for_each = var.client_security_group_ids

  security_group_id            = aws_security_group.this.id
  description                  = "Valkey from ${each.key}"
  referenced_security_group_id = each.value
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${var.name_prefix}-cache"
  description          = "TillFlow cache-aside (ADR-002)"

  engine         = "valkey"
  engine_version = var.engine_version
  node_type      = var.node_type
  port           = 6379

  num_cache_clusters         = var.num_cache_clusters
  automatic_failover_enabled = var.num_cache_clusters > 1
  multi_az_enabled           = var.num_cache_clusters > 1

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.this.id]

  at_rest_encryption_enabled = true
  kms_key_id                 = var.kms_key_arn
  transit_encryption_enabled = true

  # A cache holding tenant-scoped data is not something to leave open on the
  # network alone (T4.5).
  auth_token_update_strategy = "ROTATE"

  maintenance_window       = var.maintenance_window
  snapshot_retention_limit = var.snapshot_retention_limit

  apply_immediately = var.apply_immediately

  tags = { Name = "${var.name_prefix}-cache" }
}
