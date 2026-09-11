# Network topology per ADR-010.
#
#   public      : NAT gateway only. Nothing else is public-facing.
#   private-app : ECS tasks + the INTERNAL ALB.
#   private-data: RDS + ElastiCache. No route to NAT or IGW at all.
#
# Egress posture (threat model T2.4 / AR-7): AWS-service traffic leaves through
# VPC endpoints and never touches NAT. Only the `payments` service is given a
# route to the internet, because only it talks to Daraja. Security groups
# cannot filter by hostname, so "Daraja-only" is NOT claimed — the residual is
# accepted as AR-7 and watched via flow logs.

locals {
  # Two AZs, pinned explicitly. Deliberately NOT derived from
  # data.aws_availability_zones: which AZs an account can use varies per
  # account, so auto-discovery makes plans differ between teammates.
  # See ADR-001 and docs/scar-log.md — us-west-1 does not offer 1b to every
  # account, so this list is a variable and must be verified against the
  # target account before the first apply.
  azs = var.availability_zones

  # /16 split into predictable /20s so a subnet's purpose is readable from
  # its CIDR during an incident.
  public_cidrs       = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  private_app_cidrs  = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 4)]
  private_data_cidrs = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 8)]
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.name_prefix}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name_prefix}-igw" }
}

# ---------------------------------------------------------------------------
# Subnets
# ---------------------------------------------------------------------------

resource "aws_subnet" "public" {
  for_each = { for i, az in local.azs : az => i }

  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = local.public_cidrs[each.value]

  # Explicit: nothing in a public subnet should get an address automatically.
  # The NAT gateway has its own EIP.
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.name_prefix}-public-${each.key}"
    tier = "public"
  }
}

resource "aws_subnet" "private_app" {
  for_each = { for i, az in local.azs : az => i }

  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.key
  cidr_block              = local.private_app_cidrs[each.value]
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.name_prefix}-private-app-${each.key}"
    tier = "private-app"
  }
}

resource "aws_subnet" "private_data" {
  for_each = { for i, az in local.azs : az => i }

  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.key
  cidr_block              = local.private_data_cidrs[each.value]
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.name_prefix}-private-data-${each.key}"
    tier = "private-data"
  }
}

# ---------------------------------------------------------------------------
# NAT
#
# One NAT for dev, accepted as a single point of egress failure (AR-1).
# `nat_gateway_count` is the upgrade path: set it to length(azs) before any
# drill that claims AZ-independent egress.
# ---------------------------------------------------------------------------

resource "aws_eip" "nat" {
  count  = var.nat_gateway_count
  domain = "vpc"
  tags   = { Name = "${var.name_prefix}-nat-eip-${count.index}" }
}

resource "aws_nat_gateway" "this" {
  count = var.nat_gateway_count

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[local.azs[count.index]].id

  tags = { Name = "${var.name_prefix}-nat-${count.index}" }

  depends_on = [aws_internet_gateway.this]
}

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name_prefix}-rt-public" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

# One app route table per AZ so a future move to one-NAT-per-AZ is a variable
# change, not a refactor.
resource "aws_route_table" "private_app" {
  for_each = aws_subnet.private_app

  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name_prefix}-rt-private-app-${each.key}" }
}

resource "aws_route" "private_app_nat" {
  for_each = aws_subnet.private_app

  route_table_id         = aws_route_table.private_app[each.key].id
  destination_cidr_block = "0.0.0.0/0"

  # With a single NAT every AZ shares it (AR-1). With one per AZ each routes
  # to its own, and an AZ failure stops being a whole-VPC egress outage.
  nat_gateway_id = aws_nat_gateway.this[
    var.nat_gateway_count == 1 ? 0 : index(local.azs, each.key)
  ].id
}

resource "aws_route_table_association" "private_app" {
  for_each = aws_subnet.private_app

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private_app[each.key].id
}

# Data tier: a route table with NO default route. Not "no public IP" — no path
# to the internet at all, in either direction (ADR-010, threat model T2.2).
resource "aws_route_table" "private_data" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name_prefix}-rt-private-data" }
}

resource "aws_route_table_association" "private_data" {
  for_each = aws_subnet.private_data

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private_data.id
}

# ---------------------------------------------------------------------------
# VPC endpoints (threat model T2.4)
#
# These are the implementable half of the egress story: S3, ECR, Secrets
# Manager and CloudWatch traffic never traverses NAT, so a compromised task
# cannot reach those services through the open internet path, and three of the
# four services need no internet route at all.
# ---------------------------------------------------------------------------

resource "aws_security_group" "vpc_endpoints" {
  name        = "${var.name_prefix}-vpce"
  description = "Interface VPC endpoints - HTTPS from inside the VPC only"
  vpc_id      = aws_vpc.this.id

  tags = { Name = "${var.name_prefix}-vpce" }
}

resource "aws_vpc_security_group_ingress_rule" "vpc_endpoints_https" {
  security_group_id = aws_security_group.vpc_endpoints.id
  description       = "HTTPS from within the VPC"
  cidr_ipv4         = aws_vpc.this.cidr_block
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

# Gateway endpoint — routed, not an ENI, so it costs nothing per hour and
# attaches to route tables rather than subnets.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"

  route_table_ids = concat(
    [for rt in aws_route_table.private_app : rt.id],
    [aws_route_table.private_data.id],
  )

  tags = { Name = "${var.name_prefix}-vpce-s3" }
}

resource "aws_vpc_endpoint" "interface" {
  for_each = toset(var.interface_endpoints)

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [for s in aws_subnet.private_app : s.id]
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = { Name = "${var.name_prefix}-vpce-${each.key}" }
}

# ---------------------------------------------------------------------------
# Flow logs (threat model T2.4 / AR-7)
#
# Since egress cannot be restricted by hostname, flow logs are how an
# unexpected destination becomes visible at all. Without these, AR-7 would be
# an accepted risk with no detection attached to it.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "flow_logs" {
  name              = "/${var.name_prefix}/vpc-flow-logs"
  retention_in_days = var.flow_log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = { Name = "${var.name_prefix}-vpc-flow-logs" }
}

data "aws_iam_policy_document" "flow_logs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "flow_logs" {
  name               = "${var.name_prefix}-vpc-flow-logs"
  assume_role_policy = data.aws_iam_policy_document.flow_logs_assume.json
}

data "aws_iam_policy_document" "flow_logs" {
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
    ]
    resources = ["${aws_cloudwatch_log_group.flow_logs.arn}:*"]
  }
}

resource "aws_iam_role_policy" "flow_logs" {
  name   = "publish"
  role   = aws_iam_role.flow_logs.id
  policy = data.aws_iam_policy_document.flow_logs.json
}

resource "aws_flow_log" "this" {
  vpc_id                   = aws_vpc.this.id
  traffic_type             = "ALL"
  log_destination_type     = "cloud-watch-logs"
  log_destination          = aws_cloudwatch_log_group.flow_logs.arn
  iam_role_arn             = aws_iam_role.flow_logs.arn
  max_aggregation_interval = 60

  tags = { Name = "${var.name_prefix}-flow-logs" }
}
