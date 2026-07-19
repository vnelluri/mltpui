terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  ssm_arn    = "arn:aws:ssm:${var.region}:${local.account_id}:parameter${var.ssm_parameter_prefix}"

  # In the account split each tenant has its own dataplane KMS key
  # (Tenant.kmsKeyArn, which the app prefers), so the platform-wide fallback
  # key is only injected for single-account deployments — otherwise its SSM
  # parameter would be a required-but-unused dependency.
  split_enabled = var.dataplane_runtime_role_arn != null

  # The app publishes provisioning events by bus NAME; IAM below grants by
  # ARN. Deriving the name from the same ARN keeps them in lockstep — a
  # custom bus in the variable previously left the app publishing to
  # "default", which the IAM grant then denied (and the app swallows
  # publish errors best-effort, so tenants just sat pending).
  provisioning_event_bus_name = (
    var.provisioning_event_bus_arn == null
    ? "default"
    : element(split("/", var.provisioning_event_bus_arn), 1)
  )

  # SSM-backed config injected as container secrets (matches app/config.py).
  ssm_secrets = merge(
    {
      COGNITO_USER_POOL_ID      = "${local.ssm_arn}/cognito/user-pool-id"
      COGNITO_APP_CLIENT_ID     = "${local.ssm_arn}/cognito/app-client-id"
      CORS_ALLOWED_ORIGINS      = "${local.ssm_arn}/cors/allowed-origins"
      EMR_STUDIO_URL            = "${local.ssm_arn}/emr/studio-url"
      SAGEMAKER_DOMAIN_ID       = "${local.ssm_arn}/sagemaker/domain-id"
      SAGEMAKER_TRAINING_IMAGE  = "${local.ssm_arn}/sagemaker/training-image"
      SNOWFLAKE_ACCOUNT         = "${local.ssm_arn}/snowflake/account"
      SNOWFLAKE_TOKEN_URL       = "${local.ssm_arn}/snowflake/token-url"
      SNOWFLAKE_OAUTH_CLIENT_ID = "${local.ssm_arn}/snowflake/oauth-client-id"
    },
    local.split_enabled ? {} : {
      KMS_SNOWFLAKE_KEY_ARN = "${local.ssm_arn}/kms/snowflake-key-arn"
    },
  )

  plain_environment = {
    AUTH_MODE                        = "prod"
    AWS_REGION                       = var.region
    DYNAMODB_TABLE_NAME              = var.dynamodb_table_name
    S3_ARTIFACTS_BUCKET              = var.artifacts_bucket
    EMR_MOCK_MODE                    = "false"
    SAGEMAKER_MOCK_MODE              = "false"
    SNOWFLAKE_MOCK_MODE              = "false"
    TENANT_PROVISIONING_MOCK_MODE    = "false"
    TENANT_PROVISIONING_EVENT_BUS    = local.provisioning_event_bus_name
    PLATFORM_API_BASE_URL            = var.platform_api_base_url
    SNOWFLAKE_OAUTH_INTEGRATION_NAME = "ml_platform_oauth"
    SNOWFLAKE_DEFAULT_WAREHOUSE      = "COMPUTE_WH"
    SNOWFLAKE_DEFAULT_ROLE           = "ML_PLATFORM_ROLE"
    SECRETS_MANAGER_JOB_TOKEN_PREFIX = var.job_token_secret_prefix
    DATAPLANE_RUNTIME_ROLE_ARN       = var.dataplane_runtime_role_arn == null ? "" : var.dataplane_runtime_role_arn
  }
}

# ── Logging ──────────────────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${var.name_prefix}-backend"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# ── Execution role (image pull, logs, config injection) ─────────────────────
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name_prefix}-ecs-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_config" {
  statement {
    sid       = "ReadConfigParameters"
    actions   = ["ssm:GetParameters"]
    resources = ["${local.ssm_arn}/*"]
  }
  statement {
    sid       = "ReadOAuthClientSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.snowflake_oauth_secret_arn]
  }
}

resource "aws_iam_role_policy" "execution_config" {
  name   = "config-injection"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_config.json
}

# ── Task role (runtime permissions of the app itself) ───────────────────────
resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-backend-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "task" {
  statement {
    sid = "DynamoSingleTable"
    actions = [
      "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
      "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan",
      "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem",
    ]
    resources = [var.dynamodb_table_arn, "${var.dynamodb_table_arn}/index/*"]
  }

  statement {
    sid       = "ArtifactsBucketList"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.artifacts_bucket}"]
  }
  statement {
    sid       = "ArtifactsBucketObjects"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["arn:aws:s3:::${var.artifacts_bucket}/*"]
  }

  # KMS for Snowflake-token encryption AND the artifacts bucket's SSE key.
  # Scoped by the `platform` resource tag rather than a static ARN list, so
  # per-tenant keys created dynamically by the tmt-dataplane reconcile
  # pipeline are covered without re-applying this module. GenerateDataKey is
  # needed for S3 SSE-KMS (encrypt-on-write). Cross-account use is still
  # gated by each key's key policy (granted to this task role by
  # tmt-dataplane); this identity policy is the second required half.
  statement {
    sid = "PlatformKmsKeys"
    actions = [
      "kms:Encrypt", "kms:Decrypt", "kms:DescribeKey",
      "kms:GenerateDataKey", "kms:ReEncrypt*",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ResourceTag/platform"
      values   = [var.name_prefix]
    }
  }

  statement {
    sid = "JobTokenSecrets"
    actions = [
      "secretsmanager:CreateSecret", "secretsmanager:PutSecretValue",
      "secretsmanager:GetSecretValue", "secretsmanager:DeleteSecret",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      "arn:aws:secretsmanager:${var.region}:${local.account_id}:secret:${var.job_token_secret_prefix}*"
    ]
  }

  statement {
    sid = "EmrServerlessJobs"
    actions = [
      "emr-serverless:StartJobRun", "emr-serverless:GetJobRun",
      "emr-serverless:CancelJobRun", "emr-serverless:ListJobRuns",
      "emr-serverless:GetApplication",
    ]
    # Per-tenant applications are created by tmt-dataplane; constrain by tag.
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/platform"
      values   = [var.name_prefix]
    }
  }

  statement {
    sid = "SageMakerTrainingJobs"
    actions = [
      "sagemaker:CreateTrainingJob", "sagemaker:DescribeTrainingJob",
      "sagemaker:StopTrainingJob", "sagemaker:CreatePresignedDomainUrl",
    ]
    resources = ["*"]
  }

  # Required to hand the per-tenant execution role to EMR Serverless /
  # SageMaker at job submission (Tenant.executionRoleArn).
  statement {
    sid       = "PassTenantExecutionRoles"
    actions   = ["iam:PassRole"]
    resources = [var.tenant_execution_role_arn_pattern]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["emr-serverless.amazonaws.com", "sagemaker.amazonaws.com"]
    }
  }

  statement {
    sid     = "TenantProvisioningEvents"
    actions = ["events:PutEvents"]
    resources = [
      coalesce(
        var.provisioning_event_bus_arn,
        "arn:aws:events:${var.region}:${local.account_id}:event-bus/default"
      )
    ]
  }

  # Account split: EMR and job-secret operations go through the dataplane
  # runtime role, assumed with tenantId session tags (ABAC).
  dynamic "statement" {
    for_each = var.dataplane_runtime_role_arn == null ? [] : [1]
    content {
      sid       = "AssumeDataplaneRuntime"
      actions   = ["sts:AssumeRole", "sts:TagSession"]
      resources = [var.dataplane_runtime_role_arn]
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "runtime"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# ── Task definition + service ────────────────────────────────────────────────
resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.name_prefix}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  tags                     = var.tags

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "backend"
      image     = var.image
      essential = true
      portMappings = [
        { name = "http", containerPort = 8000, protocol = "tcp", appProtocol = "http" }
      ]
      environment = [
        for k, v in local.plain_environment : { name = k, value = v }
      ]
      secrets = concat(
        [for k, v in local.ssm_secrets : { name = k, valueFrom = v }],
        [{ name = "SNOWFLAKE_OAUTH_CLIENT_SECRET", valueFrom = var.snowflake_oauth_secret_arn }]
      )
      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.backend.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "backend"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "backend" {
  name            = "${var.name_prefix}-backend"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  tags            = var.tags

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "backend"
    container_port   = 8000
  }

  lifecycle {
    ignore_changes = [desired_count] # allow autoscaling to own this
  }
}
