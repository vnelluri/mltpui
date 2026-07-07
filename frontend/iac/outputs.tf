output "service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.frontend.name
}

output "task_definition_arn" {
  description = "Registered task definition ARN."
  value       = aws_ecs_task_definition.frontend.arn
}

output "log_group_name" {
  description = "CloudWatch log group for the frontend."
  value       = aws_cloudwatch_log_group.frontend.name
}
