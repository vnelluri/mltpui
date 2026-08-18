"""Unit tests for real-mode job submission — findings of the mock-mode sweep.

Pins the fixes for the fourth batch of mock-mode-hidden landmines: AWS-facing
job names must be slugged (SageMaker/EMR name patterns reject spaces),
SageMaker's required S3OutputPath must default to the tenant prefix, and the
newer EMR "QUEUED" job-run state must not misreport as running.
"""
from __future__ import annotations

import pytest

import app.services.job_service as js
from app.config import settings
from app.db.models import JobStatus, Tenant, TrainingJob


def _job(**overrides):
    defaults = dict(
        jobId="job-1",
        tenantId="tenant-a",
        userId="user-1",
        name="My Training Job (v2)!",
        framework="pytorch",
        entryPointScript="s3://bucket/train.py",
        computeType="emr_serverless",
    )
    defaults.update(overrides)
    return TrainingJob(**defaults)


def _tenant():
    return Tenant(
        tenantId="tenant-a",
        name="A",
        emrApplicationId="app-1",
        executionRoleArn="arn:aws:iam::1:role/ml-platform-tenant-tenant-a-exec",
    )


class FakeEmr:
    def __init__(self):
        self.runs = []

    def start_job_run(self, **kwargs):
        self.runs.append(kwargs)
        return {"jobRunId": "jr-1"}


class FakeSageMaker:
    def __init__(self):
        self.jobs = []

    def create_training_job(self, **kwargs):
        self.jobs.append(kwargs)
        return {}


def _svc():
    svc = js.JobService()
    svc.emr_mock = False
    svc.sagemaker_mock = False
    return svc


# ── Name slugging ────────────────────────────────────────────────────────────


def test_safe_job_name_slugs_invalid_chars():
    assert js.JobService._safe_job_name("My Training Job (v2)!", 64) == (
        "My-Training-Job-v2"
    )
    assert js.JobService._safe_job_name("___", 64) == "job"  # never empty
    assert js.JobService._safe_job_name("a" * 100, 40) == "a" * 40


def test_emr_submit_uses_slugged_name(monkeypatch):
    emr = FakeEmr()
    monkeypatch.setattr(js, "dataplane_client", lambda *a, **k: emr)
    _svc().submit_emr_job(_job(), _tenant(), secret_arn=None)
    (run,) = emr.runs
    assert run["name"] == "My-Training-Job-v2"
    assert run["tags"]["tenantId"] == "tenant-a"


def test_sagemaker_submit_uses_slugged_name(monkeypatch):
    sm = FakeSageMaker()
    monkeypatch.setattr(js, "dataplane_client", lambda *a, **k: sm)
    monkeypatch.setattr(settings, "SAGEMAKER_TRAINING_IMAGE", "img:latest")
    _svc().submit_sagemaker_job(
        _job(computeType="sagemaker"), _tenant(), secret_arn=None
    )
    (created,) = sm.jobs
    assert created["TrainingJobName"].startswith("My-Training-Job-v2-")
    # SageMaker pattern: no spaces, parens, underscores.
    import re

    assert re.fullmatch(
        r"[a-zA-Z0-9](-*[a-zA-Z0-9])*", created["TrainingJobName"]
    )


# ── SageMaker S3OutputPath default ───────────────────────────────────────────


def test_sagemaker_defaults_output_path_to_tenant_prefix(monkeypatch):
    sm = FakeSageMaker()
    monkeypatch.setattr(js, "dataplane_client", lambda *a, **k: sm)
    monkeypatch.setattr(settings, "SAGEMAKER_TRAINING_IMAGE", "img:latest")
    job = _job(computeType="sagemaker")  # no s3OutputPath
    _svc().submit_sagemaker_job(job, _tenant(), secret_arn=None)
    (created,) = sm.jobs
    expected = f"s3://{settings.S3_ARTIFACTS_BUCKET}/tenant-a/jobs/job-1/output/"
    # Never an empty string (required field), written back on the record, and
    # the env var the training script reads agrees.
    assert created["OutputDataConfig"]["S3OutputPath"] == expected
    assert job.s3OutputPath == expected
    assert created["Environment"]["ML_PLATFORM_S3_OUTPUT_PATH"] == expected


def test_sagemaker_explicit_output_path_kept(monkeypatch):
    sm = FakeSageMaker()
    monkeypatch.setattr(js, "dataplane_client", lambda *a, **k: sm)
    monkeypatch.setattr(settings, "SAGEMAKER_TRAINING_IMAGE", "img:latest")
    job = _job(computeType="sagemaker", s3OutputPath="s3://x/custom/")
    _svc().submit_sagemaker_job(job, _tenant(), secret_arn=None)
    assert sm.jobs[0]["OutputDataConfig"]["S3OutputPath"] == "s3://x/custom/"


# ── EMR state mapping ────────────────────────────────────────────────────────


def test_emr_queued_state_maps_to_queued():
    assert js.JobService._map_emr_state("QUEUED") == JobStatus.QUEUED.value


def test_emr_whitespace_env_guard(monkeypatch):
    """Free-text values must not ride spark-submit params (pre-existing
    guard — pinned here so the sweep's contract stays enforced)."""
    emr = FakeEmr()
    monkeypatch.setattr(js, "dataplane_client", lambda *a, **k: emr)
    job = _job(s3InputPath="s3://bucket/path with spaces/")
    with pytest.raises(RuntimeError) as exc:
        _svc().submit_emr_job(job, _tenant(), secret_arn=None)
    assert "whitespace" in str(exc.value)
