output "studio_id" {
  description = "EMR Studio ID."
  value       = aws_emr_studio.this.id
}

output "url" {
  description = "Studio access URL — set this as the backend's EMR_STUDIO_URL (see backend/iac's ssm/emr/studio-url parameter)."
  value       = aws_emr_studio.this.url
}

output "service_role_arn" {
  description = "Studio service role ARN."
  value       = aws_iam_role.service.arn
}

output "user_role_arn" {
  description = "Studio user role ARN — shared by every SSO session (platform-global; see README limitation)."
  value       = aws_iam_role.user.arn
}

output "engine_security_group_id" {
  description = "Engine SG ID — attach this to any EMR Serverless application / cluster the Studio should be able to reach."
  value       = aws_security_group.engine.id
}

output "workspace_security_group_id" {
  description = "Workspace SG ID."
  value       = aws_security_group.workspace.id
}

output "session_policy_arns" {
  description = "Session policy ARNs by tier (basic, intermediate), for wiring additional session_mappings outside this module."
  value       = local.session_policy_arns
}
