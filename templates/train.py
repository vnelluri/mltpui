"""Training-script template for the ML Training Platform.

Copy this file, fill in the TRAIN section, upload it to your tenant's S3
prefix, and submit a job pointing `entryPointScript` at it. It runs
unchanged on both compute backends (EMR Serverless / SageMaker training
jobs) and uses only boto3 + the standard library for the platform contract;
pyspark and the Snowflake connectors are imported lazily where needed.

── The contract (what the platform injects) ────────────────────────────────

Environment variables:
    ML_PLATFORM_JOB_ID            e.g. "job-0042"
    ML_PLATFORM_TENANT_ID         the tenant this run belongs to
    ML_PLATFORM_EXPERIMENT_ID     experiment holding this run
    ML_PLATFORM_RUN_ID            e.g. "run-0007" — the row your metrics land on
    ML_PLATFORM_API_URL           platform API base URL (absent in local dev)
    ML_PLATFORM_JOB_SECRET_ARN    Secrets Manager ARN of the per-job secret
    ML_PLATFORM_S3_INPUT_PATH     input data location (if set at submission)
    ML_PLATFORM_S3_OUTPUT_PATH    where the trained artifact must be written
    AS_OF_DATE                    data snapshot date, YYYY-MM-DD (backfills
                                  re-submit the same job with a different date)
    SNOWFLAKE_DATABASE / SNOWFLAKE_SCHEMA / SNOWFLAKE_WAREHOUSE /
    SNOWFLAKE_TABLE               set when the job uses a Snowflake source

Per-job secret (JSON at ML_PLATFORM_JOB_SECRET_ARN — read it, never log it):
    run_token                     "mlrt_…" bearer token for the platform API,
                                  scoped to exactly this run, TTL ~26h
    experimentId / runId / tenantId
    snowflake_token               short-lived (~1h) OAuth token — consume it
                                  for the INITIAL data read, first thing
    snowflakeExpiresAt            its expiry (ISO-8601)
    snowflakeSql                  custom SQL chosen at submission (optional).
                                  NOTE: SQL travels here, NOT in an env var —
                                  the old SNOWFLAKE_CUSTOM_SQL env is gone.

Platform API (Authorization: Bearer <run_token>):
    PUT {API}/experiments/{exp}/runs/{run}/metrics   {"metrics": {...}}
    PUT {API}/experiments/{exp}/runs/{run}/params    {"params":  {...}}
    PUT {API}/experiments/{exp}/runs/{run}/tags      {"tags":    {...}}

Custom SQL may contain the literal placeholder {{AS_OF_DATE}}; this template
substitutes the job's AS_OF_DATE into it, so a cloned/backfilled job reruns
the same query against a different snapshot date.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("train")

# Org-specific: your Snowflake account locator (not injected by the platform).
SNOWFLAKE_ACCOUNT = os.environ.get("SNOWFLAKE_ACCOUNT", "<your-account>")


# ── Job context ─────────────────────────────────────────────────────────────
@dataclass
class JobContext:
    job_id: str
    tenant_id: str
    experiment_id: Optional[str]
    run_id: Optional[str]
    api_url: Optional[str]
    as_of_date: Optional[str]
    s3_input_path: Optional[str]
    s3_output_path: Optional[str]
    snowflake_database: Optional[str]
    snowflake_schema: Optional[str]
    snowflake_warehouse: Optional[str]
    snowflake_table: Optional[str]
    secret: Dict[str, Any] = field(default_factory=dict, repr=False)  # never print


def load_context() -> JobContext:
    env = os.environ.get
    secret: Dict[str, Any] = {}
    secret_arn = env("ML_PLATFORM_JOB_SECRET_ARN")
    if secret_arn:
        import boto3  # present on EMR Serverless and SageMaker images

        resp = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
        secret = json.loads(resp["SecretString"])
    return JobContext(
        job_id=env("ML_PLATFORM_JOB_ID", "unknown"),
        tenant_id=env("ML_PLATFORM_TENANT_ID", "unknown"),
        experiment_id=env("ML_PLATFORM_EXPERIMENT_ID") or secret.get("experimentId"),
        run_id=env("ML_PLATFORM_RUN_ID") or secret.get("runId"),
        api_url=env("ML_PLATFORM_API_URL"),
        as_of_date=env("AS_OF_DATE"),
        s3_input_path=env("ML_PLATFORM_S3_INPUT_PATH"),
        s3_output_path=env("ML_PLATFORM_S3_OUTPUT_PATH"),
        snowflake_database=env("SNOWFLAKE_DATABASE"),
        snowflake_schema=env("SNOWFLAKE_SCHEMA"),
        snowflake_warehouse=env("SNOWFLAKE_WAREHOUSE"),
        snowflake_table=env("SNOWFLAKE_TABLE"),
        secret=secret,
    )


# ── Platform run logging (metrics / params / tags) ──────────────────────────
class PlatformRun:
    """Logs to this run's row in the platform. Best-effort by design: a
    logging hiccup must never kill hours of training, so failures warn and
    continue. Falls back to no-ops when the API URL or token is absent
    (local dev / mock mode)."""

    def __init__(self, ctx: JobContext) -> None:
        token = ctx.secret.get("run_token")
        self._enabled = bool(ctx.api_url and token and ctx.experiment_id and ctx.run_id)
        if not self._enabled:
            log.info("Platform run logging disabled (no API URL / run token).")
            return
        self._base = (
            f"{ctx.api_url.rstrip('/')}/experiments/{ctx.experiment_id}"
            f"/runs/{ctx.run_id}"
        )
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def log_metrics(self, metrics: Dict[str, Any]) -> None:
        self._put("metrics", {"metrics": metrics})

    def log_params(self, params: Dict[str, Any]) -> None:
        self._put("params", {"params": params})

    def log_tags(self, tags: Dict[str, Any]) -> None:
        self._put("tags", {"tags": tags})

    def _put(self, kind: str, payload: Dict[str, Any]) -> None:
        if not self._enabled:
            return
        req = urllib.request.Request(
            f"{self._base}/{kind}",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers,
            method="PUT",
        )
        for attempt in (1, 2, 3):
            try:
                with urllib.request.urlopen(req, timeout=15):
                    return
            except (urllib.error.URLError, OSError) as exc:
                log.warning("log %s attempt %d failed: %s", kind, attempt, exc)
        log.warning("Giving up logging %s — training continues.", kind)


# ── Snowflake source ────────────────────────────────────────────────────────
def resolve_sql(ctx: JobContext) -> Optional[str]:
    """The query for this run: custom SQL from the job secret if provided,
    otherwise a full read of the configured table for AS_OF_DATE."""
    sql = ctx.secret.get("snowflakeSql")
    if sql:
        return sql.replace("{{AS_OF_DATE}}", ctx.as_of_date or "")
    if ctx.snowflake_table:
        query = f"SELECT * FROM {ctx.snowflake_table}"
        if ctx.as_of_date:
            query += f" WHERE AS_OF_DATE = '{ctx.as_of_date}'"
        return query
    return None


def read_snowflake_spark(spark, ctx: JobContext):
    """Read the Snowflake source as a Spark DataFrame (EMR Serverless).

    Requires the spark-snowflake connector on the job's classpath. Do this
    FIRST — the OAuth token in the secret lives ~1 hour from submission.
    """
    sql = resolve_sql(ctx)
    if not sql:
        raise RuntimeError("Job has no Snowflake source configured.")
    return (
        spark.read.format("snowflake")
        .options(
            sfURL=f"{SNOWFLAKE_ACCOUNT}.snowflakecomputing.com",
            sfDatabase=ctx.snowflake_database,
            sfSchema=ctx.snowflake_schema,
            sfWarehouse=ctx.snowflake_warehouse,
            sfAuthenticator="oauth",
            sfToken=ctx.secret["snowflake_token"],
        )
        .option("query", sql)
        .load()
    )


def read_snowflake_pandas(ctx: JobContext):
    """Read the Snowflake source as a pandas DataFrame (SageMaker).

    Requires snowflake-connector-python[pandas] in the training image.
    """
    import snowflake.connector

    sql = resolve_sql(ctx)
    if not sql:
        raise RuntimeError("Job has no Snowflake source configured.")
    conn = snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT,
        authenticator="oauth",
        token=ctx.secret["snowflake_token"],
        database=ctx.snowflake_database,
        schema=ctx.snowflake_schema,
        warehouse=ctx.snowflake_warehouse,
    )
    try:
        return conn.cursor().execute(sql).fetch_pandas_all()
    finally:
        conn.close()


# ── Artifact output ─────────────────────────────────────────────────────────
def save_artifact(local_path: str, ctx: JobContext) -> str:
    """Persist the trained model and return the URI to register.

    SageMaker: anything under /opt/ml/model is uploaded automatically to the
    job's S3OutputPath — write there and you're done. EMR: upload explicitly
    to ML_PLATFORM_S3_OUTPUT_PATH. The returned URI is what you attach to
    the model version ("Attach results") before submitting for MRM review.
    """
    sm_model_dir = os.environ.get("SM_MODEL_DIR")
    if sm_model_dir:  # SageMaker container
        dest = os.path.join(sm_model_dir, os.path.basename(local_path))
        if os.path.abspath(local_path) != os.path.abspath(dest):
            import shutil

            shutil.copy2(local_path, dest)
        return f"{(ctx.s3_output_path or '').rstrip('/')}/{os.path.basename(local_path)}"

    if not ctx.s3_output_path:
        raise RuntimeError("No s3OutputPath was set at job submission.")
    import boto3

    bucket, _, prefix = ctx.s3_output_path[len("s3://"):].partition("/")
    key = f"{prefix.rstrip('/')}/{os.path.basename(local_path)}"
    boto3.client("s3").upload_file(local_path, bucket, key)
    return f"s3://{bucket}/{key}"


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    ctx = load_context()
    run = PlatformRun(ctx)
    log.info("Starting %s (run %s, as-of %s)", ctx.job_id, ctx.run_id, ctx.as_of_date)

    run.log_params({"asOfDate": ctx.as_of_date or "", "entrypoint": os.path.basename(__file__)})

    # 1. Read data — FIRST, while the Snowflake token is fresh.
    #    EMR (Spark):
    #        from pyspark.sql import SparkSession
    #        spark = SparkSession.builder.appName(ctx.job_id).getOrCreate()
    #        df = read_snowflake_spark(spark, ctx)
    #    SageMaker (pandas):
    #        df = read_snowflake_pandas(ctx)
    #    S3 input instead of Snowflake: read from ctx.s3_input_path.

    # 2. TRAIN — replace with your model code.
    #    model = ...
    #    metrics = {"auc": 0.91, "gini": 0.82}

    # 3. Log results and save the artifact.
    #    run.log_metrics(metrics)
    #    run.log_tags({"trainedAt": ctx.as_of_date or ""})
    #    model_path = "/tmp/model.pkl"; joblib.dump(model, model_path)
    #    artifact_uri = save_artifact(model_path, ctx)
    #    log.info("Artifact written to %s", artifact_uri)

    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
