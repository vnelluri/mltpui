"""Training job dispatch to EMR Serverless / SageMaker, with mock modes.

Also handles secure transit of the user's Snowflake OAuth token to the
compute job via AWS Secrets Manager: the token is stored under a
short-lived secret and only the secret ARN is passed to the job. In mock
mode a fake secret ARN is returned without writing anything.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from app.config import settings
from app.db.client import make_boto3_client
from app.db.models import JobStatus, Tenant, TrainingJob, utcnow_iso


class TenantNotProvisionedError(RuntimeError):
    """Raised when a job targets a tenant whose dataplane resources (EMR
    application / execution role) have not been provisioned yet."""


_TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
}


def _parse_iso(ts: str) -> datetime:
    cleaned = (ts or "").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class JobService:
    def __init__(self) -> None:
        self.emr_mock = settings.EMR_MOCK_MODE
        self.sagemaker_mock = settings.SAGEMAKER_MOCK_MODE
        self.snowflake_mock = settings.SNOWFLAKE_MOCK_MODE

    # ── Secrets Manager token transit ────────────────────────────────────
    def store_job_token(
        self, plaintext_token: str, job_id: str, tenant_id: str, expires_at: str
    ) -> str:
        """Store the Snowflake token in Secrets Manager, return its ARN.

        In Snowflake mock mode, returns a fake ARN and writes nothing.
        """
        if self.snowflake_mock:
            return f"mock-secret-arn/{uuid.uuid4()}"

        client = make_boto3_client(
            "secretsmanager", settings.SECRETS_MANAGER_ENDPOINT_URL
        )
        secret_name = f"{settings.SECRETS_MANAGER_JOB_TOKEN_PREFIX}{job_id}"
        secret_string = json.dumps(
            {
                "snowflake_token": plaintext_token,
                "expiresAt": expires_at,
                "tenantId": tenant_id,
            }
        )
        try:
            resp = client.create_secret(
                Name=secret_name,
                SecretString=secret_string,
                Description=f"Short-lived Snowflake token for job {job_id}",
            )
            return resp["ARN"]
        except client.exceptions.ResourceExistsException:
            resp = client.put_secret_value(
                SecretId=secret_name, SecretString=secret_string
            )
            return resp["ARN"]

    def delete_job_token(self, secret_arn: Optional[str]) -> None:
        """Delete a job token secret after the job completes/fails."""
        if not secret_arn or secret_arn.startswith("mock-secret-arn/"):
            return
        client = make_boto3_client(
            "secretsmanager", settings.SECRETS_MANAGER_ENDPOINT_URL
        )
        try:
            client.delete_secret(
                SecretId=secret_arn, ForceDeleteWithoutRecovery=True
            )
        except Exception:
            # Best-effort cleanup; never fail a request on secret deletion.
            pass

    # ── Submission ───────────────────────────────────────────────────────
    def submit(
        self,
        job: TrainingJob,
        tenant: Tenant,
        snowflake_secret_arn: Optional[str] = None,
    ) -> TrainingJob:
        """Dispatch the job to the correct compute backend, using the
        tenant's own EMR Serverless application and execution role."""
        if job.computeType == "emr_serverless":
            run_id = self.submit_emr_job(job, tenant, snowflake_secret_arn)
            job.emrJobRunId = run_id
        else:
            training_name = self.submit_sagemaker_job(job, tenant, snowflake_secret_arn)
            job.sagemakerTrainingJobName = training_name
        job.status = JobStatus.QUEUED.value
        job.snowflakeSecretArn = snowflake_secret_arn
        return job

    @staticmethod
    def _require_provisioned(tenant: Tenant, *fields: str) -> None:
        missing = [f for f in fields if not getattr(tenant, f)]
        if missing:
            raise TenantNotProvisionedError(
                f"Tenant '{tenant.tenantId}' has no {', '.join(missing)} — "
                "its dataplane resources are not provisioned yet."
            )

    def submit_emr_job(
        self, job: TrainingJob, tenant: Tenant, secret_arn: Optional[str]
    ) -> str:
        job.emrApplicationId = tenant.emrApplicationId
        if self.emr_mock:
            return f"mock-jr-{uuid.uuid4()}"

        self._require_provisioned(tenant, "emrApplicationId", "executionRoleArn")
        client = make_boto3_client("emr-serverless")
        spark_params = [f"--conf spark.executor.instances={job.maxExecutors or job.instanceCount}"]
        if job.driverMemory:
            spark_params.append(f"--conf spark.driver.memory={job.driverMemory}")
        if job.executorMemory:
            spark_params.append(f"--conf spark.executor.memory={job.executorMemory}")
        # Env vars carried via Spark config so the entrypoint can read them
        # from its process environment on both driver and executors.
        for key, value in self._job_env(job, secret_arn).items():
            spark_params.append(f"--conf spark.emr-serverless.driverEnv.{key}={value}")
            spark_params.append(f"--conf spark.executorEnv.{key}={value}")
        resp = client.start_job_run(
            applicationId=tenant.emrApplicationId,
            executionRoleArn=tenant.executionRoleArn,
            name=job.name,
            jobDriver={
                "sparkSubmit": {
                    "entryPoint": job.entryPointScript,
                    "sparkSubmitParameters": " ".join(spark_params),
                }
            },
            configurationOverrides={
                "monitoringConfiguration": {
                    "cloudWatchLoggingConfiguration": {"enabled": True}
                }
            },
            tags={
                "tenantId": job.tenantId,
                "jobId": job.jobId,
                **({"snowflakeSecretArn": secret_arn} if secret_arn else {}),
            },
        )
        return resp["jobRunId"]

    def submit_sagemaker_job(
        self, job: TrainingJob, tenant: Tenant, secret_arn: Optional[str]
    ) -> str:
        if self.sagemaker_mock:
            return f"mock-smj-{uuid.uuid4()}"

        self._require_provisioned(tenant, "executionRoleArn")
        if not settings.SAGEMAKER_TRAINING_IMAGE:
            raise RuntimeError(
                "SAGEMAKER_TRAINING_IMAGE is not configured — required for "
                "real SageMaker training job submission."
            )
        client = make_boto3_client("sagemaker")
        training_job_name = f"{job.name[:40]}-{uuid.uuid4().hex[:8]}"
        env = self._job_env(job, secret_arn)
        client.create_training_job(
            TrainingJobName=training_job_name,
            AlgorithmSpecification={
                "TrainingInputMode": "File",
                "TrainingImage": settings.SAGEMAKER_TRAINING_IMAGE,
            },
            RoleArn=tenant.executionRoleArn,
            HyperParameters={k: str(v) for k, v in job.hyperparameters.items()},
            Environment=env,
            OutputDataConfig={"S3OutputPath": job.s3OutputPath or ""},
            ResourceConfig={
                "InstanceType": job.instanceType or "ml.m5.xlarge",
                "InstanceCount": job.instanceCount,
                "VolumeSizeInGB": job.volumeSizeGb,
            },
            StoppingCondition={"MaxRuntimeInSeconds": 86400},
        )
        return training_job_name

    def _job_env(self, job: TrainingJob, secret_arn: Optional[str]) -> dict:
        env = {
            "ML_PLATFORM_JOB_ID": job.jobId,
            "ML_PLATFORM_TENANT_ID": job.tenantId,
        }
        if job.snowflakeDatabase:
            env["SNOWFLAKE_DATABASE"] = job.snowflakeDatabase
        if job.snowflakeSchema:
            env["SNOWFLAKE_SCHEMA"] = job.snowflakeSchema
        if job.snowflakeWarehouse:
            env["SNOWFLAKE_WAREHOUSE"] = job.snowflakeWarehouse
        if job.snowflakeTable:
            env["SNOWFLAKE_TABLE"] = job.snowflakeTable
        if job.snowflakeSql:
            env["SNOWFLAKE_CUSTOM_SQL"] = job.snowflakeSql
        if secret_arn:
            # Only the secret ARN is passed — never the plaintext token.
            env["SNOWFLAKE_TOKEN_SECRET_ARN"] = secret_arn
        return env

    # ── Status polling ───────────────────────────────────────────────────
    def live_status(self, job: TrainingJob) -> TrainingJob:
        """Return the job with its live status resolved.

        Terminal stored statuses are preserved. For non-terminal mock jobs a
        synthetic progression is computed purely from the ``createdAt`` diff:
        queued (<5s) → running (<30s) → succeeded (>=30s).
        """
        if job.status in _TERMINAL_STATUSES:
            return job

        is_mock = (
            job.computeType == "emr_serverless" and self.emr_mock
        ) or (job.computeType == "sagemaker" and self.sagemaker_mock)

        if is_mock:
            elapsed = (
                datetime.now(timezone.utc) - _parse_iso(job.createdAt)
            ).total_seconds()
            if elapsed < 5:
                job.status = JobStatus.QUEUED.value
            elif elapsed < 30:
                job.status = JobStatus.RUNNING.value
                if not job.startedAt:
                    job.startedAt = utcnow_iso()
            else:
                job.status = JobStatus.SUCCEEDED.value
                job.startedAt = job.startedAt or job.createdAt
                job.completedAt = job.completedAt or utcnow_iso()
                job.durationSeconds = int(elapsed)
                # Terminal: the short-lived Snowflake token secret is no
                # longer needed — clean it up (not only on cancel).
                self.delete_job_token(job.snowflakeSecretArn)
            return job

        return self._poll_real_status(job)

    @staticmethod
    def _emr_application_id(job: TrainingJob) -> Optional[str]:
        # Legacy job records predate per-tenant applications and fall back to
        # the (deprecated) platform-wide setting.
        return job.emrApplicationId or settings.EMR_SERVERLESS_APPLICATION_ID

    def _poll_real_status(self, job: TrainingJob) -> TrainingJob:
        previous_status = job.status
        try:
            if job.computeType == "emr_serverless" and job.emrJobRunId:
                client = make_boto3_client("emr-serverless")
                resp = client.get_job_run(
                    applicationId=self._emr_application_id(job),
                    jobRunId=job.emrJobRunId,
                )
                state = resp["jobRun"]["state"]
                job.status = self._map_emr_state(state)
            elif job.computeType == "sagemaker" and job.sagemakerTrainingJobName:
                client = make_boto3_client("sagemaker")
                resp = client.describe_training_job(
                    TrainingJobName=job.sagemakerTrainingJobName
                )
                job.status = self._map_sagemaker_state(resp["TrainingJobStatus"])
        except Exception:
            # If polling fails, keep the last known status.
            pass
        if job.status in _TERMINAL_STATUSES and previous_status not in _TERMINAL_STATUSES:
            if job.status != JobStatus.CANCELLED.value:
                job.completedAt = job.completedAt or utcnow_iso()
            # Terminal: clean up the short-lived Snowflake token secret.
            self.delete_job_token(job.snowflakeSecretArn)
        return job

    @staticmethod
    def _map_emr_state(state: str) -> str:
        mapping = {
            "SUBMITTED": JobStatus.QUEUED.value,
            "PENDING": JobStatus.QUEUED.value,
            "SCHEDULED": JobStatus.QUEUED.value,
            "RUNNING": JobStatus.RUNNING.value,
            "SUCCESS": JobStatus.SUCCEEDED.value,
            "FAILED": JobStatus.FAILED.value,
            "CANCELLED": JobStatus.CANCELLED.value,
            "CANCELLING": JobStatus.CANCELLED.value,
        }
        return mapping.get(state, JobStatus.RUNNING.value)

    @staticmethod
    def _map_sagemaker_state(state: str) -> str:
        mapping = {
            "InProgress": JobStatus.RUNNING.value,
            "Completed": JobStatus.SUCCEEDED.value,
            "Failed": JobStatus.FAILED.value,
            "Stopping": JobStatus.CANCELLED.value,
            "Stopped": JobStatus.CANCELLED.value,
        }
        return mapping.get(state, JobStatus.RUNNING.value)

    # ── Cancellation ─────────────────────────────────────────────────────
    def cancel(self, job: TrainingJob) -> TrainingJob:
        is_mock = (
            job.computeType == "emr_serverless" and self.emr_mock
        ) or (job.computeType == "sagemaker" and self.sagemaker_mock)
        if not is_mock:
            try:
                if job.computeType == "emr_serverless" and job.emrJobRunId:
                    client = make_boto3_client("emr-serverless")
                    client.cancel_job_run(
                        applicationId=self._emr_application_id(job),
                        jobRunId=job.emrJobRunId,
                    )
                elif job.computeType == "sagemaker" and job.sagemakerTrainingJobName:
                    client = make_boto3_client("sagemaker")
                    client.stop_training_job(
                        TrainingJobName=job.sagemakerTrainingJobName
                    )
            except Exception:
                pass
        job.status = JobStatus.CANCELLED.value
        job.completedAt = utcnow_iso()
        # Clean up any Snowflake token secret.
        self.delete_job_token(job.snowflakeSecretArn)
        return job

    # ── Logs ─────────────────────────────────────────────────────────────
    def log_stream_url(self, job: TrainingJob) -> str:
        if (job.computeType == "emr_serverless" and self.emr_mock) or (
            job.computeType == "sagemaker" and self.sagemaker_mock
        ):
            return f"https://mock-cloudwatch.local/log-stream/{job.jobId}"

        region = settings.AWS_REGION
        if job.computeType == "sagemaker":
            group = "/aws/sagemaker/TrainingJobs"
            stream = job.sagemakerTrainingJobName or job.jobId
        else:
            group = f"/aws/emr-serverless/{self._emr_application_id(job)}"
            stream = job.emrJobRunId or job.jobId
        return (
            f"https://{region}.console.aws.amazon.com/cloudwatch/home?region="
            f"{region}#logsV2:log-groups/log-group/"
            f"{group.replace('/', '$252F')}/log-events/{stream}"
        )


job_service = JobService()
