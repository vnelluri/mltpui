variable "name_prefix" {
  description = "Prefix for all named resources (e.g. ml-platform)."
  type        = string
  default     = "ml-platform"
}

variable "region" {
  description = "AWS region (used in log configuration and SSM ARNs)."
  type        = string
  default     = "us-east-1"
}

variable "cluster_arn" {
  description = "ARN of the ECS cluster to deploy into."
  type        = string
}

variable "image" {
  description = "Full backend container image URI (ECR repo + tag)."
  type        = string
}

variable "cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 512
}

variable "memory" {
  description = "Fargate task memory (MiB)."
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Number of backend tasks."
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
  description = "ALB target group (ip target type) receiving /api traffic."
  type        = string
}

variable "dynamodb_table_arn" {
  description = "ARN of the ml-platform single table (GSIs are derived)."
  type        = string
}

variable "dynamodb_table_name" {
  description = "Name of the ml-platform single table."
  type        = string
  default     = "ml-platform"
}

variable "artifacts_bucket" {
  description = "Shared artifacts S3 bucket name."
  type        = string
}

variable "ssm_parameter_prefix" {
  description = "SSM Parameter Store prefix holding backend config (see README env table)."
  type        = string
  default     = "/ml-platform"
}

variable "snowflake_oauth_secret_arn" {
  description = "Secrets Manager ARN of the Snowflake OAuth client secret."
  type        = string
}

variable "kms_snowflake_key_arns" {
  description = "KMS key ARNs the backend may Encrypt/Decrypt with (Snowflake token keys, incl. per-tenant keys from tmt-dataplane)."
  type        = list(string)
}

variable "job_token_secret_prefix" {
  description = "Secrets Manager name prefix for per-job Snowflake token secrets."
  type        = string
  default     = "ml-platform/job-tokens/"
}

variable "tenant_execution_role_arn_pattern" {
  description = "ARN pattern of per-tenant execution roles (tmt-dataplane) for iam:PassRole."
  type        = string
}

variable "provisioning_event_bus_arn" {
  description = "EventBridge bus ARN for TenantProvisioningRequested events."
  type        = string
  default     = null
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 90
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}
