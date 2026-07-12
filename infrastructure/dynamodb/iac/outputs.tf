output "table_name" {
  description = "DynamoDB table name — the backend's DYNAMODB_TABLE_NAME."
  value       = aws_dynamodb_table.this.name
}

output "table_arn" {
  description = "DynamoDB table ARN, for IAM policy references (index access needs \"$${arn}/index/*\")."
  value       = aws_dynamodb_table.this.arn
}
