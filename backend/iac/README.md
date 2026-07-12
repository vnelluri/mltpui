# backend/iac — Terraform module: ML platform backend (control plane)

Deploys the FastAPI backend as an ECS Fargate service in the **control-plane
account**: task definition, ECS service, CloudWatch log group, and the two IAM
roles (execution + task). Replaces the hand-edited JSON formerly under
`infrastructure/ecs/` (removed).

This is a **module** (no provider/backend blocks) — instantiate it from your
per-account pipeline root, e.g.:

```hcl
module "backend" {
  source = "git::https://<host>/tmt.git//backend/iac?ref=main"

  name_prefix          = "ml-platform"
  cluster_arn          = aws_ecs_cluster.main.arn
  image                = "${local.ecr}/ml-platform-backend:${var.image_tag}"
  subnet_ids           = var.private_subnet_ids
  security_group_ids   = [aws_security_group.backend.id]
  target_group_arn     = aws_lb_target_group.backend.arn
  dynamodb_table_arn   = aws_dynamodb_table.ml_platform.arn
  artifacts_bucket     = "ml-platform-artifacts-prod"
  ssm_parameter_prefix = "/ml-platform"
  # ARN pattern of the per-tenant execution roles created by the
  # tmt-dataplane repo — required for iam:PassRole to EMR/SageMaker.
  tenant_execution_role_arn_pattern = "arn:aws:iam::${var.dataplane_account_id}:role/ml-platform-tenant-*-exec"
}
```

Notes:

- The task role includes `events:PutEvents` (tenant provisioning requests)
  and `iam:PassRole` restricted to the per-tenant execution-role name pattern
  — without the PassRole grant, real-mode job submission fails.
- Secrets/config are read from SSM Parameter Store / Secrets Manager under
  `ssm_parameter_prefix` (same paths as the README's AWS setup section).
- Per-tenant compute (EMR Serverless applications, execution roles, KMS keys)
  is **not** created here — that lives in the `tmt-dataplane` repository.
