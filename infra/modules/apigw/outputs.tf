output "api_endpoint" {
  description = "Public base URL. The only public entry point in the system."
  value       = aws_apigatewayv2_stage.this.invoke_url
}

output "api_id" { value = aws_apigatewayv2_api.this.id }

output "vpc_link_id" { value = aws_apigatewayv2_vpc_link.this.id }
