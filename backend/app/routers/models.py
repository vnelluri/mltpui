"""Model registry: register, list, transition stage, model card, archive."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
from app.config import settings
from app.db.client import make_boto3_client
from app.db.models import GovernanceReview, ModelDevStatus, ModelStage, ModelVersion
from app.db.repositories.experiment_repo import ExperimentRepository
from app.db.repositories.governance_repo import GovernanceRepository
from app.db.repositories.model_repo import ModelRepository
from app.dependencies import get_current_user, require_role
from app.middleware.tenant_scope import enforce_tenant_access, resolve_write_tenant
from app.services.audit_service import audit_service
from app.services.model_card_service import build_model_card

router = APIRouter(prefix="/models", tags=["models"])

_repo = ModelRepository()
_exp_repo = ExperimentRepository()
_gov_repo = GovernanceRepository()


def _scope_tenant(user: CurrentUser, requested_tenant_id: Optional[str]) -> str:
    """Resolve which tenant's model namespace a name-based endpoint targets.

    Model names are namespaced per tenant, so cross-tenant roles
    (PlatformAdmin/MRM) must say which tenant they mean via the ``tenantId``
    query parameter; tenant-scoped users are always pinned to their own.
    """
    if user.sees_all_tenants:
        tenant_id = requested_tenant_id or user.tenantId
        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Model names are tenant-scoped: cross-tenant roles must "
                    "pass the tenantId query parameter."
                ),
            )
        return tenant_id
    if not user.tenantId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current user has no tenant assigned.",
        )
    if requested_tenant_id and requested_tenant_id != user.tenantId:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only access models within your own tenant.",
        )
    return user.tenantId


def _validate_artifact_uri(artifact_uri: str, field: str = "artifactUri") -> str:
    """Reject artifact URIs that don't point at anything real in S3.

    The registry is what MRM reviews against — a free-text URI that nobody
    verified makes every downstream governance step untrustworthy. Accepts
    either an exact object key or a prefix containing at least one object.
    Returns the normalized (trimmed) URI; errors name the offending field.
    ARTIFACT_URI_MOCK_MODE=true (testing only) skips the S3 existence
    lookup, keeping just the format checks.
    """
    artifact_uri = artifact_uri.strip()
    if not artifact_uri.startswith("s3://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} must be an s3:// URI, e.g. s3://ml-platform-artifacts/<tenant>/models/model.pkl.",
        )
    bucket, _, key = artifact_uri[len("s3://"):].partition("/")
    if not bucket or not key.strip("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{field} must include a bucket AND a key/prefix after it — got "
                f"'{artifact_uri}'. Expected e.g. s3://ml-platform-artifacts/<tenant>/models/model.pkl."
            ),
        )
    if settings.ARTIFACT_URI_MOCK_MODE:
        return artifact_uri
    client = make_boto3_client("s3", settings.S3_ENDPOINT_URL)
    try:
        try:
            client.head_object(Bucket=bucket, Key=key)
            return artifact_uri
        except Exception:
            resp = client.list_objects_v2(Bucket=bucket, Prefix=key, MaxKeys=1)
            if resp.get("KeyCount", 0) > 0:
                return artifact_uri
    except Exception:
        pass
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"No object found at {field} '{artifact_uri}' — upload it first.",
    )


# Use-case IDs follow the enterprise inventory convention: "UC-" + 4 digits.
_USECASE_ID_RE = re.compile(r"^UC-\d{4}$")


class ModelRegisterRequest(BaseModel):
    # The model's inventory KEY, chosen by the registrant (e.g. MDL-0001).
    # Shared by every version of the model; (modelId, version) must be
    # globally unique.
    modelId: str
    name: str
    # Free-form version string ("2", "1.0.3", "2024-Q1"); omitted -> the next
    # numeric version for this model name.
    version: Optional[str] = None
    # The business use case this model serves (format UC-####). Registration
    # happens at inception, before any training run exists — so the use case
    # is the anchor here, and the run/artifact are attached later via the
    # update endpoint ("Attach results").
    usecaseId: str
    # Target tenant: required for PlatformAdmin (who has no tenant of their
    # own); tenant-scoped users may omit it and any mismatch is rejected.
    tenantId: Optional[str] = None
    framework: Optional[str] = None
    artifactUri: Optional[str] = None
    description: Optional[str] = None
    modelSchema: Dict[str, Any] = {}
    hasExplainer: bool = False
    driftBaselineUri: Optional[str] = None


class ModelUpdateRequest(BaseModel):
    """Post-training update: attach the trained artifact and the metadata
    MRM reviews against. Registration happens FIRST (at inception, before
    training) — this is how results land on the inventory entry afterwards."""

    description: Optional[str] = None
    runId: Optional[str] = None
    framework: Optional[str] = None
    artifactUri: Optional[str] = None
    modelSchema: Optional[Dict[str, Any]] = None
    results: Optional[Dict[str, Any]] = None
    documentationUri: Optional[str] = None
    hasExplainer: Optional[bool] = None
    driftBaselineUri: Optional[str] = None


class StageTransitionRequest(BaseModel):
    stage: str
    # ServiceNow change ticket — required when promoting to Production.
    snowTicketId: Optional[str] = None


@router.post("", response_model=ModelVersion, status_code=status.HTTP_201_CREATED)
async def register_model(
    body: ModelRegisterRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("DataScientist")),
) -> ModelVersion:
    tenant_id = resolve_write_tenant(user, body.tenantId).tenantId

    usecase_id = body.usecaseId.strip().upper()
    if not _USECASE_ID_RE.match(usecase_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="usecaseId must be in the form UC-#### (e.g. UC-1043).",
        )
    model_id = body.modelId.strip()
    if not model_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="modelId is required — it is the model's inventory key.",
        )
    # Registration trust: MRM reviews against these fields, so they must
    # reference things that actually exist.
    artifact_uri = _validate_artifact_uri(body.artifactUri) if body.artifactUri else None

    version = (body.version or "").strip()
    if not version:
        # Auto-number: the next numeric version for this model name.
        version = str(_repo.latest_version_number(tenant_id, body.name) + 1)
    # Lineage consistency: a model NAME maps to exactly one Model ID, and a
    # Model ID to exactly one model — reviews and journeys are keyed by
    # (modelId, version), so a fragmented mapping would corrupt governance.
    siblings = _repo.list_versions(tenant_id, body.name)
    if siblings and siblings[0].modelId != model_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{body.name}' is already registered under Model ID "
                f"'{siblings[0].modelId}' — new versions must reuse it."
            ),
        )
    same_key = _repo.list_by_model_id(model_id)
    if same_key and (same_key[0].name != body.name or same_key[0].tenantId != tenant_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Model ID '{model_id}' already belongs to '{same_key[0].name}' "
                f"(tenant '{same_key[0].tenantId}')."
            ),
        )
    # modelId is the KEY: reject anything that would collide with an
    # existing entry — same name+version in this tenant, or the same
    # (modelId, version) pair anywhere.
    if _repo.get_version(tenant_id, body.name, version) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{body.name}' v{version} already exists in tenant '{tenant_id}'.",
        )
    if _repo.get_by_model_id(model_id, version) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Model ID '{model_id}' v{version} is already registered.",
        )

    mv = ModelVersion(
        modelId=model_id,
        tenantId=tenant_id,
        name=body.name,
        version=version,
        stage=ModelStage.NONE.value,
        usecaseId=usecase_id,
        framework=body.framework,
        artifactUri=artifact_uri,
        description=body.description,
        modelSchema=body.modelSchema,
        hasExplainer=body.hasExplainer,
        driftBaselineUri=body.driftBaselineUri,
        registeredBy=user.userId,
    )
    _repo.create(mv)
    audit_service.record(
        user=user,
        action="model.register",
        resource_type="ModelVersion",
        resource_id=f"{mv.name}/{mv.version}",
        tenant_id=tenant_id,
        details={"usecaseId": mv.usecaseId},
        request=request,
    )
    return mv


def compute_dev_status(mv: ModelVersion, reviews: list[GovernanceReview]) -> str:
    """Derive where a version sits in its development journey.

    The registry row shows this to the data scientist, who cannot read the
    MRM review queue directly (GET /governance/reviews is MRM-only) — so the
    review outcome has to surface here, folded into the model listing.
    """
    # modelId is shared by every version of a model, so reviews fetched by
    # modelId must be narrowed to THIS version — v1's approval must never
    # paint v2's journey.
    reviews = [r for r in reviews if r.modelVersion == mv.version]
    latest = max(reviews, key=lambda r: r.createdAt, default=None)
    if latest is not None:
        if latest.decision == "approved":
            return ModelDevStatus.MRM_APPROVED.value
        if latest.decision == "rejected":
            return ModelDevStatus.MRM_REJECTED.value
        return ModelDevStatus.SUBMITTED_TO_MRM.value
    if mv.artifactUri:
        return ModelDevStatus.DEV_COMPLETE.value
    return ModelDevStatus.INITIATED.value


@router.get("")
async def list_models(
    page: int = 1, pageSize: int = 20, user: CurrentUser = Depends(get_current_user)
) -> Dict[str, Any]:
    if user.sees_all_tenants:
        items = _repo.list_all()
    else:
        items = _repo.list_by_tenant(user.tenantId)
    total = len(items)
    start = (page - 1) * pageSize
    page_slice = items[start : start + pageSize]

    # Reviews are only needed for the PAGE being returned. Tenant-scoped
    # users get them in one cheap GSI query; cross-tenant users get one
    # key-scoped GSI query per unique modelId on the page — never a second
    # full-table scan that grows with total platform history.
    reviews_by_model: Dict[str, list] = {}
    if user.sees_all_tenants:
        for model_id in {m.modelId for m in page_slice}:
            reviews_by_model[model_id] = _gov_repo.list_by_model(model_id)
    else:
        for r in _gov_repo.list_by_tenant(user.tenantId):
            reviews_by_model.setdefault(r.modelId, []).append(r)

    page_items = [
        {**m.model_dump(), "devStatus": compute_dev_status(m, reviews_by_model.get(m.modelId, []))}
        for m in page_slice
    ]
    return {
        "items": page_items,
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/{name}/versions")
async def list_versions(
    name: str,
    tenantId: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    tenant_id = _scope_tenant(user, tenantId)
    versions = _repo.list_versions(tenant_id, name)
    for v in versions:
        enforce_tenant_access(user, v.tenantId)
    return {"items": versions, "total": len(versions), "page": 1, "pageSize": len(versions) or 1}


def _get_owned_version(
    name: str, ver: str, user: CurrentUser, requested_tenant_id: Optional[str]
) -> ModelVersion:
    tenant_id = _scope_tenant(user, requested_tenant_id)
    mv = _repo.get_version(tenant_id, name, ver)
    if mv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model version not found.")
    enforce_tenant_access(user, mv.tenantId)
    return mv


@router.get("/{name}/versions/{ver}", response_model=ModelVersion)
async def get_version(
    name: str,
    ver: str,
    tenantId: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> ModelVersion:
    return _get_owned_version(name, ver, user, tenantId)


@router.put("/{name}/versions/{ver}", response_model=ModelVersion)
async def update_version(
    name: str,
    ver: str,
    body: ModelUpdateRequest,
    request: Request,
    tenantId: Optional[str] = None,
    user: CurrentUser = Depends(require_role("TenantAdmin", "DataScientist")),
) -> ModelVersion:
    """Attach training results (artifact, run, schemas) to a registered model.

    Locked once a governance review is pending or approved: MRM must review
    exactly the artifact that was submitted — it cannot be swapped afterwards.
    A rejected review unlocks the version so the owner can fix and resubmit.
    """
    mv = _get_owned_version(name, ver, user, tenantId)
    reviews = _gov_repo.list_by_model(mv.modelId)
    # Version-scoped: v1's pending/approved review must not lock v2's attach
    # (modelId is shared across versions).
    blocking = next(
        (
            r
            for r in reviews
            if r.modelVersion == mv.version and r.decision in {"pending", "approved"}
        ),
        None,
    )
    if blocking is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This version has a {blocking.decision} governance review "
                f"({blocking.reviewId}) — its artifact and metadata are locked."
            ),
        )

    if body.runId is not None and _exp_repo.get_run_by_id(mv.tenantId, body.runId) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"runId '{body.runId}' does not exist in tenant '{mv.tenantId}'.",
        )
    updates = body.model_dump(exclude_unset=True)
    if body.artifactUri is not None:
        updates["artifactUri"] = _validate_artifact_uri(body.artifactUri)
    # Documentation is reviewed too — same "must actually exist" bar as the
    # trained artifact. An empty/whitespace value clears the field.
    if "documentationUri" in updates:
        doc = (updates["documentationUri"] or "").strip()
        updates["documentationUri"] = (
            _validate_artifact_uri(doc, field="documentationUri") if doc else None
        )
    for field, value in updates.items():
        setattr(mv, field, value)
    updated = _repo.update(mv)
    audit_service.record(
        user=user,
        action="model.update",
        resource_type="ModelVersion",
        resource_id=f"{name}/{ver}",
        tenant_id=mv.tenantId,
        details={"fields": sorted(updates.keys())},
        request=request,
    )
    return updated


@router.put("/{name}/versions/{ver}/stage", response_model=ModelVersion)
async def transition_stage(
    name: str,
    ver: str,
    body: StageTransitionRequest,
    request: Request,
    tenantId: Optional[str] = None,
    user: CurrentUser = Depends(require_role("TenantAdmin")),
) -> ModelVersion:
    mv = _get_owned_version(name, ver, user, tenantId)
    snow_ticket = (body.snowTicketId or "").strip().upper() or None
    if body.stage == ModelStage.PRODUCTION.value:
        # THIS version must be approved — a sibling version's approval does
        # not authorize an unreviewed binary into Production.
        if not _gov_repo.has_approved_review(mv.modelId, mv.version):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An approved governance review is required before promoting to Production.",
            )
        # Deployment readiness is gated on change management: the promotion
        # must reference the ServiceNow change ticket that authorized it.
        if not snow_ticket:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A ServiceNow change ticket (e.g. CHG0012345) is required to promote to Production.",
            )
    from app.db.models import utcnow_iso

    mv.stage = body.stage
    mv.promotedAt = utcnow_iso()
    mv.promotedBy = user.userId
    if snow_ticket:
        mv.snowTicketId = snow_ticket
    updated = _repo.update(mv)
    audit_service.record(
        user=user,
        action="model.stage_transition",
        resource_type="ModelVersion",
        resource_id=f"{name}/{ver}",
        tenant_id=mv.tenantId,
        details={"newStage": body.stage, "snowTicketId": snow_ticket},
        request=request,
    )
    return updated


@router.get("/{name}/versions/{ver}/card")
async def get_model_card(
    name: str,
    ver: str,
    tenantId: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    mv = _get_owned_version(name, ver, user, tenantId)
    run = _exp_repo.get_run_by_id(mv.tenantId, mv.runId) if mv.runId else None
    # The card describes ONE version — narrow the model's reviews to it.
    reviews = [
        r for r in _gov_repo.list_by_model(mv.modelId) if r.modelVersion == mv.version
    ]
    return build_model_card(mv, run, reviews)


@router.post("/{name}/versions/{ver}/archive", response_model=ModelVersion)
async def archive_version(
    name: str,
    ver: str,
    request: Request,
    tenantId: Optional[str] = None,
    user: CurrentUser = Depends(require_role("TenantAdmin")),
) -> ModelVersion:
    mv = _get_owned_version(name, ver, user, tenantId)
    mv.stage = ModelStage.ARCHIVED.value
    updated = _repo.update(mv)
    audit_service.record(
        user=user,
        action="model.archive",
        resource_type="ModelVersion",
        resource_id=f"{name}/{ver}",
        tenant_id=mv.tenantId,
        request=request,
    )
    return updated
