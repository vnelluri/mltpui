terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

locals {
  # default_s3_location is s3://bucket/optional/prefix — split so IAM
  # statements can scope ListBucket (needs the bucket ARN) separately from
  # object actions (needs the bucket+prefix ARN).
  s3_location_trimmed = trimprefix(var.default_s3_location, "s3://")
  s3_bucket_name      = split("/", local.s3_location_trimmed)[0]
  s3_bucket_arn       = "arn:aws:s3:::${local.s3_bucket_name}"
  s3_prefix           = join("/", slice(split("/", local.s3_location_trimmed), 1, length(split("/", local.s3_location_trimmed))))
  s3_objects_arn      = local.s3_prefix == "" ? "${local.s3_bucket_arn}/*" : "${local.s3_bucket_arn}/${local.s3_prefix}/*"
}

# ── Security groups ───────────────────────────────────────────────────────────
# Two-SG model required by EMR Studio: the Workspace (notebook editor UI) only
# ever talks to the Engine (the attached EMR Serverless application / cluster)
# on 18888 (Jupyter Enterprise Gateway); nothing else may reach the Workspace.
resource "aws_security_group" "engine" {
  name        = "${var.name_prefix}-emr-studio-engine"
  description = "EMR Studio Engine SG — accepts Workspace connections on 18888."
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-emr-studio-engine" })
}

resource "aws_security_group" "workspace" {
  name        = "${var.name_prefix}-emr-studio-workspace"
  description = "EMR Studio Workspace SG — outbound only, to the Engine SG and the Studio control plane."
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-emr-studio-workspace" })
}

resource "aws_vpc_security_group_ingress_rule" "engine_from_workspace" {
  security_group_id            = aws_security_group.engine.id
  referenced_security_group_id = aws_security_group.workspace.id
  ip_protocol                  = "tcp"
  from_port                    = 18888
  to_port                      = 18888
  description                  = "Jupyter Enterprise Gateway from Workspace"
}

resource "aws_vpc_security_group_egress_rule" "engine_all" {
  security_group_id = aws_security_group.engine.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Engine reaches EMR Serverless / AWS API endpoints"
}

resource "aws_vpc_security_group_egress_rule" "workspace_to_engine" {
  security_group_id            = aws_security_group.workspace.id
  referenced_security_group_id = aws_security_group.engine.id
  ip_protocol                  = "tcp"
  from_port                    = 18888
  to_port                      = 18888
  description                  = "Workspace reaches Jupyter Enterprise Gateway on the Engine"
}

resource "aws_vpc_security_group_egress_rule" "workspace_https" {
  for_each = toset(var.workspace_egress_cidrs)

  security_group_id = aws_security_group.workspace.id
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "Workspace reaches the EMR Studio control plane / git / package indexes"
}

# ── Service role (assumed by the EMR Studio control plane itself) ───────────
data "aws_iam_policy_document" "studio_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["elasticmapreduce.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "service" {
  name               = "${var.name_prefix}-emr-studio-service-role"
  assume_role_policy = data.aws_iam_policy_document.studio_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "service" {
  statement {
    sid = "AllowEMRReadOnly"
    actions = [
      "elasticmapreduce:ListInstances",
      "elasticmapreduce:DescribeCluster",
      "elasticmapreduce:ListSteps",
    ]
    resources = ["*"]
  }

  statement {
    sid = "AllowEC2ENIAndNetworkReadOnly"
    actions = [
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeVpcs",
      "ec2:DescribeNetworkInterfaces",
      "ec2:CreateNetworkInterface",
      "ec2:CreateNetworkInterfacePermission",
      "ec2:DeleteNetworkInterface",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "AllowWorkspaceBucketList"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [local.s3_bucket_arn]
  }

  statement {
    sid = "AllowWorkspaceBucketObjects"
    actions = [
      "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:GetEncryptionConfiguration",
    ]
    resources = [local.s3_objects_arn]
  }
}

resource "aws_iam_role_policy" "service" {
  name   = "emr-studio-service"
  role   = aws_iam_role.service.id
  policy = data.aws_iam_policy_document.service.json
}

# ── User role (assumed by every federated SSO user via Identity Center) ─────
# Platform-global by design (see repo README's MVP limitation): all users
# share this one role, so it is scoped to browsing/attaching EMR Serverless
# applications and the shared Workspace bucket — NOT to any tenant's data.
# Per-tenant isolation for notebook activity is a later release.
resource "aws_iam_role" "user" {
  name               = "${var.name_prefix}-emr-studio-user-role"
  assume_role_policy = data.aws_iam_policy_document.studio_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "user" {
  statement {
    sid = "AllowStudioSelfService"
    actions = [
      "elasticmapreduce:DescribeStudio",
      "elasticmapreduce:ListStudios",
      "elasticmapreduce:DescribeCluster",
      "elasticmapreduce:ListInstances",
      "elasticmapreduce:ListSteps",
    ]
    resources = ["*"]
  }

  statement {
    sid = "AllowEmrServerlessBrowse"
    actions = [
      "emr-serverless:ListApplications",
      "emr-serverless:GetApplication",
      "emr-serverless:ListJobRuns",
      "emr-serverless:GetJobRun",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "AllowWorkspaceBucketList"
    actions   = ["s3:ListBucket"]
    resources = [local.s3_bucket_arn]
  }

  statement {
    sid       = "AllowWorkspaceBucketObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [local.s3_objects_arn]
  }
}

resource "aws_iam_role_policy" "user" {
  name   = "emr-studio-user"
  role   = aws_iam_role.user.id
  policy = data.aws_iam_policy_document.user.json
}

# ── Session policies (referenced by session mappings below) ─────────────────
# Mirrors AWS's published "basic" / "intermediate" EMR Studio session-policy
# templates: they further restrict what an assumed session may do beyond the
# user role above. "basic" = attach + run notebooks only; "intermediate" adds
# the ability to create/terminate the EMR Serverless applications a Workspace
# attaches to.
data "aws_iam_policy_document" "session_basic" {
  statement {
    sid = "BasicNotebookUsage"
    actions = [
      "elasticmapreduce:DescribeStudio",
      "elasticmapreduce:DescribeCluster",
      "elasticmapreduce:ListInstances",
      "emr-serverless:ListApplications",
      "emr-serverless:GetApplication",
      "emr-serverless:GetJobRun",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "BasicWorkspaceStorage"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [local.s3_bucket_arn, local.s3_objects_arn]
  }
}

data "aws_iam_policy_document" "session_intermediate" {
  source_policy_documents = [data.aws_iam_policy_document.session_basic.json]

  statement {
    sid = "IntermediateApplicationLifecycle"
    actions = [
      "emr-serverless:StartApplication",
      "emr-serverless:StopApplication",
      "emr-serverless:StartJobRun",
      "emr-serverless:CancelJobRun",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "session_basic" {
  name   = "${var.name_prefix}-emr-studio-session-basic"
  policy = data.aws_iam_policy_document.session_basic.json
  tags   = var.tags
}

resource "aws_iam_policy" "session_intermediate" {
  name   = "${var.name_prefix}-emr-studio-session-intermediate"
  policy = data.aws_iam_policy_document.session_intermediate.json
  tags   = var.tags
}

locals {
  session_policy_arns = {
    basic        = aws_iam_policy.session_basic.arn
    intermediate = aws_iam_policy.session_intermediate.arn
  }
}

# ── Studio ────────────────────────────────────────────────────────────────────
resource "aws_emr_studio" "this" {
  name                        = "${var.name_prefix}-studio"
  auth_mode                   = "SSO"
  default_s3_location         = var.default_s3_location
  engine_security_group_id    = aws_security_group.engine.id
  workspace_security_group_id = aws_security_group.workspace.id
  service_role                = aws_iam_role.service.arn
  user_role                   = aws_iam_role.user.arn
  vpc_id                      = var.vpc_id
  subnet_ids                  = var.subnet_ids
  tags                        = var.tags
}

# ── Session mappings ──────────────────────────────────────────────────────────
# Grants IAM Identity Center groups/users access; the identity names must
# already exist in Identity Center (SCIM-synced from the Entra security
# groups documented in the platform README) — this module does not create
# them.
resource "aws_emr_studio_session_mapping" "this" {
  for_each = var.session_mappings

  studio_id          = aws_emr_studio.this.id
  identity_type      = var.session_identity_type
  identity_name      = each.key
  session_policy_arn = local.session_policy_arns[each.value]
}
