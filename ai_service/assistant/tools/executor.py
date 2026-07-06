"""In-process read-only tool executor for L3 agent (no HTTP self-calls)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from assistant.config import ai_service_root, load_assistant_config
from assistant.health import build_health_payload
from assistant.tools.registry import get_tool_names

_DEFAULT_IV_CSV = ai_service_root() / "data" / "usgs_puget_iv.csv"
_PUGET_SITES_JSON = ai_service_root() / "config" / "usgs_puget_default_sites.json"
_ALLOWED_FORECAST_PARAMS = frozenset({"00060", "63680"})
_SITE_NO_PATTERN = re.compile(r"^\d{8}$")

READONLY_TOOL_NAMES = frozenset(get_tool_names())


def list_tool_names() -> list[str]:
    return sorted(READONLY_TOOL_NAMES)


def _load_puget_allowlist() -> set[str]:
    if not _PUGET_SITES_JSON.is_file():
        return set()
    try:
        payload = json.loads(_PUGET_SITES_JSON.read_text(encoding="utf-8"))
        sites = payload.get("sites") or []
        return {str(s.get("site_no", "")).strip() for s in sites if s.get("site_no")}
    except (json.JSONDecodeError, OSError):
        return set()


def validate_site_no(site_no: str) -> str:
    """Accept any 8-digit USGS site; normalize and strip."""
    site = str(site_no).strip()
    if not _SITE_NO_PATTERN.match(site):
        raise ValueError(f"site_no must be an 8-digit USGS site number, got: {site_no!r}")
    return site


def is_puget_demo_site(site_no: str) -> bool:
    return site_no in _load_puget_allowlist()


def execute_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Dispatch a whitelisted read-only tool by name.

    Returns ``{ok: true, data, source}`` or ``{ok: false, error_code, message}``.
    """
    if name not in READONLY_TOOL_NAMES:
        return {
            "ok": False,
            "error_code": "TOOL_NOT_ALLOWED",
            "message": f"Tool {name!r} is not in the read-only whitelist.",
        }

    args = dict(arguments or {})
    try:
        if name == "get_turbidity_risk_forecast_12h":
            return _get_turbidity_risk_forecast_12h(args)
        if name == "get_forecast_series":
            return _get_forecast_series(args)
        if name == "get_assistant_health":
            return _get_assistant_health()
        if name == "get_turbidity_state_snapshot":
            return _get_turbidity_state_snapshot(args)
        if name == "list_puget_default_sites":
            return _list_puget_default_sites()
        if name == "search_ops_docs":
            return _search_ops_docs_tool(args)
        return {"ok": False, "error_code": "UNKNOWN_TOOL", "message": f"Unhandled tool: {name}"}
    except ValueError as exc:
        return {"ok": False, "error_code": "INVALID_ARGUMENT", "message": str(exc)}
    except FileNotFoundError as exc:
        return {"ok": False, "error_code": "DATA_NOT_FOUND", "message": str(exc)}
    except Exception as exc:
        return {"ok": False, "error_code": "TOOL_EXECUTION_FAILED", "message": str(exc)}


def _ok(data: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {"ok": True, "data": data, "source": source}


def _get_turbidity_risk_forecast_12h(args: dict[str, Any]) -> dict[str, Any]:
    from models.turbidity_risk_forecast_12h import run_risk_forecast_12h

    site_no = validate_site_no(args.get("site_no", ""))
    reference_utc = args.get("reference_utc")
    ref = str(reference_utc).strip() if reference_utc else None
    if ref == "":
        ref = None

    data = run_risk_forecast_12h(site_no=site_no, reference_utc=ref)
    return _ok(data, source="python:/turbidity/risk-forecast-12h")


def _get_forecast_series(args: dict[str, Any]) -> dict[str, Any]:
    from models.forecast_engine import forecast_series_from_iv_csv

    site_no = validate_site_no(args.get("site_no", ""))
    parameter_cd = str(args.get("parameter_cd", "")).strip()
    if parameter_cd not in _ALLOWED_FORECAST_PARAMS:
        raise ValueError(f"parameter_cd must be 00060 or 63680, got: {parameter_cd!r}")

    horizon_raw = args.get("horizon_hours")
    if horizon_raw is None:
        raise ValueError("horizon_hours is required")
    horizon_hours = int(horizon_raw)
    if horizon_hours < 1 or horizon_hours > 168:
        raise ValueError("horizon_hours must be between 1 and 168")

    history_days = int(args.get("history_days", 30))
    if history_days < 1 or history_days > 90:
        raise ValueError("history_days must be between 1 and 90")

    csv_path = Path(args.get("iv_csv_path")) if args.get("iv_csv_path") else _DEFAULT_IV_CSV
    if not csv_path.is_file():
        raise FileNotFoundError(f"IV CSV not found: {csv_path}")

    data = forecast_series_from_iv_csv(
        csv_path,
        site_no=site_no,
        parameter_cd=parameter_cd,
        horizon_hours=horizon_hours,
        history_days=history_days,
    )
    return _ok(data, source="python:/forecast/series")


def _get_assistant_health() -> dict[str, Any]:
    cfg = load_assistant_config()
    data = build_health_payload(cfg)
    return _ok(data, source="python:/assistant/health")


def _get_turbidity_state_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    from models.turbidity_state_monitoring import run_state_snapshot

    site_no = validate_site_no(args.get("site_no", ""))
    reference_utc = args.get("reference_utc")
    ref = str(reference_utc).strip() if reference_utc else None
    if ref == "":
        ref = None

    data = run_state_snapshot(
        site_no,
        features_csv=args.get("features_csv_path"),
        thresholds_json=args.get("thresholds_json_path"),
        reference_utc=ref,
    )
    return _ok(data, source="python:/turbidity/state/snapshot")


def _list_puget_default_sites() -> dict[str, Any]:
    from puget_site_discovery import load_puget_config

    if not _PUGET_SITES_JSON.is_file():
        raise FileNotFoundError(f"Puget sites config not found: {_PUGET_SITES_JSON}")
    data = load_puget_config(_PUGET_SITES_JSON)
    return _ok(data, source="python:/config/puget-default-sites")


def _search_ops_docs_tool(args: dict[str, Any]) -> dict[str, Any]:
    from assistant.config import load_rag_config
    from assistant.rag.search import ensure_rag_index, search_ops_docs

    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")

    top_k_raw = args.get("top_k")
    top_k: int | None = None
    if top_k_raw is not None:
        top_k = int(top_k_raw)
        if top_k < 1 or top_k > 10:
            raise ValueError("top_k must be between 1 and 10")

    cfg = load_rag_config()
    ensure_rag_index(cfg)
    hits = search_ops_docs(query, top_k=top_k, config=cfg)
    data = {
        "query": query,
        "hit_count": len(hits),
        "hits": [
            {
                "ref": f"{hit.chunk.source_path}#{hit.chunk.anchor}",
                "heading": hit.chunk.heading,
                "score": round(hit.score, 4),
                "text": hit.chunk.text,
            }
            for hit in hits
        ],
    }
    return _ok(data, source="rag:search_ops_docs")
