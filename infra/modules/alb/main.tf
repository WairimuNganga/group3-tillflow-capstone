# INTERNAL Application Load Balancer.
#
# Threat model T2.1: this ALB carries external traffic only — API Gateway →
# VPC Link → here. Internal service-to-service calls use Service Connect, so
# there is deliberately no in-VPC caller to allow. It never gets a public
# listener and never gets a public subnet.

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-alb"
  description = "Internal ALB — inbound from the API Gateway VPC Link only"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "from_vpc_link" {
  security_group_id            = aws_security_group.this.id
  description                  = "HTTP from the API Gateway VPC Link ENIs"
  referenced_security_group_id = var.vpc_link_security_group_id
  from_port                    = var.listener_port
  to_port                      = var.listener_port
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "to_targets" {
  security_group_id = aws_security_group.this.id
  description       = "To ECS targets inside the VPC"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
}

resource "aws_lb" "this" {
  name               = "${var.name_prefix}-alb"
  load_balancer_type = "application"
  internal           = true # never public (ADR-010)
  subnets            = var.subnet_ids
  security_groups    = [aws_security_group.this.id]

  drop_invalid_header_fields = true
  enable_deletion_protection = var.enable_deletion_protection

  # Access logs go to the dedicated SSE-S3 bucket. ALB log delivery does not
  # support a customer-managed CMK — pointing this at the KMS-encrypted logs
  # bucket would silently stop delivery (ADR-003 exception, threat model T8.4).
  access_logs {
    bucket  = var.access_logs_bucket
    prefix  = "alb"
    enabled = true
  }

  tags = { Name = "${var.name_prefix}-alb" }
}

resource "aws_lb_target_group" "this" {
  for_each = var.targets

  name        = "${var.name_prefix}-${each.key}"
  port        = each.value.port
  protocol    = "HTTP"
  target_type = "ip" # awsvpc networking
  vpc_id      = var.vpc_id

  # Fargate tasks come and go; don't hold a connection open to a draining task
  # longer than it takes to finish in-flight work.
  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = each.value.health_path
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name    = "${var.name_prefix}-${each.key}"
    service = each.key
  }
}

resource "aws_lb_listener" "this" {
  load_balancer_arn = aws_lb.this.arn
  port              = var.listener_port
  protocol          = "HTTP"

  # Default deny. A request that matches no service rule gets 404 from the ALB
  # rather than being handed to whichever target group happened to be first.
  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "application/json"
      message_body = jsonencode({ error = "no route" })
      status_code  = "404"
    }
  }
}

resource "aws_lb_listener_rule" "this" {
  for_each = var.targets

  listener_arn = aws_lb_listener.this.arn
  priority     = each.value.priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this[each.key].arn
  }

  condition {
    path_pattern {
      values = each.value.path_patterns
    }
  }

  tags = { service = each.key }
}
