"""Feature Store preview — demonstrates the core Feast-style idea:

    "define a feature once, retrieve it either as a historical batch
    (offline store) or as the latest single value (online store), kept in
    sync by materializing."

This is a demo/preview capability only, scoped for a first release without
a real feature-store integration:
  - There is no real offline store connector (e.g. Snowflake) here.
  - There is no real online store (e.g. DynamoDB-backed Feast online store).
  - There is no real materialization job — "materialize" just stamps a
    timestamp so the UI can show the batch→real-time sync concept.
Every value returned by generate_offline_preview / generate_online_preview
is synthetic. The FeatureView registry itself (name, entity, feature list,
source table) is real and persisted — only the preview data is simulated.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

_DEFAULT_ROWS = 10

# A handful of well-known feature names get realistic-looking values instead
# of generic "val_1234" placeholders — purely cosmetic polish for demos.
_CATEGORICAL_VALUES = {
    "risk_segment": ["low", "medium", "high"],
    "merchant_category": ["grocery", "travel", "electronics", "dining", "utilities"],
}
_INT_RANGES = {
    "age": (18, 85),
    "credit_score": (300, 850),
    "tenure_months": (1, 240),
}


def _synthetic_value(name: str, dtype: str, seed: int) -> Any:
    rng = random.Random(seed)
    if name in _CATEGORICAL_VALUES:
        options = _CATEGORICAL_VALUES[name]
        return options[rng.randrange(len(options))]
    if dtype == "int64":
        lo, hi = _INT_RANGES.get(name, (1, 1000))
        return rng.randint(lo, hi)
    if dtype == "float":
        return round(rng.uniform(1.0, 5000.0), 2)
    if dtype == "bool":
        return rng.random() > 0.8
    if dtype == "timestamp":
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return (base + timedelta(days=rng.randint(0, 500))).strftime("%Y-%m-%d")
    return f"val_{rng.randint(1000, 9999)}"


def _synthetic_entity_id(entity_column: str, seed: int) -> str:
    rng = random.Random(seed)
    prefix = entity_column.replace("_id", "").upper() or "ENTITY"
    return f"{prefix}-{100000 + rng.randint(0, 899999)}"


def generate_offline_preview(
    entity_column: str, features: List[Dict[str, str]], rows: int = _DEFAULT_ROWS
) -> Dict[str, Any]:
    """Synthetic point-in-time batch rows, as if pulled from an offline store."""
    columns = [entity_column, "event_timestamp"] + [f["name"] for f in features]
    data: List[List[Any]] = []
    now = datetime.now(timezone.utc)
    for i in range(rows):
        row: List[Any] = [
            _synthetic_entity_id(entity_column, seed=i),
            (now - timedelta(hours=i * 6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ]
        for j, feat in enumerate(features):
            row.append(_synthetic_value(feat["name"], feat.get("dtype", "string"), seed=i * 31 + j * 7))
        data.append(row)
    return {"columns": columns, "rows": data}


def generate_online_preview(entity_column: str, features: List[Dict[str, str]]) -> Dict[str, Any]:
    """Synthetic "latest value" lookup, as if served from a low-latency online store."""
    seed = random.randint(0, 1_000_000)
    entity_id = _synthetic_entity_id(entity_column, seed=seed)
    values = {
        feat["name"]: _synthetic_value(feat["name"], feat.get("dtype", "string"), seed=seed + i)
        for i, feat in enumerate(features)
    }
    return {
        "entityId": entity_id,
        "asOf": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        # A believable single-digit-to-low-double-digit millisecond lookup —
        # this is the number that sells "this is a real-time path", even
        # though nothing is actually being queried.
        "latencyMs": round(random.uniform(2.0, 14.0), 1),
        "values": values,
    }


def new_materialization_id() -> str:
    return f"mat-{uuid.uuid4().hex[:10]}"
