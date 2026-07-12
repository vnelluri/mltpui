terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

# Single-table design with overloaded GSIs. One table holds every entity
# (Tenant, GroupMapping, UserProfile, TrainingJob, Experiment, ExperimentRun,
# ModelVersion, GovernanceReview, AuditEvent, NotebookSession,
# SnowflakeTokenCache). Only key attributes are declared — schemaless items
# may carry any other attributes. PK/SK are the base primary key; GSI1/2/3
# are overloaded string keys reused across entities:
#
#   GSI1 — primary "by tenantId" axis. e.g. TrainingJob →
#          TENANT#<tenantId> / STATUS#<status>#JOB#<jobId>; ModelVersion →
#          TENANT#<tenantId> / STAGE#<stage>#MODEL#<name>#V#<version>.
#   GSI2 — secondary axis. e.g. UserProfile by email → EMAIL#<email> /
#          USER#<userId>; ExperimentRun by experiment →
#          EXPERIMENT#<experimentId> / RUN#<runId>.
#   GSI3 — tertiary axis. e.g. GroupMapping by role → ROLE#<role> /
#          GROUPMAPPING#<groupId>; Tenant by status (global) →
#          ENTITY#TENANT / STATUS#<status>#<tenantId>.
#
# This is the data store — protected against destroy both by DynamoDB
# deletion protection and by Terraform lifecycle. Removing it requires
# deliberately disabling both.
resource "aws_dynamodb_table" "this" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "PK"
  range_key = "SK"

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  attribute {
    name = "GSI1PK"
    type = "S"
  }
  attribute {
    name = "GSI1SK"
    type = "S"
  }
  attribute {
    name = "GSI2PK"
    type = "S"
  }
  attribute {
    name = "GSI2SK"
    type = "S"
  }
  attribute {
    name = "GSI3PK"
    type = "S"
  }
  attribute {
    name = "GSI3SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "GSI2"
    hash_key        = "GSI2PK"
    range_key       = "GSI2SK"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "GSI3"
    hash_key        = "GSI3PK"
    range_key       = "GSI3SK"
    projection_type = "ALL"
  }

  # Used by SnowflakeTokenCache items (epoch seconds); harmless no-op for
  # items without the attribute.
  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  # AWS-managed KMS key (same as the retired CloudFormation template's
  # SSEEnabled: true).
  server_side_encryption {
    enabled = true
  }

  deletion_protection_enabled = true

  tags = merge(var.tags, { Application = "ml-training-platform" })

  lifecycle {
    prevent_destroy = true
  }
}
