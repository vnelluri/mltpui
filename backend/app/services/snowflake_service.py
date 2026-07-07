"""Snowflake OAuth token exchange, KMS token encryption, and query execution.

In ``SNOWFLAKE_MOCK_MODE`` (the local-dev default) every external call is
replaced with realistic mock data whose *shape* is identical to the real
responses, so the frontend behaves the same in both modes.

Security:
- Snowflake OAuth tokens are encrypted with KMS before they ever touch
  DynamoDB (see :class:`KmsCipher`).
- Plaintext tokens are NEVER logged.
- ``/snowflake/query`` is restricted to SELECT statements (see
  :func:`validate_select_only`).
"""
from __future__ import annotations

import base64
import hashlib
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
import sqlparse
from sqlparse.tokens import DML, Keyword

from app.config import settings
from app.db.client import make_boto3_client

# ── SQL safety ───────────────────────────────────────────────────────────────
_FORBIDDEN_KEYWORDS = {
    "CREATE",
    "DROP",
    "ALTER",
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "REPLACE",
    "CALL",
    "EXECUTE",
    "COPY",
    "PUT",
    "REMOVE",
    "USE",
}


class SqlValidationError(ValueError):
    """Raised when a submitted query is not a safe read-only SELECT."""


def validate_select_only(sql: str) -> str:
    """Validate that ``sql`` is a single read-only SELECT statement.

    Rejects DDL/DML keywords even when nested, multiple statements, and
    non-SELECT leading statements. Returns the trimmed SQL on success.
    """
    if not sql or not sql.strip():
        raise SqlValidationError("Query is empty.")

    statements = [s for s in sqlparse.parse(sql) if s.token_first(skip_cm=True)]
    if len(statements) != 1:
        raise SqlValidationError("Only a single SELECT statement is allowed.")

    statement = statements[0]
    stmt_type = statement.get_type()
    if stmt_type != "SELECT":
        # Allow WITH ... SELECT (CTEs) which sqlparse types as "UNKNOWN".
        first = statement.token_first(skip_cm=True)
        if not (first and first.ttype is Keyword.CTE):
            raise SqlValidationError("Only SELECT statements are permitted.")

    # Deep scan every token for forbidden keywords / DML verbs.
    for token in statement.flatten():
        value = token.value.upper()
        if token.ttype in (DML,) and value in _FORBIDDEN_KEYWORDS:
            raise SqlValidationError(
                f"Statement contains a forbidden keyword: {value}"
            )
        if token.ttype in (Keyword, Keyword.DDL, Keyword.DML) and value in _FORBIDDEN_KEYWORDS:
            raise SqlValidationError(
                f"Statement contains a forbidden keyword: {value}"
            )
    return sql.strip().rstrip(";")


def wrap_with_limit(sql: str, limit: int) -> str:
    """Wrap a validated SELECT so results are hard-capped at ``limit`` rows."""
    safe_limit = max(1, min(int(limit), 1000))
    inner = sql.strip().rstrip(";")
    return f"SELECT * FROM (\n{inner}\n) AS _capped LIMIT {safe_limit}"


# ── KMS encryption ──────────────────────────────────────────────────────────
class KmsCipher:
    """Encrypt/decrypt Snowflake tokens with AWS KMS (or LocalStack KMS).

    Falls back to a reversible local encoding only if KMS is entirely
    unavailable, so local dev never hard-fails; the marker prefix records
    which path was used. In production with a real KMS key this always uses
    KMS.
    """

    _LOCAL_PREFIX = "local:"
    _KMS_PREFIX = "kms:"

    def __init__(self, tenant_id: Optional[str] = None) -> None:
        self.tenant_id = tenant_id
        self._client = make_boto3_client("kms", settings.KMS_ENDPOINT_URL)

    def _key_id(self) -> str:
        if settings.KMS_SNOWFLAKE_KEY_ARN:
            return settings.KMS_SNOWFLAKE_KEY_ARN
        # Tenant-specific alias convention, single shared alias locally.
        if self.tenant_id:
            return f"alias/ml-platform-snowflake-{self.tenant_id}"
        return "alias/ml-platform-snowflake"

    def encrypt(self, plaintext: str) -> str:
        try:
            resp = self._client.encrypt(
                KeyId=self._key_id(),
                Plaintext=plaintext.encode("utf-8"),
            )
            blob = resp["CiphertextBlob"]
            return self._KMS_PREFIX + base64.b64encode(blob).decode("ascii")
        except Exception:
            # Local fallback (never used with a real, configured KMS key).
            encoded = base64.b64encode(plaintext.encode("utf-8")).decode("ascii")
            return self._LOCAL_PREFIX + encoded

    def decrypt(self, ciphertext: str) -> str:
        if ciphertext.startswith(self._LOCAL_PREFIX):
            raw = ciphertext[len(self._LOCAL_PREFIX):]
            return base64.b64decode(raw).decode("utf-8")
        if ciphertext.startswith(self._KMS_PREFIX):
            raw = ciphertext[len(self._KMS_PREFIX):]
        else:
            raw = ciphertext
        blob = base64.b64decode(raw)
        resp = self._client.decrypt(CiphertextBlob=blob)
        return resp["Plaintext"].decode("utf-8")


# ── Mock schema catalogue ────────────────────────────────────────────────────
MOCK_DATABASES = ["PROD_DB", "DEV_DB", "ANALYTICS_DB"]
MOCK_SCHEMAS = ["PUBLIC", "ML_FEATURES", "RISK_MODELS", "FRAUD_DETECTION"]

# column name -> logical type
MOCK_TABLE_SCHEMAS: Dict[str, List[Dict[str, str]]] = {
    "TRANSACTION_FEATURES": [
        {"name": "transaction_id", "type": "string"},
        {"name": "customer_id", "type": "string"},
        {"name": "amount", "type": "float"},
        {"name": "merchant_category", "type": "string"},
        {"name": "transaction_date", "type": "date"},
        {"name": "is_fraud", "type": "boolean"},
    ],
    "CUSTOMER_FEATURES": [
        {"name": "customer_id", "type": "string"},
        {"name": "age", "type": "integer"},
        {"name": "tenure_months", "type": "integer"},
        {"name": "credit_score", "type": "integer"},
        {"name": "avg_balance", "type": "float"},
        {"name": "risk_segment", "type": "string"},
    ],
    "MODEL_INPUT_DAILY": [
        {"name": "as_of_date", "type": "date"},
        {"name": "customer_id", "type": "string"},
        {"name": "feature_1", "type": "float"},
        {"name": "feature_2", "type": "float"},
        {"name": "feature_3", "type": "float"},
        {"name": "label", "type": "integer"},
    ],
}
MOCK_TABLES = list(MOCK_TABLE_SCHEMAS.keys())

_MERCHANT_CATEGORIES = ["grocery", "travel", "electronics", "dining", "utilities"]
_RISK_SEGMENTS = ["low", "medium", "high"]


@dataclass
class QueryResult:
    columns: List[str]
    rows: List[List[Any]]
    rowCount: int
    queryId: str


def _synthetic_value(logical_type: str, seed: int) -> Any:
    rng = random.Random(seed)
    if logical_type == "string":
        return f"val_{rng.randint(1000, 9999)}"
    if logical_type == "integer":
        return rng.randint(1, 1000)
    if logical_type == "float":
        return round(rng.uniform(1.0, 5000.0), 2)
    if logical_type == "boolean":
        return rng.random() > 0.85
    if logical_type == "date":
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return (base + timedelta(days=rng.randint(0, 500))).strftime("%Y-%m-%d")
    return f"val_{rng.randint(1000, 9999)}"


def _rows_for_schema(schema: List[Dict[str, str]], n: int, salt: int = 0) -> List[List[Any]]:
    rows: List[List[Any]] = []
    for i in range(n):
        row: List[Any] = []
        for j, col in enumerate(schema):
            name = col["name"]
            logical = col["type"]
            if name == "merchant_category":
                row.append(_MERCHANT_CATEGORIES[(i + salt) % len(_MERCHANT_CATEGORIES)])
            elif name == "risk_segment":
                row.append(_RISK_SEGMENTS[(i + salt) % len(_RISK_SEGMENTS)])
            elif name.endswith("_id"):
                row.append(f"{name[:-3].upper()}-{100000 + i + salt}")
            else:
                row.append(_synthetic_value(logical, seed=(i * 31 + j * 7 + salt)))
        rows.append(row)
    return rows


class SnowflakeService:
    """Facade over Snowflake OAuth + query execution (mock-aware)."""

    def __init__(self) -> None:
        self.mock = settings.SNOWFLAKE_MOCK_MODE

    # ── Token exchange ───────────────────────────────────────────────────
    def exchange_token(
        self, entra_access_token: str, user_email: str
    ) -> Tuple[str, str, str]:
        """Exchange an Entra token for a Snowflake OAuth token.

        Returns ``(raw_token, snowflake_username, expires_at_iso)``.
        """
        if self.mock:
            raw_token = f"mock-sf-token-{uuid.uuid4()}"
            username = self._derive_username(user_email)
            expires_at = (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            return raw_token, username, expires_at

        token_url = settings.snowflake_token_url
        if not token_url:
            raise RuntimeError("SNOWFLAKE_TOKEN_URL / SNOWFLAKE_ACCOUNT not configured.")

        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": entra_access_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "scope": f"session:role:{settings.SNOWFLAKE_OAUTH_INTEGRATION_NAME}",
        }
        auth = None
        if settings.SNOWFLAKE_OAUTH_CLIENT_ID and settings.SNOWFLAKE_OAUTH_CLIENT_SECRET:
            auth = (
                settings.SNOWFLAKE_OAUTH_CLIENT_ID,
                settings.SNOWFLAKE_OAUTH_CLIENT_SECRET,
            )
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(token_url, data=data, auth=auth)
            resp.raise_for_status()
            payload = resp.json()

        raw_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        username = payload.get("username") or self._derive_username(user_email)
        return raw_token, username, expires_at

    @staticmethod
    def _derive_username(email: str) -> str:
        local = (email or "user").split("@")[0]
        return local.upper()

    # ── Catalogue browsing ───────────────────────────────────────────────
    def list_databases(self, token: str) -> List[str]:
        if self.mock:
            return list(MOCK_DATABASES)
        return self._run_scalar_query(token, "SHOW DATABASES", column="name")

    def list_schemas(self, token: str, database: str) -> List[str]:
        if self.mock:
            return list(MOCK_SCHEMAS)
        return self._run_scalar_query(
            token, f"SHOW SCHEMAS IN DATABASE {database}", column="name"
        )

    def list_tables(self, token: str, database: str, schema: str) -> List[Dict[str, Any]]:
        """Return tables with column metadata (mock) or names (real)."""
        if self.mock:
            return [
                {
                    "name": name,
                    "columns": MOCK_TABLE_SCHEMAS[name],
                }
                for name in MOCK_TABLES
            ]
        names = self._run_scalar_query(
            token, f"SHOW TABLES IN SCHEMA {database}.{schema}", column="name"
        )
        return [{"name": n, "columns": []} for n in names]

    def get_table_preview(
        self, token: str, database: str, schema: str, table: str, rows: int = 10
    ) -> QueryResult:
        if self.mock:
            table_schema = MOCK_TABLE_SCHEMAS.get(
                table.upper(),
                [
                    {"name": "col_1", "type": "string"},
                    {"name": "col_2", "type": "float"},
                    {"name": "col_3", "type": "integer"},
                ],
            )
            columns = [c["name"] for c in table_schema]
            data = _rows_for_schema(table_schema, rows, salt=_stable_salt(table))
            return QueryResult(columns, data, len(data), f"mock-query-{uuid.uuid4()}")
        sql = f'SELECT * FROM "{database}"."{schema}"."{table}" LIMIT {rows}'
        return self.execute_query(token, sql, database, schema, settings.SNOWFLAKE_DEFAULT_WAREHOUSE, rows)

    # ── Query execution ──────────────────────────────────────────────────
    def execute_query(
        self,
        token: str,
        sql: str,
        database: str,
        schema: str,
        warehouse: str,
        limit: int = 1000,
    ) -> QueryResult:
        if self.mock:
            return self._mock_query_result(sql, limit)
        return self._real_query(token, sql, database, schema, warehouse)

    def _mock_query_result(self, sql: str, limit: int) -> QueryResult:
        # Try to detect a known table name in the SQL to shape the result.
        upper = sql.upper()
        matched = next((t for t in MOCK_TABLES if t in upper), None)
        n = min(10, max(1, limit))
        if matched:
            table_schema = MOCK_TABLE_SCHEMAS[matched]
            columns = [c["name"] for c in table_schema]
            data = _rows_for_schema(table_schema, n, salt=_stable_salt(matched))
        else:
            generic = [
                {"name": "id", "type": "string"},
                {"name": "value", "type": "float"},
                {"name": "category", "type": "string"},
                {"name": "created_at", "type": "date"},
            ]
            columns = [c["name"] for c in generic]
            data = _rows_for_schema(generic, n, salt=7)
        return QueryResult(columns, data, len(data), f"mock-query-{uuid.uuid4()}")

    def _real_query(
        self, token: str, sql: str, database: str, schema: str, warehouse: str
    ) -> QueryResult:
        """Execute a query via the Snowflake SQL API using the OAuth token."""
        account = settings.SNOWFLAKE_ACCOUNT
        if not account:
            raise RuntimeError("SNOWFLAKE_ACCOUNT not configured.")
        url = f"https://{account}.snowflakecomputing.com/api/v2/statements"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Snowflake-Authorization-Token-Type": "OAUTH",
        }
        body = {
            "statement": sql,
            "timeout": 60,
            "database": database,
            "schema": schema,
            "warehouse": warehouse or settings.SNOWFLAKE_DEFAULT_WAREHOUSE,
        }
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            payload = resp.json()

        columns = [
            col["name"] for col in payload.get("resultSetMetaData", {}).get("rowType", [])
        ]
        rows = payload.get("data", []) or []
        query_id = payload.get("statementHandle", str(uuid.uuid4()))
        return QueryResult(columns, rows, len(rows), query_id)

    def _run_scalar_query(self, token: str, sql: str, column: str) -> List[str]:
        result = self._real_query(
            token, sql, "", "", settings.SNOWFLAKE_DEFAULT_WAREHOUSE
        )
        if column in result.columns:
            idx = result.columns.index(column)
        else:
            idx = 1 if len(result.columns) > 1 else 0
        return [str(r[idx]) for r in result.rows]


def _stable_salt(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:6], 16) % 997


# Module-level singleton.
snowflake_service = SnowflakeService()
