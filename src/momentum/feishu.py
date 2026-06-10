"""Feishu Base integration for Momentum Radar and Fallen Angel tables.

Best-effort: if Feishu API fails, logs error but does not block report delivery.
Credentials loaded from environment variables (FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_APP_TOKEN).
"""

import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Credentials loaded lazily from environment — same pattern as FMP_API_KEY etc. in .env


def _get_credential(key: str) -> str:
    """Lazily read credential from environment (allows dotenv to load first)."""
    return os.environ.get(key, "")

# Module-level token cache (token + expiry)
_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


def _get_base_url() -> str:
    return f"https://open.feishu.cn/open-apis/bitable/v1/apps/{_get_credential('FEISHU_APP_TOKEN')}"


def get_tenant_token() -> str | None:
    """Get tenant_access_token, reusing cached token within 2hr window."""
    app_id = _get_credential("FEISHU_APP_ID")
    app_secret = _get_credential("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        logger.warning("Feishu credentials not set (FEISHU_APP_ID/FEISHU_APP_SECRET)")
        return None

    # Return cached token if still valid (with 5-min safety margin)
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 300:
        return _token_cache["token"]

    try:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("tenant_access_token")
        expire = data.get("expire", 7200)  # default 2hr
        _token_cache["token"] = token
        _token_cache["expires_at"] = time.time() + expire
        return token
    except Exception as e:
        logger.warning("Failed to get Feishu tenant token: %s", e)
        return None


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _find_table_by_name(token: str, name: str) -> str | None:
    """Find a table ID by name in the Feishu Base app."""
    try:
        resp = requests.get(
            f"{_get_base_url()}/tables",
            headers=_headers(token),
            timeout=10,
        )
        resp.raise_for_status()
        for table in resp.json().get("data", {}).get("items", []):
            if table.get("name") == name:
                return table.get("table_id")
    except Exception as e:
        logger.warning("Failed to list Feishu tables: %s", e)
    return None


def _create_table(token: str, name: str, fields: list[dict[str, Any]]) -> str | None:
    """Create a new table in the Feishu Base app. Returns table_id or None."""
    try:
        resp = requests.post(
            f"{_get_base_url()}/tables",
            headers=_headers(token),
            json={
                "table": {
                    "name": name,
                    "default_view_name": "Grid View",
                    "fields": fields,
                },
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("table_id")
    except Exception as e:
        logger.warning("Failed to create Feishu table '%s': %s", name, e)
        return None


# ─── Table schemas ───

MOMENTUM_TABLE_NAME = "Momentum Radar"
MOMENTUM_FIELDS = [
    {"field_name": "Ticker", "type": 1},       # Text
    {"field_name": "Name", "type": 1},          # Text
    {"field_name": "Sector", "type": 1},        # Text
    {"field_name": "12m Return", "type": 2},    # Number
    {"field_name": "FIP Score", "type": 2},     # Number
    {"field_name": "Composite", "type": 2},     # Number
    {"field_name": "Tier", "type": 2},          # Number
    {"field_name": "Weeks", "type": 2},         # Number
    {"field_name": "Change", "type": 1},        # Text
]

FALLEN_ANGEL_TABLE_NAME = "Fallen Angels"
FALLEN_ANGEL_FIELDS = [
    {"field_name": "Ticker", "type": 1},        # Text
    {"field_name": "Name", "type": 1},          # Text
    {"field_name": "Sector", "type": 1},        # Text
    {"field_name": "Drawdown %", "type": 2},    # Number
    {"field_name": "F-Score", "type": 2},       # Number
    {"field_name": "Z-Score", "type": 2},       # Number
    {"field_name": "MCap $B", "type": 2},       # Number
    {"field_name": "Weeks", "type": 2},         # Number
]


def ensure_tables_exist() -> tuple[str | None, str | None]:
    """Create Momentum Radar + Fallen Angels tables if they don't exist.

    Returns (momentum_table_id, fallen_angel_table_id). Either may be None on failure.
    """
    token = get_tenant_token()
    if not token:
        return None, None

    m_id = _find_table_by_name(token, MOMENTUM_TABLE_NAME)
    if not m_id:
        m_id = _create_table(token, MOMENTUM_TABLE_NAME, MOMENTUM_FIELDS)
        if m_id:
            logger.info("Created Feishu table '%s': %s", MOMENTUM_TABLE_NAME, m_id)

    fa_id = _find_table_by_name(token, FALLEN_ANGEL_TABLE_NAME)
    if not fa_id:
        fa_id = _create_table(token, FALLEN_ANGEL_TABLE_NAME, FALLEN_ANGEL_FIELDS)
        if fa_id:
            logger.info("Created Feishu table '%s': %s", FALLEN_ANGEL_TABLE_NAME, fa_id)

    return m_id, fa_id


def _fetch_all_records(token: str, table_id: str) -> dict[str, str]:
    """Fetch all records and return {ticker: record_id} map."""
    ticker_to_id: dict[str, str] = {}
    page_token: str | None = None
    base = _get_base_url()

    while True:
        try:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(
                f"{base}/tables/{table_id}/records",
                headers=_headers(token),
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            for item in data.get("items", []):
                ticker = item.get("fields", {}).get("Ticker")
                if ticker:
                    ticker_to_id[ticker] = item["record_id"]
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
        except Exception as e:
            logger.warning("Failed to fetch Feishu records: %s", e)
            break

    return ticker_to_id


def _batch_create(
    token: str, table_id: str, records: list[dict[str, Any]]
) -> None:
    """Batch-create records (up to 500 per call)."""
    base = _get_base_url()
    for i in range(0, len(records), 500):
        chunk = records[i : i + 500]
        try:
            resp = requests.post(
                f"{base}/tables/{table_id}/records/batch_create",
                headers=_headers(token),
                json={"records": [{"fields": r} for r in chunk]},
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Feishu batch_create failed (chunk %d): %s", i, e)


def _batch_update(
    token: str, table_id: str, records: list[dict[str, Any]]
) -> None:
    """Batch-update records (up to 500 per call). Each record needs 'record_id' + 'fields'."""
    base = _get_base_url()
    for i in range(0, len(records), 500):
        chunk = records[i : i + 500]
        try:
            resp = requests.post(
                f"{base}/tables/{table_id}/records/batch_update",
                headers=_headers(token),
                json={"records": chunk},
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Feishu batch_update failed (chunk %d): %s", i, e)


def upsert_momentum_records(table_id: str, entries: list) -> None:
    """Upsert momentum radar entries into Feishu Base. Best-effort, batched."""
    token = get_tenant_token()
    if not token:
        logger.warning("Cannot update Feishu momentum table — no token")
        return

    existing = _fetch_all_records(token, table_id)
    to_create: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []

    for entry in entries:
        fields = {
            "Ticker": entry.ticker,
            "Name": entry.name,
            "Sector": entry.sector,
            "12m Return": round(entry.return_12m, 4),
            "FIP Score": round(entry.fip_score, 4),
            "Composite": round(entry.composite_score, 1),
            "Tier": entry.tier,
            "Weeks": entry.weeks_on_list,
            "Change": entry.change,
        }
        record_id = existing.get(entry.ticker)
        if record_id:
            to_update.append({"record_id": record_id, "fields": fields})
        else:
            to_create.append(fields)

    if to_create:
        _batch_create(token, table_id, to_create)
    if to_update:
        _batch_update(token, table_id, to_update)

    logger.info(
        "Feishu momentum: %d created, %d updated", len(to_create), len(to_update)
    )


def upsert_fallen_angel_records(table_id: str, entries: list) -> None:
    """Upsert fallen angel entries into Feishu Base. Best-effort, batched."""
    token = get_tenant_token()
    if not token:
        logger.warning("Cannot update Feishu fallen angel table — no token")
        return

    existing = _fetch_all_records(token, table_id)
    to_create: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []

    for entry in entries:
        fields = {
            "Ticker": entry.ticker,
            "Name": entry.name,
            "Sector": entry.sector,
            "Drawdown %": round(entry.drawdown_pct, 4),
            "F-Score": entry.f_score,
            "Z-Score": round(entry.z_score, 2) if entry.z_score is not None else None,
            "MCap $B": round(entry.market_cap_b, 1),
            "Weeks": entry.weeks_on_list,
        }
        record_id = existing.get(entry.ticker)
        if record_id:
            to_update.append({"record_id": record_id, "fields": fields})
        else:
            to_create.append(fields)

    if to_create:
        _batch_create(token, table_id, to_create)
    if to_update:
        _batch_update(token, table_id, to_update)

    logger.info(
        "Feishu fallen angels: %d created, %d updated", len(to_create), len(to_update)
    )
