"""FastAPI application entrypoint.

Mounts every router, wires CORS + request logging, and exposes the OpenAPI
Swagger UI at ``/docs`` (fully usable in ``AUTH_MODE=dev`` with no auth
headers, since ``get_current_user`` short-circuits to a synthetic user).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.middleware.request_logging import RequestLoggingMiddleware
from app.services.snowflake_service import KmsEncryptionError
from app.routers import (
    audit,
    auth,
    experiments,
    feature_store,
    governance,
    group_mappings,
    health,
    jobs,
    models,
    notebooks,
    s3,
    snowflake,
    tenants,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="ML Training Platform API",
    description=(
        "Multi-tenant ML Model Training Platform — FastAPI backend. "
        "Tenancy and role are resolved from Entra ID group membership "
        "(AUTH_MODE=prod) or a synthetic dev user (AUTH_MODE=dev)."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)


@app.exception_handler(KmsEncryptionError)
async def kms_encryption_error_handler(request: Request, exc: KmsEncryptionError):
    """Fail closed on token-encryption problems: the operation is refused
    (503) rather than ever storing/using a token without real encryption."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(jobs.router)
app.include_router(experiments.router)
app.include_router(feature_store.router)
app.include_router(models.router)
app.include_router(governance.router)
app.include_router(notebooks.router)
app.include_router(s3.router)
app.include_router(snowflake.router)
app.include_router(group_mappings.router)
app.include_router(audit.router)
