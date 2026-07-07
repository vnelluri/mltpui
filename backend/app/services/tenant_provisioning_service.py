"""Tenant dataplane provisioning handoff.

The API never creates dataplane infrastructure (EMR Serverless application,
per-tenant execution role, KMS key, S3 prefix) at request time. Instead:

- ``TENANT_PROVISIONING_MOCK_MODE=true`` (local dev): tenant creation is
  self-provisioned with mock resource IDs and the tenant's S3 prefix marker,
  and the tenant goes straight to ``provisioningStatus=active`` so the full
  flow works with zero AWS accounts.
- ``TENANT_PROVISIONING_MOCK_MODE=false`` (prod): tenant creation emits a
  ``TenantProvisioningRequested`` event to EventBridge. The IaC pipeline in
  the dataplane account instantiates the tenant module and reports the
  resulting resource IDs back via ``PUT /tenants/{id}/provisioning``, which
  flips the tenant to ``active``. Until then, job submission is rejected.
"""
from __future__ import annotations

import json
import logging

from app.config import settings
from app.db.client import make_boto3_client
from app.db.models import ProvisioningStatus, Tenant

logger = logging.getLogger("ml_platform.tenant_provisioning")

EVENT_SOURCE = "ml-platform.tenants"
EVENT_DETAIL_TYPE = "TenantProvisioningRequested"


class TenantProvisioningService:
    def __init__(self) -> None:
        self.mock = settings.TENANT_PROVISIONING_MOCK_MODE

    def provision(self, tenant: Tenant, requested_by: str) -> Tenant:
        """Kick off provisioning for a newly created tenant.

        Mutates and returns ``tenant`` with the appropriate provisioning
        state; the caller persists it.
        """
        if self.mock:
            return self._mock_provision(tenant)
        tenant.provisioningStatus = ProvisioningStatus.PENDING.value
        self._emit_provisioning_event(tenant, requested_by)
        return tenant

    def _mock_provision(self, tenant: Tenant) -> Tenant:
        """Local dev: fill mock resource IDs and create the S3 prefix marker."""
        tenant.emrApplicationId = f"mock-emr-app-{tenant.tenantId}"
        tenant.executionRoleArn = (
            f"arn:aws:iam::000000000000:role/mock-{tenant.tenantId}-exec"
        )
        tenant.s3BucketName = f"s3://{settings.S3_ARTIFACTS_BUCKET}/{tenant.tenantId}/"
        tenant.provisioningStatus = ProvisioningStatus.ACTIVE.value
        self._ensure_s3_prefix(tenant.tenantId)
        return tenant

    def _ensure_s3_prefix(self, tenant_id: str) -> None:
        """Create the shared bucket (LocalStack) and the tenant's prefix marker
        so the S3 browser has somewhere to land. Best-effort — never fails
        tenant creation."""
        bucket = settings.S3_ARTIFACTS_BUCKET
        client = make_boto3_client("s3", settings.S3_ENDPOINT_URL)
        try:
            try:
                client.head_bucket(Bucket=bucket)
            except Exception:
                if settings.AWS_REGION == "us-east-1":
                    client.create_bucket(Bucket=bucket)
                else:
                    client.create_bucket(
                        Bucket=bucket,
                        CreateBucketConfiguration={
                            "LocationConstraint": settings.AWS_REGION
                        },
                    )
            client.put_object(Bucket=bucket, Key=f"{tenant_id}/.keep", Body=b"")
        except Exception:
            logger.warning(
                "Could not create S3 prefix for tenant %s (mock provisioning).",
                tenant_id,
                exc_info=True,
            )

    def _emit_provisioning_event(self, tenant: Tenant, requested_by: str) -> None:
        """Publish the provisioning request to EventBridge (best-effort).

        On failure the tenant simply stays ``pending``; a PlatformAdmin can
        re-drive the pipeline manually and complete via the write-back
        endpoint.
        """
        detail = {
            "tenantId": tenant.tenantId,
            "name": tenant.name,
            "computeQuotaVcpuHours": tenant.computeQuotaVcpuHours,
            "allowedFrameworks": tenant.allowedFrameworks,
            "requestedBy": requested_by,
        }
        try:
            client = make_boto3_client("events")
            client.put_events(
                Entries=[
                    {
                        "Source": EVENT_SOURCE,
                        "DetailType": EVENT_DETAIL_TYPE,
                        "Detail": json.dumps(detail),
                        "EventBusName": settings.TENANT_PROVISIONING_EVENT_BUS,
                    }
                ]
            )
        except Exception:
            logger.warning(
                "Failed to emit %s event for tenant %s — tenant stays pending.",
                EVENT_DETAIL_TYPE,
                tenant.tenantId,
                exc_info=True,
            )


tenant_provisioning_service = TenantProvisioningService()
