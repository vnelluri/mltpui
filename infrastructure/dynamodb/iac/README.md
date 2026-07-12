# infrastructure/dynamodb/iac — Terraform module: platform DynamoDB table

The single table (default name `ml-platform`) behind the whole control plane —
every entity lives here under the overloaded-GSI single-table design (see the
comments in `main.tf` for the per-entity key layout). Replaces the
CloudFormation template that previously lived at
`infrastructure/dynamodb/tables.json` (removed).

**Keep this module in its own state/root, separate from the app stacks**
(`backend/iac`, `frontend/iac`): it is the data store, and its lifecycle must
not be coupled to compute you destroy and recreate freely. Both DynamoDB
deletion protection and `lifecycle { prevent_destroy }` are enabled.

This is a **module** (no provider/backend blocks) — instantiate it from your
per-account pipeline root, e.g.:

```hcl
module "dynamodb" {
  source = "git::https://<host>/tmt.git//infrastructure/dynamodb/iac?ref=main"

  table_name = "ml-platform"
  tags       = { Environment = "prod" }
}
```

## Adopting an existing table (deployed from the old CFN template)

Do **not** let Terraform create a second table — import the existing one into
this module's state, then plan to confirm no replacement:

```bash
terraform import module.dynamodb.aws_dynamodb_table.this ml-platform
terraform plan   # expect no destructive changes; tag/PITR drift is fine to apply
```

If the table was created via the CloudFormation stack, delete the stack only
after importing, and rely on its `DeletionPolicy: Retain` (the stack deletion
leaves the table in place).

## Local development

Local dev does not use this module — `backend/scripts/create_tables.py`
creates the same schema against DynamoDB Local/moto (`DYNAMODB_ENDPOINT_URL`).
If you change the schema here, change it there too.
