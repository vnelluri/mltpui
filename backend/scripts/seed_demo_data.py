#!/usr/bin/env python
"""Seed realistic demo data for local development.

Idempotent: each item is created with a ``attribute_not_exists`` condition
via its repository, so re-running this script is always safe — existing
items are skipped rather than duplicated. Uses well-known IDs (e.g.
``tenant-risk-analytics``) so the same demo data is reproducible across runs
and documented in the README's role-switching table.
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from botocore.exceptions import ClientError  # noqa: E402

from app.db.models import (  # noqa: E402
    AuditEvent,
    Experiment,
    ExperimentRun,
    FeatureView,
    GovernanceReview,
    GroupMapping,
    JobStatus,
    ModelStage,
    ModelVersion,
    ProvisioningStatus,
    ReviewDecision,
    Tenant,
    TenantStatus,
    TrainingJob,
    utcnow_iso,
)
from app.config import settings  # noqa: E402
from app.db.client import make_boto3_client  # noqa: E402
from app.db.repositories.audit_repo import AuditRepository  # noqa: E402
from app.db.repositories.experiment_repo import ExperimentRepository  # noqa: E402
from app.db.repositories.feature_view_repo import FeatureViewRepository  # noqa: E402
from app.db.repositories.governance_repo import GovernanceRepository  # noqa: E402
from app.db.repositories.group_mapping_repo import GroupMappingRepository  # noqa: E402
from app.db.repositories.job_repo import JobRepository  # noqa: E402
from app.db.repositories.model_repo import ModelRepository  # noqa: E402
from app.db.repositories.tenant_repo import TenantRepository  # noqa: E402

RNG = random.Random(42)

created_counts = {
    "tenants": 0,
    "groupMappings": 0,
    "jobs": 0,
    "experiments": 0,
    "runs": 0,
    "models": 0,
    "reviews": 0,
    "featureViews": 0,
    "auditEvents": 0,
    "s3Objects": 0,
}
skipped_counts = {k: 0 for k in created_counts}


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _try_create(kind: str, fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
        created_counts[kind] += 1
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            skipped_counts[kind] += 1
            return False
        raise


def _demo_tenant(
    tenant_id: str, name: str, quota: int, frameworks: list[str]
) -> Tenant:
    # Mirrors what TenantProvisioningService._mock_provision fills in for
    # tenants created through the API in local dev: per-tenant mock EMR
    # application + execution role, provisioning already "active".
    return Tenant(
        tenantId=tenant_id,
        name=name,
        status=TenantStatus.ACTIVE.value,
        createdBy="system-seed",
        emrApplicationId=f"mock-emr-app-{tenant_id}",
        executionRoleArn=f"arn:aws:iam::000000000000:role/mock-{tenant_id}-exec",
        provisioningStatus=ProvisioningStatus.ACTIVE.value,
        s3BucketName=f"s3://ml-platform-artifacts/{tenant_id}/",
        computeQuotaVcpuHours=quota,
        allowedFrameworks=frameworks,
    )


def seed_tenants(repo: TenantRepository) -> None:
    tenants = [
        _demo_tenant(
            "tenant-risk-analytics",
            "Risk Analytics",
            2000,
            ["pytorch", "tensorflow", "sklearn", "xgboost"],
        ),
        _demo_tenant(
            "tenant-fraud-detection",
            "Fraud Detection",
            1500,
            ["pytorch", "sklearn", "xgboost"],
        ),
        _demo_tenant("tenant-compliance", "Compliance", 500, ["sklearn"]),
    ]
    for t in tenants:
        _try_create("tenants", repo.create, t)


GROUP_PLATFORM_ADMIN = "aaaaaaaa-0001-0001-0001-000000000001"
GROUP_MRM = "aaaaaaaa-0002-0001-0001-000000000002"
GROUP_TENANTADMIN_RA = "aaaaaaaa-0003-0001-0001-000000000003"
GROUP_TENANTADMIN_FD = "aaaaaaaa-0004-0001-0001-000000000004"
GROUP_DATASCIENTIST_RA = "aaaaaaaa-0005-0001-0001-000000000005"
GROUP_DATASCIENTIST_FD = "aaaaaaaa-0006-0001-0001-000000000006"


def seed_group_mappings(repo: GroupMappingRepository) -> None:
    mappings = [
        GroupMapping(
            groupId=GROUP_PLATFORM_ADMIN,
            role="PlatformAdmin",
            tenantId=None,
            description="ML-PlatformAdmins",
            createdBy="system-seed",
        ),
        GroupMapping(
            groupId=GROUP_MRM,
            role="MRM",
            tenantId=None,
            description="ML-ModelRiskManagement",
            createdBy="system-seed",
        ),
        GroupMapping(
            groupId=GROUP_TENANTADMIN_RA,
            role="TenantAdmin",
            tenantId="tenant-risk-analytics",
            description="ML-RiskAnalytics-TenantAdmins",
            createdBy="system-seed",
        ),
        GroupMapping(
            groupId=GROUP_TENANTADMIN_FD,
            role="TenantAdmin",
            tenantId="tenant-fraud-detection",
            description="ML-FraudDetection-TenantAdmins",
            createdBy="system-seed",
        ),
        GroupMapping(
            groupId=GROUP_DATASCIENTIST_RA,
            role="DataScientist",
            tenantId="tenant-risk-analytics",
            description="ML-RiskAnalytics-DataScientists",
            createdBy="system-seed",
        ),
        GroupMapping(
            groupId=GROUP_DATASCIENTIST_FD,
            role="DataScientist",
            tenantId="tenant-fraud-detection",
            description="ML-FraudDetection-DataScientists",
            createdBy="system-seed",
        ),
    ]
    for gm in mappings:
        _try_create("groupMappings", repo.create, gm)


# Well-known demo user IDs. There is no UserProfile/user directory table —
# Entra ID + GroupMapping is the sole source of truth for identity, resolved
# fresh on every request (see app/dependencies.py). These IDs exist here only
# as attribution values (createdBy/userId/registeredBy/reviewedBy) on the
# other seeded entities below, matching what each demo user's real Entra
# login would resolve to via the group mappings seeded above.
USER_PLATFORM_ADMIN = "user-platformadmin-01"
USER_MRM = "user-mrm-01"
USER_TENANTADMIN_RA = "user-tenantadmin-ra-01"
USER_TENANTADMIN_FD = "user-tenantadmin-fd-01"
USER_DS_RA_1 = "user-ds-ra-01"
USER_DS_RA_2 = "user-ds-ra-02"
USER_DS_FD_1 = "user-ds-fd-01"
USER_DS_FD_2 = "user-ds-fd-02"


def seed_jobs(repo: JobRepository) -> list[TrainingJob]:
    now = datetime.now(timezone.utc)
    specs = [
        ("queued", None, None),
        ("running", None, None),
        ("succeeded", 420, 5),
        ("succeeded", 900, 5),
        ("succeeded", 1740, 5),
        ("succeeded", 360, 5),
        ("succeeded", 2100, 5),
        ("failed", 120, 3),
        ("failed", 45, 3),
        ("cancelled", 200, 2),
    ]
    tenants_users = [
        ("tenant-risk-analytics", USER_DS_RA_1),
        ("tenant-fraud-detection", USER_DS_FD_1),
    ]
    frameworks = ["pytorch", "tensorflow", "sklearn", "xgboost"]
    jobs: list[TrainingJob] = []
    for i, (job_status, duration, hours_ago_offset) in enumerate(specs):
        tenant_id, user_id = tenants_users[i % 2]
        created_at = now - timedelta(hours=(i + 1) * 6)
        compute_type = "emr_serverless" if i % 2 == 0 else "sagemaker"
        job = TrainingJob(
            jobId=f"demo-job-{i + 1:02d}",
            tenantId=tenant_id,
            userId=user_id,
            name=f"{frameworks[i % 4]}-training-run-{i + 1}",
            status=job_status,
            framework=frameworks[i % 4],
            entryPointScript=f"s3://ml-platform-artifacts/{tenant_id}/scripts/train.py",
            s3InputPath=f"s3://ml-platform-artifacts/{tenant_id}/data/input/",
            s3OutputPath=f"s3://ml-platform-artifacts/{tenant_id}/models/run-{i + 1}/",
            computeType=compute_type,
            emrJobRunId=f"mock-jr-demo-{i + 1:02d}" if compute_type == "emr_serverless" else None,
            sagemakerTrainingJobName=f"mock-smj-demo-{i + 1:02d}" if compute_type == "sagemaker" else None,
            hyperparameters={"learning_rate": 0.001, "batch_size": 64, "epochs": 10},
            createdAt=_iso(created_at),
            startedAt=_iso(created_at + timedelta(seconds=5)) if duration else None,
            completedAt=_iso(created_at + timedelta(seconds=duration)) if duration else None,
            durationSeconds=duration,
            instanceType="ml.m5.xlarge" if compute_type == "sagemaker" else None,
            instanceCount=RNG.choice([1, 2, 4]),
            volumeSizeGb=30,
        )
        jobs.append(job)
        _try_create("jobs", repo.create, job)
    return jobs


def seed_experiments_and_runs(
    repo: ExperimentRepository,
) -> tuple[dict[str, tuple[str, str]], dict[str, list[ExperimentRun]]]:
    now = datetime.now(timezone.utc)
    experiment_specs = [
        ("demo-exp-risk-scoring", "tenant-risk-analytics", "Credit Risk Scoring", USER_DS_RA_1),
        ("demo-exp-fraud-baseline", "tenant-fraud-detection", "Fraud Detection Baseline", USER_DS_FD_1),
        ("demo-exp-churn", "tenant-risk-analytics", "Customer Churn Prediction", USER_DS_RA_2),
    ]

    all_runs: dict[str, list[ExperimentRun]] = {}
    for exp_id, tenant_id, name, created_by in experiment_specs:
        exp = Experiment(
            experimentId=exp_id,
            tenantId=tenant_id,
            name=name,
            description=f"{name} — demo experiment seeded for local development.",
            createdBy=created_by,
            tags={"team": tenant_id.replace("tenant-", "")},
        )
        _try_create("experiments", repo.create_experiment, exp)

        runs = []
        for r in range(8):
            run_id = f"{exp_id}-run-{r + 1:02d}"
            start = now - timedelta(days=r, hours=r)
            val_loss_curve = [round(1.2 - i * (1.0 / 12), 4) for i in range(10)]
            auc = round(0.85 + RNG.random() * 0.12, 4)
            f1 = round(0.80 + RNG.random() * 0.15, 4)
            psi = round(0.01 + RNG.random() * 0.04, 4)
            run = ExperimentRun(
                runId=run_id,
                experimentId=exp_id,
                tenantId=tenant_id,
                jobId=None,
                status=JobStatus.SUCCEEDED.value,
                startTime=_iso(start),
                endTime=_iso(start + timedelta(minutes=45)),
                params={
                    "learning_rate": round(RNG.choice([0.01, 0.005, 0.001, 0.0005]), 5),
                    "batch_size": RNG.choice([32, 64, 128]),
                    "max_depth": RNG.choice([4, 6, 8]),
                },
                metrics={
                    "auc": auc,
                    "f1": f1,
                    "psi": psi,
                    "val_loss": val_loss_curve[-1],
                },
                tags={"val_loss_curve": val_loss_curve, "framework": RNG.choice(["pytorch", "xgboost", "sklearn"])},
                artifactUri=f"s3://ml-platform-artifacts/{tenant_id}/experiments/{exp_id}/{run_id}/",
            )
            runs.append(run)
            _try_create("runs", repo.create_run, run)
        all_runs[exp_id] = runs

    # Pick a handful of high-scoring runs to back the demo ModelVersions.
    best = {
        "risk-score-model": ("demo-exp-risk-scoring", "tenant-risk-analytics"),
        "fraud-detector": ("demo-exp-fraud-baseline", "tenant-fraud-detection"),
        "churn-predictor": ("demo-exp-churn", "tenant-risk-analytics"),
    }
    return best, all_runs


def seed_models(
    repo: ModelRepository,
    best: dict[str, tuple[str, str]],
    all_runs: dict[str, list[ExperimentRun]],
) -> dict[tuple[str, int], tuple[str, str]]:
    stage_plan = [
        ("risk-score-model", 1, ModelStage.NONE.value),
        ("risk-score-model", 2, ModelStage.STAGING.value),
        ("fraud-detector", 1, ModelStage.NONE.value),
        ("fraud-detector", 2, ModelStage.STAGING.value),
        ("fraud-detector", 3, ModelStage.PRODUCTION.value),
        ("churn-predictor", 1, ModelStage.ARCHIVED.value),
    ]
    model_ids = {}
    for name, version, stage in stage_plan:
        exp_id, tenant_id = best[name]
        run = all_runs[exp_id][version % len(all_runs[exp_id])]
        model_id = f"demo-model-{name}-v{version}"
        model_ids[(name, version)] = (model_id, tenant_id)
        mv = ModelVersion(
            modelId=model_id,
            tenantId=tenant_id,
            name=name,
            version=version,
            stage=stage,
            runId=run.runId,
            framework=run.tags.get("framework", "xgboost"),
            artifactUri=run.artifactUri,
            description=f"{name} version {version}, seeded for local development.",
            inputSchema={"features": ["feature_1", "feature_2", "feature_3"]},
            outputSchema={"prediction": "float", "probability": "float"},
            hasExplainer=version % 2 == 0,
            driftBaselineUri=f"{run.artifactUri}drift_baseline.json" if stage != "None" else None,
            registeredBy=USER_DS_RA_1 if tenant_id == "tenant-risk-analytics" else USER_DS_FD_1,
            promotedAt=utcnow_iso() if stage in {"Staging", "Production", "Archived"} else None,
            promotedBy=USER_TENANTADMIN_RA if tenant_id == "tenant-risk-analytics" else USER_TENANTADMIN_FD,
        )
        _try_create("models", repo.create, mv)
    return model_ids


def seed_governance_reviews(
    repo: GovernanceRepository, model_ids: dict[tuple[str, int], tuple[str, str]]
) -> None:
    prod_model_id, prod_tenant = model_ids[("fraud-detector", 3)]
    staging_model_id, staging_tenant = model_ids[("risk-score-model", 2)]

    approved = GovernanceReview(
        reviewId="demo-review-approved-01",
        modelId=prod_model_id,
        tenantId=prod_tenant,
        modelName="fraud-detector",
        modelVersion=3,
        reviewedBy=USER_MRM,
        decision=ReviewDecision.APPROVED.value,
        comments="Model meets fairness and stability thresholds. Approved for Production.",
        conditions="Re-review required after 90 days or a PSI drift alert.",
        reviewedAt=utcnow_iso(),
        expiresAt=_iso(datetime.now(timezone.utc) + timedelta(days=90)),
    )
    _try_create("reviews", repo.create, approved)

    pending = GovernanceReview(
        reviewId="demo-review-pending-01",
        modelId=staging_model_id,
        tenantId=staging_tenant,
        modelName="risk-score-model",
        modelVersion=2,
        reviewedBy=None,
        decision=ReviewDecision.PENDING.value,
        comments=None,
        conditions=None,
    )
    _try_create("reviews", repo.create, pending)


def seed_feature_views(repo: FeatureViewRepository) -> None:
    """Feature Store preview demo data — reuses the same table/column names
    as the mock Snowflake catalog (snowflake_service.MOCK_TABLE_SCHEMAS) so
    the story is internally consistent: these feature views describe the
    exact same tables you can browse in the Snowflake tab of the job wizard.
    """
    views = [
        FeatureView(
            featureViewId="demo-fv-customer-risk",
            tenantId="tenant-risk-analytics",
            name="customer_risk_features",
            description="Customer-level features used by the Credit Risk Scoring model.",
            entityColumn="customer_id",
            features=[
                {"name": "age", "dtype": "int64"},
                {"name": "tenure_months", "dtype": "int64"},
                {"name": "credit_score", "dtype": "int64"},
                {"name": "avg_balance", "dtype": "float"},
                {"name": "risk_segment", "dtype": "string"},
            ],
            sourceTable="PROD_DB.ML_FEATURES.CUSTOMER_FEATURES",
            experimentId="demo-exp-risk-scoring",
            createdBy=USER_DS_RA_1,
            lastMaterializedAt=utcnow_iso(),
        ),
        FeatureView(
            featureViewId="demo-fv-fraud-transaction",
            tenantId="tenant-fraud-detection",
            name="fraud_transaction_features",
            description="Transaction-level features used by the Fraud Detection Baseline model.",
            entityColumn="transaction_id",
            features=[
                {"name": "amount", "dtype": "float"},
                {"name": "merchant_category", "dtype": "string"},
                {"name": "transaction_date", "dtype": "timestamp"},
                {"name": "is_fraud", "dtype": "bool"},
            ],
            sourceTable="PROD_DB.ML_FEATURES.TRANSACTION_FEATURES",
            experimentId="demo-exp-fraud-baseline",
            createdBy=USER_DS_FD_1,
        ),
    ]
    for fv in views:
        _try_create("featureViews", repo.create, fv)


def seed_audit_events(repo: AuditRepository) -> None:
    now = datetime.now(timezone.utc)
    actions = [
        ("tenant.create", "Tenant", "tenant-risk-analytics", USER_PLATFORM_ADMIN, None),
        ("tenant.create", "Tenant", "tenant-fraud-detection", USER_PLATFORM_ADMIN, None),
        ("group_mapping.create", "GroupMapping", GROUP_DATASCIENTIST_RA, USER_PLATFORM_ADMIN, None),
        ("job.submit", "TrainingJob", "demo-job-01", USER_DS_RA_1, "tenant-risk-analytics"),
        ("job.submit", "TrainingJob", "demo-job-02", USER_DS_FD_1, "tenant-fraud-detection"),
        ("job.submit", "TrainingJob", "demo-job-03", USER_DS_RA_1, "tenant-risk-analytics"),
        ("job.cancel", "TrainingJob", "demo-job-10", USER_DS_RA_1, "tenant-risk-analytics"),
        ("experiment.create", "Experiment", "demo-exp-risk-scoring", USER_DS_RA_1, "tenant-risk-analytics"),
        ("experiment.create", "Experiment", "demo-exp-fraud-baseline", USER_DS_FD_1, "tenant-fraud-detection"),
        ("model.register", "ModelVersion", "risk-score-model/2", USER_DS_RA_1, "tenant-risk-analytics"),
        ("model.register", "ModelVersion", "fraud-detector/3", USER_DS_FD_1, "tenant-fraud-detection"),
        ("model.stage_transition", "ModelVersion", "fraud-detector/3", USER_TENANTADMIN_FD, "tenant-fraud-detection"),
        ("governance.review_decision", "GovernanceReview", "demo-review-approved-01", USER_MRM, "tenant-fraud-detection"),
        ("notebook.launch", "NotebookSession", "demo-nb-01", USER_DS_RA_2, "tenant-risk-analytics"),
        ("snowflake.connect", "SnowflakeTokenCache", USER_DS_FD_2, USER_DS_FD_2, "tenant-fraud-detection"),
    ]
    for i, (action, resource_type, resource_id, user_id, tenant_id) in enumerate(actions):
        event = AuditEvent(
            eventId=f"demo-audit-{i + 1:02d}",
            tenantId=tenant_id,
            userId=user_id,
            action=action,
            resourceType=resource_type,
            resourceId=resource_id,
            timestamp=_iso(now - timedelta(days=RNG.uniform(0, 7), hours=RNG.uniform(0, 23))),
            ipAddress="127.0.0.1",
            userAgent="seed_demo_data.py",
            details={"seed": True},
        )
        _try_create("auditEvents", repo.create, event)


_DEMO_S3_FILES: dict[str, list[tuple[str, bytes]]] = {
    "tenant-risk-analytics": [
        ("scripts/train.py", b"# Demo training entrypoint for Risk Analytics\nprint('training risk model')\n"),
        (
            "data/input/credit_features_sample.csv",
            b"customer_id,credit_score,income,default\nC-100001,712,54000,0\nC-100002,655,38000,1\n",
        ),
        ("models/risk-score-model/v2/model.pkl", b"placeholder-binary-model-artifact"),
    ],
    "tenant-fraud-detection": [
        ("scripts/train.py", b"# Demo training entrypoint for Fraud Detection\nprint('training fraud model')\n"),
        (
            "data/input/transactions_sample.csv",
            b"transaction_id,amount,merchant_category,is_fraud\nT-500001,124.50,grocery,0\nT-500002,980.10,electronics,1\n",
        ),
        ("models/fraud-detector/v3/model.pkl", b"placeholder-binary-model-artifact"),
    ],
    "tenant-compliance": [
        ("scripts/train.py", b"# Demo training entrypoint for Compliance\nprint('training compliance model')\n"),
    ],
}


def _ensure_bucket(client) -> None:
    """Create the shared artifacts bucket if it doesn't exist yet.

    Normally handled by the tenant provisioning service (mock mode) when
    tenants are created via ``POST /tenants``, but this script writes tenants
    directly to DynamoDB, bypassing that path — so the bucket needs creating
    here too.
    """
    bucket = settings.S3_ARTIFACTS_BUCKET
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        if settings.AWS_REGION == "us-east-1":
            client.create_bucket(Bucket=bucket)
        else:
            client.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": settings.AWS_REGION},
            )


def seed_s3_objects() -> None:
    """Seed a few demo files per tenant so the S3 browser has content to show."""
    client = make_boto3_client("s3", settings.S3_ENDPOINT_URL)
    _ensure_bucket(client)
    bucket = settings.S3_ARTIFACTS_BUCKET
    for tenant_id, files in _DEMO_S3_FILES.items():
        for rel_key, body in files:
            key = f"{tenant_id}/{rel_key}"
            try:
                client.head_object(Bucket=bucket, Key=key)
                skipped_counts["s3Objects"] += 1
                continue
            except ClientError as exc:
                if exc.response["Error"]["Code"] not in {"404", "NoSuchKey"}:
                    raise
            client.put_object(Bucket=bucket, Key=key, Body=body)
            created_counts["s3Objects"] += 1


def main() -> None:
    tenant_repo = TenantRepository()
    group_repo = GroupMappingRepository()
    job_repo = JobRepository()
    exp_repo = ExperimentRepository()
    model_repo = ModelRepository()
    gov_repo = GovernanceRepository()
    audit_repo = AuditRepository()
    feature_view_repo = FeatureViewRepository()

    print("Seeding demo data (idempotent — safe to re-run) ...")
    seed_tenants(tenant_repo)
    seed_group_mappings(group_repo)
    seed_jobs(job_repo)
    best, all_runs = seed_experiments_and_runs(exp_repo)
    model_ids = seed_models(model_repo, best, all_runs)
    seed_governance_reviews(gov_repo, model_ids)
    seed_feature_views(feature_view_repo)
    seed_audit_events(audit_repo)
    seed_s3_objects()

    print("\nSummary")
    print("-------")
    header = f"{'Entity':<14}{'Created':>10}{'Already existed':>18}"
    print(header)
    print("-" * len(header))
    for key in created_counts:
        print(f"{key:<14}{created_counts[key]:>10}{skipped_counts[key]:>18}")
    print("\n✔ Demo data ready.")
    print(
        "  Tenants:        Risk Analytics · Fraud Detection · Compliance\n"
        "  Group mappings: 6 (see backend/scripts/seed_demo_data.py — identity/role/\n"
        "                  tenant come from Entra + GroupMapping, no local user directory)"
    )


if __name__ == "__main__":
    main()
