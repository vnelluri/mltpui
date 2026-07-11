"""Generate model card JSON for a registered model version.

The model card aggregates the ModelVersion, its originating ExperimentRun
(params/metrics), and its governance review history into a single document
suitable for MRM download or the frontend model-card viewer.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.db.models import ExperimentRun, GovernanceReview, ModelVersion


def build_model_card(
    model: ModelVersion,
    run: Optional[ExperimentRun],
    reviews: list[GovernanceReview],
) -> Dict[str, Any]:
    """Build a fully-populated model card document."""
    return {
        "modelId": model.modelId,
        "name": model.name,
        "version": model.version,
        "tenantId": model.tenantId,
        "stage": model.stage,
        "usecaseId": model.usecaseId,
        "framework": model.framework,
        "description": model.description,
        "artifactUri": model.artifactUri,
        "registeredAt": model.registeredAt,
        "registeredBy": model.registeredBy,
        "promotedAt": model.promotedAt,
        "promotedBy": model.promotedBy,
        "snowTicketId": model.snowTicketId,
        "schema": model.modelSchema,
        "results": model.results,
        "documentationUri": model.documentationUri,
        "explainability": {
            "hasExplainer": model.hasExplainer,
            "driftBaselineUri": model.driftBaselineUri,
        },
        "trainingRun": (
            {
                "runId": run.runId,
                "experimentId": run.experimentId,
                "jobId": run.jobId,
                "status": run.status,
                "startTime": run.startTime,
                "endTime": run.endTime,
                "params": run.params,
                "metrics": run.metrics,
                "tags": run.tags,
                "artifactUri": run.artifactUri,
            }
            if run is not None
            else None
        ),
        "governance": {
            "reviewCount": len(reviews),
            "hasApprovedReview": any(r.decision == "approved" for r in reviews),
            "reviews": [
                {
                    "reviewId": r.reviewId,
                    "submittedBy": r.submittedBy,
                    "createdAt": r.createdAt,
                    "reviewedBy": r.reviewedBy,
                    "decision": r.decision,
                    "comments": r.comments,
                    "conditions": r.conditions,
                    "mrmArtifactUris": r.mrmArtifactUris,
                    "reviewedAt": r.reviewedAt,
                    "expiresAt": r.expiresAt,
                }
                for r in reviews
            ],
        },
    }


def build_governance_export(
    model: ModelVersion,
    run: Optional[ExperimentRun],
    reviews: list[GovernanceReview],
    audit_events: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Model card + full audit trail, for /governance/export."""
    card = build_model_card(model, run, reviews)
    card["auditTrail"] = audit_events
    return card
