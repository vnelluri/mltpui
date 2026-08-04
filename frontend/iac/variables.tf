variable "name_prefix" {
  description = "Prefix for all named resources (e.g. ml-platform)."
  type        = string
  default     = "ml-platform"
}

variable "region" {
  description = "AWS region (used in log configuration)."
  type        = string
  default     = "us-east-1"
}

variable "cluster_arn" {
  description = "ARN of the ECS cluster to deploy into."
  type        = string
}

variable "image" {
  description = "Full frontend container image URI (ECR repo + tag)."
  type        = string
}

variable "cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 256
}

variable "memory" {
  description = "Fargate task memory (MiB)."
  type        = number
  default     = 512
}

variable "desired_count" {
  description = "Number of frontend tasks."
  type        = number
  default     = 2
}

variable "subnet_ids" {
  description = "Private subnets for the service (awsvpc networking)."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups attached to the tasks."
  type        = list(string)
}

variable "target_group_arn" {
  description = "ALB target group (ip target type) receiving non-/api traffic."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}
