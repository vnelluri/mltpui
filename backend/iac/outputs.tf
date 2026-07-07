output "service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.backend.name
}

output "task_role_arn" {
  description = "Backend task role ARN — trusted principal for the tmt-dataplane runtime role."
  value       = aws_iam_role.task.arn
}

output "task_definition_arn" {
  description = "Registered task definition ARN."
  value       = aws_ecs_task_definition.backend.arn
}

output "log_group_name" {
  description = "CloudWatch log group for the backend."
  value       = aws_cloudwatch_log_group.backend.name
}
