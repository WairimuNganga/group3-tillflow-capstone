# API Gateway HTTP API → VPC Link → internal ALB (ADR-010).
#
# This is the only public entry point in the system. Everything behind it is
# private: the ALB is internal, no task has a public IP, and the data subnets
# have no internet route at all.
#
# The VPC Link security group is created by the ROOT module, not here: the ALB
# must allow it as ingress while this module must reference the ALB's listener,
# which would be a dependency cycle if either module owned the SG.

resource "aws_apigatewayv2_vpc_link" "this" {
  name               = "${var.name_prefix}-vpclink"
  subnet_ids         = var.subnet_ids
  security_group_ids = [var.vpc_link_security_group_id]

  tags = { Name = "${var.name_prefix}-vpclink" }
}

resource "aws_apigatewayv2_api" "this" {
  name          = "${var.name_prefix}-api"
  protocol_type = "HTTP"
  description   = "TillFlow public edge"

  cors_configuration {
    allow_origins = var.cors_allow_origins
    allow_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_headers = ["content-type", "authorization", "idempotency-key"]
    max_age       = 300
  }
}

resource "aws_apigatewayv2_integration" "alb" {
  api_id             = aws_apigatewayv2_api.this.id
  integration_type   = "HTTP_PROXY"
  integration_method = "ANY"
  integration_uri    = var.alb_listener_arn
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.this.id

  payload_format_version = "1.0"
  timeout_milliseconds   = var.integration_timeout_ms
}

resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.alb.id}"
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/${var.name_prefix}/apigw"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

resource "aws_apigatewayv2_stage" "this" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = var.stage_name
  auto_deploy = true

  # Throttling is the DoS control from threat model T1.3. Set at the stage so
  # it applies before a request ever reaches ECS.
  default_route_settings {
    throttling_burst_limit   = var.throttle_burst
    throttling_rate_limit    = var.throttle_rate
    detailed_metrics_enabled = true
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn

    # JSON so it correlates with the services' structured logs (ADR-008).
    format = jsonencode({
      requestId       = "$context.requestId"
      ip              = "$context.identity.sourceIp"
      requestTime     = "$context.requestTime"
      httpMethod      = "$context.httpMethod"
      routeKey        = "$context.routeKey"
      status          = "$context.status"
      protocol        = "$context.protocol"
      responseLength  = "$context.responseLength"
      integrationLat  = "$context.integrationLatency"
      responseLatency = "$context.responseLatency"
    })
  }

  tags = { Name = "${var.name_prefix}-api-${var.stage_name}" }
}
