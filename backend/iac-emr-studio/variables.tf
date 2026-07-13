variable "name_prefix" {
  description = "Prefix for all named resources (e.g. ml-platform)."
  type        = string
  default     = "ml-platform"
}

variable "vpc_id" {
  description = "VPC to attach the Studio's Engine/Workspace security groups to."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets the Studio can launch Workspaces into (must route to the VPC's EMR Serverless / EMR endpoints)."
  type        = list(string)
}

variable "default_s3_location" {
  description = "S3 URI where Workspace notebook files (.ipynb) are stored, e.g. s3://ml-platform-artifacts-prod/emr-studio-workspaces."
  type        = string
}

variable "workspace_egress_cidrs" {
  description = "CIDRs the Workspace security group may reach on 443 (Studio control-plane API, git, package indexes). Restrict to VPC endpoint / NAT egress ranges where possible; defaults to unrestricted."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "session_mappings" {
  description = <<-EOT
    IAM Identity Center identity -> access tier, keyed by identity name (the
    Identity Center group/user name — SCIM-synced from the Entra security
    groups documented in the platform README, e.g. "myapp-platform-admin").
    Tier must be "basic" or "intermediate" (see session policies below).
  EOT
  type        = map(string)
  default     = {}

  validation {
    condition     = alltrue([for tier in values(var.session_mappings) : contains(["basic", "intermediate"], tier)])
    error_message = "Each session_mappings value must be \"basic\" or \"intermediate\"."
  }
}

variable "session_identity_type" {
  description = "Identity type for all entries in session_mappings — \"GROUP\" (recommended) or \"USER\"."
  type        = string
  default     = "GROUP"
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}
