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

variable "job_token_secret_prefix" {
  description = "Secrets Manager name prefix for per-job Snowflake token secrets."
  type        = string
  default     = "ml-platform/job-tokens/"
}

variable "tenant_execution_role_arn_pattern" {
  description = "ARN pattern of per-tenant execution roles (tmt-dataplane) for iam:PassRole."
  type        = string
}

variable "dataplane_runtime_role_arn" {
  description = "ARN of the dataplane account's ml-platform-dataplane-runtime role. Set for the control-plane/dataplane account split: the backend assumes it (with tenantId session tags) for EMR and job-secret operations. Leave null for single-account deployments."
  type        = string
  default     = null
}

variable "emr_studio_tier_role_arns" {
  description = "EMR Studio IAM auth mode: ARNs of the basic/intermediate tier roles (from the tmt-dataplane emr-studio module's tier_role_arns output) the backend may assume to presign Studio URLs. Empty for SSO mode."
  type        = list(string)
  default     = []
}

variable "emr_auth_mode" {
  description = "EMR Studio auth mode the backend uses: \"IAM\" (default; presigns via the tier roles below — requires emr_studio_id + both tier role ARNs) or \"SSO\" (deep-links EMR_STUDIO_URL from SSM)."
  type        = string
  default     = "IAM"
}

variable "emr_studio_id" {
  description = "IAM mode: the EMR Studio id the backend presigns into (the tmt-dataplane emr-studio module's studio_id output). Unused in SSO mode."
  type        = string
  default     = ""
}

variable "emr_studio_basic_role_arn" {
  description = "IAM mode: tier_role_arns[\"basic\"] from the tmt-dataplane emr-studio module. Unused in SSO mode."
  type        = string
  default     = ""
}

variable "emr_studio_intermediate_role_arn" {
  description = "IAM mode: tier_role_arns[\"intermediate\"] from the tmt-dataplane emr-studio module. Unused in SSO mode."
  type        = string
  default     = ""
}

variable "provisioning_event_bus_arn" {
  description = "EventBridge bus ARN for TenantProvisioningRequested events. Null uses the account's default bus. The bus NAME the app publishes to is derived from this same ARN, so IAM grant and publish target can never disagree."
  type        = string
  default     = null
}

variable "platform_api_base_url" {
  description = "Public base URL of this API (the ALB DNS name or friendly domain, e.g. https://mlplatform.example.com). Injected into training jobs as ML_PLATFORM_API_URL so they can log metrics/params/tags back with their run token. Required: without it, run-token logging silently no-ops in every training job."
  type        = string
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
