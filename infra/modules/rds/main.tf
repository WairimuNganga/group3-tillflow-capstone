# RDS PostgreSQL + RDS Proxy per ADR-002.
#
# Lives in the data-tier subnets, which have no route to NAT or IGW at all
# (ADR-010, threat model T2.2). Nothing about Postgres needs outbound internet.

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db"
  subnet_ids = var.subnet_ids

  tags = { Name = "${var.name_prefix}-db" }
}

resource "aws_security_group" "db" {
  name        = "${var.name_prefix}-db"
  description = "PostgreSQL — reachable only from the RDS Proxy"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-db" }
}

resource "aws_security_group" "proxy" {
  name        = "${var.name_prefix}-db-proxy"
  description = "RDS Proxy — reachable only from named service security groups"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-db-proxy" }
}

# Services reach the proxy, never the instance directly. Listing each service
# SG explicitly rather than allowing the whole app tier (ADR-010: a blanket
# app-tier rule defeats per-service isolation).
resource "aws_vpc_security_group_ingress_rule" "proxy_from_services" {
  for_each = var.client_security_group_ids

  security_group_id            = aws_security_group.proxy.id
  description                  = "PostgreSQL from ${each.key}"
  referenced_security_group_id = each.value
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "proxy_to_db" {
  security_group_id            = aws_security_group.proxy.id
  description                  = "Proxy to PostgreSQL"
  referenced_security_group_id = aws_security_group.db.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "db_from_proxy" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from RDS Proxy only"
  referenced_security_group_id = aws_security_group.proxy.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# ---------------------------------------------------------------------------
# Parameter group
#
# The timeouts here are load-bearing, not tuning. Threat model T4.6: RDS Proxy
# does NOT give per-service connection quotas (MaxConnectionsPercent sizes the
# proxy's own pool), so a runaway query is contained by being killed, not by
# being throttled.
# ---------------------------------------------------------------------------

resource "aws_db_parameter_group" "this" {
  name        = "${var.name_prefix}-pg${split(".", var.engine_version)[0]}"
  family      = "postgres${split(".", var.engine_version)[0]}"
  description = "TillFlow PostgreSQL parameters (ADR-002)"

  parameter {
    name  = "statement_timeout"
    value = var.statement_timeout_ms
  }

  parameter {
    name  = "idle_in_transaction_session_timeout"
    value = var.idle_in_transaction_timeout_ms
  }

  # Every connection logged — needed to attribute a connection storm to a
  # service during an incident.
  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-db"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = var.kms_key_arn

  db_name  = var.database_name
  username = var.master_username
  # Managed by Secrets Manager rather than a Terraform variable, so the master
  # password never lands in state or a plan output (threat model T6.3).
  manage_master_user_password   = true
  master_user_secret_kms_key_id = var.kms_key_arn

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false

  multi_az = var.multi_az

  backup_retention_period = var.backup_retention_days
  backup_window           = var.backup_window
  maintenance_window      = var.maintenance_window
  copy_tags_to_snapshot   = true

  auto_minor_version_upgrade = true
  deletion_protection        = var.deletion_protection

  # In dev we want destroy/rebuild to work for the G5 reproducibility proof.
  # Outside dev this should be false + a final snapshot.
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name_prefix}-db-final-${formatdate("YYYYMMDDhhmmss", timestamp())}"

  performance_insights_enabled    = var.performance_insights_enabled
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  lifecycle {
    ignore_changes = [final_snapshot_identifier]
  }

  tags = { Name = "${var.name_prefix}-db" }
}

# ---------------------------------------------------------------------------
# RDS Proxy
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "proxy_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "proxy" {
  name               = "${var.name_prefix}-db-proxy"
  assume_role_policy = data.aws_iam_policy_document.proxy_assume.json
}

data "aws_iam_policy_document" "proxy" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_db_instance.this.master_user_secret[0].secret_arn]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${var.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "proxy" {
  name   = "read-db-secret"
  role   = aws_iam_role.proxy.id
  policy = data.aws_iam_policy_document.proxy.json
}

resource "aws_db_proxy" "this" {
  name                   = "${var.name_prefix}-db-proxy"
  engine_family          = "POSTGRESQL"
  role_arn               = aws_iam_role.proxy.arn
  vpc_subnet_ids         = var.subnet_ids
  vpc_security_group_ids = [aws_security_group.proxy.id]
  require_tls            = true

  # Kill a borrowed connection that is never returned rather than leaking it.
  idle_client_timeout = 1800

  auth {
    auth_scheme = "SECRETS"
    iam_auth    = "DISABLED"
    secret_arn  = aws_db_instance.this.master_user_secret[0].secret_arn
  }

  tags = { Name = "${var.name_prefix}-db-proxy" }
}

resource "aws_db_proxy_default_target_group" "this" {
  db_proxy_name = aws_db_proxy.this.name

  connection_pool_config {
    # NOT a per-service quota — this caps the proxy's own pool against the
    # instance and leaves headroom for maintenance connections (T4.6).
    max_connections_percent      = var.proxy_max_connections_percent
    max_idle_connections_percent = var.proxy_max_idle_connections_percent
    connection_borrow_timeout    = 120
  }
}

resource "aws_db_proxy_target" "this" {
  db_proxy_name          = aws_db_proxy.this.name
  target_group_name      = aws_db_proxy_default_target_group.this.name
  db_instance_identifier = aws_db_instance.this.identifier
}
