# frontend/iac — Terraform module: ML platform frontend (control plane)

Deploys the React SPA (nginx image built by `frontend/Dockerfile`) as an ECS
Fargate service in the **control-plane account**. The frontend is static
serving only — its task role is intentionally empty.

Instantiate from your per-account pipeline root:

```hcl
module "frontend" {
  source = "git::https://<host>/tmt.git//frontend/iac?ref=main"

  name_prefix        = "ml-platform"
  cluster_arn        = aws_ecs_cluster.main.arn
  image              = "${local.ecr}/ml-platform-frontend:${var.image_tag}"
  subnet_ids         = var.private_subnet_ids
  security_group_ids = [aws_security_group.frontend.id]
  target_group_arn   = aws_lb_target_group.frontend.arn
}
```

Build-time note: `VITE_*` variables (API base URL, Cognito IDs, demo mode) are
baked into the bundle at `docker build` time — they are pipeline build args,
not runtime configuration, which is why this module has no secrets/SSM wiring.
