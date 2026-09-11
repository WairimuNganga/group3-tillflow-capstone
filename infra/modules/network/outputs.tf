output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  value = [for s in aws_subnet.public : s.id]
}

output "private_app_subnet_ids" {
  value = [for s in aws_subnet.private_app : s.id]
}

output "private_data_subnet_ids" {
  value = [for s in aws_subnet.private_data : s.id]
}

output "availability_zones" {
  value = local.azs
}

output "vpc_endpoint_security_group_id" {
  value = aws_security_group.vpc_endpoints.id
}

output "private_data_route_table_id" {
  description = "Data-tier route table. Has no 0.0.0.0/0 route by design (T2.2)."
  value       = aws_route_table.private_data.id
}
