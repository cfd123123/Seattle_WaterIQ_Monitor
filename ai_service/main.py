"""
FastAPI service: USGS IV short-horizon forecast, IV maintenance, anomaly helpers, turbidity batch reads,
and turbidity four-state monitoring (plan/turbidity_state_monitoring.md).

- IV CSV refresh: ``POST /refresh/usgs-iv`` overwrites ``data/usgs_puget_iv.csv``.
- Short-horizon forecast: ``POST /forecast``, ``POST /forecast/series`` (``forecast_engine``).
- Turbidity states: ``POST /turbidity/state/monitor``, ``POST /turbidity/state/snapshot``.
- Turbidity 12h risk: ``POST /turbidity/risk-forecast-12h`` (Phase B persistence; not NTU curve).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from fetch_usgs_puget_sound import run_fetch
from usgs_site_verify import nwis_site_verify_json
from models.forecast_engine import forecast_from_iv_csv, forecast_series_from_iv_csv
from models.site_param_anomaly_on_demand import site_param_anomaly_from_iv_csv
from models.site_param_multivar_anomaly_on_demand import site_param_multivar_anomaly_from_features
from models.turbidity_threshold_iv import site_nos_with_nonnull_63680, turbidity_threshold_batch_sites
from models.turbidity_risk_forecast_12h import run_risk_forecast_12h
from models.turbidity_risk_forecast_backtest import DEFAULT_THRESHOLDS_JSON
from models.turbidity_state_monitoring import (
    DEFAULT_ABSOLUTE_NTU_CRITICAL,
    DEFAULT_FEATURES_CSV,
    DEFAULT_SITE_NO,
    WARNING_HORIZONS,
    build_tier_rules_metadata,
    compute_thresholds,
    label_alert_tier,
    label_states,
    load_features,
    run_state_monitoring,
    snapshot_at_reference,
)
from models.backtest_turbidity_exog_ridge_lgbm import UPSTREAM_DISCHARGE_COL, _split_index_for_holdout
from usgs_iv_core_snapshot import latest_complete_core_snapshot
from puget_site_discovery import (
    DEFAULT_CORE_PARAMS,
    DEFAULT_PUGET_BBOX,
    discover_core_sites_in_bbox,
    load_puget_config,
    merge_new_sites_into_config,
)
from assistant.config import load_assistant_config
from assistant.copilot_router import copilot_router
from assistant.explain_turbidity import generate_risk_explanation
from assistant.router import router as assistant_router

app = FastAPI(title="USGS IV Forecast & Maintenance")
app.include_router(assistant_router)
app.include_router(copilot_router)

_DEFAULT_IV_CSV = Path(__file__).resolve().parent / "data" / "usgs_puget_iv.csv"
_DEFAULT_PUGET_SITES_JSON = Path(__file__).resolve().parent / "config" / "usgs_puget_default_sites.json"
_AI_SERVICE_ROOT = Path(__file__).resolve().parent


class HealthResponse(BaseModel):
    status: Literal["ok"]


class UsgsIvRefreshRequest(BaseModel):
    """Refresh IV CSV: pull from NWIS for the last ``days`` and **overwrite** the default path (no append)."""

    days: int = Field(default=30, ge=1, le=90, description="Lookback days (max 90 to cap size).")
    extra_site_nos: list[str] | None = Field(
        default=None,
        description="Extra USGS site numbers (e.g. registered external_id) merged with config list before fetch.",
    )


class ForecastRequest(BaseModel):
    """Short-horizon forecast from local IV CSV (same merged format as ``fetch_usgs_puget_sound`` output)."""

    site_no: str = Field(..., min_length=1, description="USGS 8-digit site number.")
    parameter_cd: str = Field(
        ...,
        min_length=5,
        max_length=5,
        pattern=r"^\d{5}$",
        description="NWIS parameterCd, e.g. 00060 (discharge) or 63680 (turbidity).",
    )
    horizon_hours: int = Field(default=24, ge=1, le=168, description="Forecast horizon in hours (recursive steps).")
    iv_csv_path: str | None = Field(
        default=None,
        description="Optional IV CSV path; default ai_service/data/usgs_puget_iv.csv; relative paths are under ai_service.",
    )


class ForecastSeriesRequest(ForecastRequest):
    history_days: int = Field(default=30, ge=1, le=90, description="History window in days for charting.")


class SiteParamAnomalyIvRequest(BaseModel):
    """On-demand single-site, single-parameter (00060/63680) IV anomaly detection."""

    site_no: str = Field(..., min_length=1)
    parameter_cd: str = Field(
        ...,
        min_length=5,
        max_length=5,
        pattern=r"^\d{5}$",
        description="Only 00060 (discharge) or 63680 (turbidity).",
    )
    iv_csv_path: str | None = Field(default=None)


class UsgsIvLatestCoreRequest(BaseModel):
    """Latest row from IV wide table with all five core parameters present for a site."""

    site_no: str = Field(..., min_length=1, description="USGS site number.")
    iv_csv_path: str | None = Field(
        default=None,
        description="Optional IV path; default same as forecast; relative to ai_service directory.",
    )


class TurbidityThresholdBatchRequest(BaseModel):
    """Read up to two latest raw 63680 points per site (no hourly resampling)."""

    site_nos: list[str] = Field(..., min_length=1, description="USGS site numbers.")
    iv_csv_path: str | None = Field(
        default=None,
        description="Optional IV path; default same as forecast.",
    )


class SitesWith63680Request(BaseModel):
    """List site numbers that have at least one parseable 63680 in IV."""

    iv_csv_path: str | None = Field(
        default=None,
        description="Optional IV path; default same as forecast.",
    )


class TurbidityStateMonitorRequest(BaseModel):
    """Run full four-state pipeline (labels, holdout warning metrics, optional artifacts)."""

    site_no: str = Field(default=DEFAULT_SITE_NO, min_length=1)
    features_csv_path: str | None = Field(
        default=None,
        description="Hourly features CSV (63680 + optional exog); default Cedar 12117500 2022+ file.",
    )
    out_dir: str | None = Field(
        default=None,
        description="If set, write hourly_states.csv, state_thresholds.json, summary.json, states_timeline.png.",
    )
    holdout_fraction: float = Field(default=0.2, gt=0.0, lt=1.0)
    holdout_min_hours: int = Field(default=336, ge=24)
    recovery_window_hours: int = Field(default=48, ge=1, le=168)
    thresholds_json_path: str | None = Field(
        default=None,
        description="Reuse frozen thresholds JSON instead of re-estimating on tuning segment.",
    )
    absolute_ntu_critical: float | None = Field(
        default=None,
        description="CRITICAL tier absolute NTU floor when estimating thresholds (default 50).",
    )
    write_plot: bool = Field(default=False, description="Only applies when out_dir is set.")


class SiteParamMultivarAnomalyRequest(BaseModel):
    """On-demand multivariate IF at one hour on the turbidity features CSV (12117500 wiring)."""

    site_no: str = Field(default=DEFAULT_SITE_NO, min_length=1)
    features_csv_path: str | None = Field(default=None)
    reference_utc: str | None = Field(
        default=None,
        description="ISO UTC hour; default latest hour in features CSV.",
    )


class TurbidityRiskForecast12hRequest(BaseModel):
    """12h turbidity alert-risk forecast (Phase B persistence; site 12117500 only)."""

    site_no: str = Field(default=DEFAULT_SITE_NO, min_length=1)
    features_csv_path: str | None = Field(
        default=None,
        description="Hourly features CSV; default Cedar 12117500 2022+ upstream file.",
    )
    thresholds_json_path: str | None = Field(
        default=None,
        description="Frozen state_thresholds.json; default reports/turbidity_state/12117500_v2.",
    )
    reference_utc: str | None = Field(
        default=None,
        description="ISO UTC hour; default latest hour in features CSV.",
    )


class TurbidityStateSnapshotRequest(BaseModel):
    """Current state and rule warning flags at one reference hour (default: latest)."""

    site_no: str = Field(default=DEFAULT_SITE_NO, min_length=1)
    features_csv_path: str | None = Field(default=None)
    thresholds_json_path: str | None = Field(
        default=None,
        description="Frozen thresholds; if omitted, estimated from tuning segment of features CSV.",
    )
    reference_utc: str | None = Field(
        default=None,
        description="ISO UTC hour for cutoff; default latest hour in features CSV.",
    )
    absolute_ntu_critical: float | None = Field(
        default=None,
        description="CRITICAL tier absolute NTU floor when estimating thresholds (default 50).",
    )


class DiscoverPugetSitesRequest(BaseModel):
    """
    Query NWIS IV inside a Puget / greater-Seattle bounding box for sites that have all core
    parameters in the lookback window, then append **new** site_no rows to ``usgs_puget_default_sites.json``.
    """

    days: int = Field(default=30, ge=1, le=90, description="IV lookback window (period=P{days}D).")
    dry_run: bool = Field(default=False, description="If true, do not write the JSON config file.")
    merge_into_config: bool = Field(
        default=True,
        description="If false, only return discovery stats without merging into the config file.",
    )
    max_new: int = Field(
        default=80,
        ge=1,
        le=500,
        description="Safety cap: at most this many newly discovered sites appended per run.",
    )
    bbox: list[float] | None = Field(
        default=None,
        description="Optional [west, south, east, north] in decimal degrees; default is greater Seattle / Puget Sound.",
    )

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return None
        if len(v) != 4:
            raise ValueError("bbox must contain exactly 4 values: west, south, east, north")
        return v


def _resolve_iv_csv(p: str | None) -> Path:
    if p is None or (isinstance(p, str) and not p.strip()):
        return _DEFAULT_IV_CSV
    path = Path(p.strip())
    if path.is_absolute():
        return path
    return _AI_SERVICE_ROOT / path


def _resolve_features_csv(p: str | None) -> Path:
    if p is None or (isinstance(p, str) and not p.strip()):
        return DEFAULT_FEATURES_CSV
    path = Path(p.strip())
    if path.is_absolute():
        return path
    return _AI_SERVICE_ROOT / path


def _resolve_optional_path(p: str | None) -> Path | None:
    if p is None or not str(p).strip():
        return None
    path = Path(p.strip())
    if path.is_absolute():
        return path
    return _AI_SERVICE_ROOT / path


@app.get("/usgs/site/{site_no}/verify")
def verify_usgs_site(site_no: str) -> dict[str, Any]:
    """
    Query NWIS Site File for existence of ``site_no``.
    Used by Java before saving ``monitor_station.external_id``; does not touch any database.
    """
    return nwis_site_verify_json(site_no)


@app.post("/refresh/usgs-iv")
def refresh_usgs_iv(
    body: Annotated[UsgsIvRefreshRequest | None, Body()] = None,
) -> dict[str, Any]:
    """
    Pull USGS IV, merge, and **overwrite** ``data/usgs_puget_iv.csv`` (same as CLI; file does not grow unbounded).
    """
    eff = body if body is not None else UsgsIvRefreshRequest()
    try:
        return run_fetch(
            days=eff.days,
            extra_site_nos=eff.extra_site_nos,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"NWIS fetch or file write failed: {e}",
        ) from e


@app.post("/forecast")
def forecast(body: ForecastRequest) -> dict[str, Any]:
    """
    Lagged Ridge on hourly series for one site and one ``parameter_cd``; recursive ``horizon_hours``-step forecast.
    Sets ``forecast_available=false`` when history is insufficient.
    """
    csv_path = _resolve_iv_csv(body.iv_csv_path)
    return forecast_from_iv_csv(
        csv_path,
        site_no=body.site_no,
        parameter_cd=body.parameter_cd,
        horizon_hours=body.horizon_hours,
    )


@app.post("/forecast/series")
def forecast_series(body: ForecastSeriesRequest) -> dict[str, Any]:
    """Return history series plus forecast series for charts (solid history, dashed forecast)."""
    csv_path = _resolve_iv_csv(body.iv_csv_path)
    return forecast_series_from_iv_csv(
        csv_path,
        site_no=body.site_no,
        parameter_cd=body.parameter_cd,
        horizon_hours=body.horizon_hours,
        history_days=body.history_days,
    )


@app.post("/anomaly/site-param-multivar-from-features")
def anomaly_site_param_multivar_from_features(body: SiteParamMultivarAnomalyRequest) -> dict[str, Any]:
    """
    Multivariate IsolationForest on 63680 + precipitation + upstream discharge at one hour.

    Same model as offline tier-vs-multivar eval; no exog forward-fill at scoring time.
    """
    features_path = _resolve_features_csv(body.features_csv_path)
    if not features_path.is_file():
        raise HTTPException(status_code=400, detail=f"features CSV not found: {features_path}")
    try:
        return site_param_multivar_anomaly_from_features(
            features_path,
            site_no=body.site_no.strip(),
            reference_utc=body.reference_utc,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/anomaly/site-param-from-iv")
def anomaly_site_param_from_iv(body: SiteParamAnomalyIvRequest) -> dict[str, Any]:
    """
    Fit univariate IsolationForest on IV hourly series for 00060/63680 per site.
    Returns HTTP 200 with ``anomaly_available=false`` when data are insufficient (no 4xx for uniform UI handling).
    """
    csv_path = _resolve_iv_csv(body.iv_csv_path)
    return site_param_anomaly_from_iv_csv(
        csv_path,
        site_no=body.site_no,
        parameter_cd=body.parameter_cd,
    )


@app.post("/usgs/iv/turbidity-threshold-batch")
def usgs_iv_turbidity_threshold_batch(body: TurbidityThresholdBatchRequest) -> dict[str, Any]:
    """
    One IV read: up to two latest 63680 points per site; two-point threshold rule runs in Java.
    """
    csv_path = _resolve_iv_csv(body.iv_csv_path)
    return turbidity_threshold_batch_sites(csv_path, body.site_nos)


@app.post("/usgs/iv/sites-with-63680")
def usgs_iv_sites_with_63680(
    body: Annotated[SitesWith63680Request | None, Body()] = None,
) -> dict[str, Any]:
    """Site numbers that have at least one parseable turbidity (63680) in IV."""
    eff = body if body is not None else SitesWith63680Request()
    csv_path = _resolve_iv_csv(eff.iv_csv_path)
    return {"site_nos": site_nos_with_nonnull_63680(csv_path)}


@app.post("/turbidity/state/monitor")
def turbidity_state_monitor(body: TurbidityStateMonitorRequest) -> dict[str, Any]:
    """
    Turbidity monitoring: quality tiers (NORMAL/WATCH/HIGH/CRITICAL), gap tiers
    (SENSOR_GAP/DATA_STALE/UNKNOWN), and legacy four-state labels.

    Computes tuning-frozen thresholds, hourly labels, holdout warning metrics (h=6,12),
    never-alert baseline, and optional report artifacts under ``out_dir``.
    """
    features_path = _resolve_features_csv(body.features_csv_path)
    if not features_path.is_file():
        raise HTTPException(status_code=400, detail=f"features CSV not found: {features_path}")
    thr_path = _resolve_optional_path(body.thresholds_json_path)
    out_path = _resolve_optional_path(body.out_dir)
    abs_crit = (
        float(body.absolute_ntu_critical)
        if body.absolute_ntu_critical is not None
        else DEFAULT_ABSOLUTE_NTU_CRITICAL
    )
    try:
        return run_state_monitoring(
            features_path,
            site_no=body.site_no.strip(),
            holdout_fraction=body.holdout_fraction,
            holdout_min_hours=body.holdout_min_hours,
            recovery_window_hours=body.recovery_window_hours,
            out_dir=out_path,
            write_plot=body.write_plot,
            thresholds_json=thr_path,
            absolute_ntu_critical=abs_crit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _run_turbidity_risk_forecast_12h(body: TurbidityRiskForecast12hRequest) -> dict[str, Any]:
    """Shared Phase B forecast path for risk-forecast-12h and risk-explain."""
    features_path = _resolve_features_csv(body.features_csv_path)
    thr_path = _resolve_optional_path(body.thresholds_json_path) or DEFAULT_THRESHOLDS_JSON
    return run_risk_forecast_12h(
        site_no=body.site_no.strip(),
        features_csv=features_path,
        thresholds_json=thr_path,
        reference_utc=body.reference_utc,
    )


@app.post("/turbidity/risk-forecast-12h")
def turbidity_risk_forecast_12h(body: TurbidityRiskForecast12hRequest) -> dict[str, Any]:
    """
    12h turbidity RISK forecast (not NTU curve): persistence alert + max tier.

    Uses features CSV with precip no-ffill and upstream ffill; frozen v2.1 thresholds.
    """
    try:
        return _run_turbidity_risk_forecast_12h(body)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/turbidity/risk-explain")
def turbidity_risk_explain(body: TurbidityRiskForecast12hRequest) -> dict[str, Any]:
    """
    12h turbidity risk forecast plus LLM explanation_text (L1; decision fields frozen).

    Calls ``run_risk_forecast_12h`` first, then appends ``explanation_text`` without
    modifying ``recommend_alert``, ``max_tier_forecast``, or related decision fields.
    """
    try:
        frozen = _run_turbidity_risk_forecast_12h(body)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    cfg = load_assistant_config()
    if not cfg.enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "assistant_disabled",
                "message": "Assistant LLM is not enabled or configured.",
                "assistant_enabled": cfg.master_enabled,
                "llm_configured": cfg.llm_configured,
            },
        )

    try:
        return generate_risk_explanation(frozen, config=cfg)
    except RuntimeError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": "llm_completion_failed", "message": str(e)},
        ) from e


@app.post("/turbidity/state/snapshot")
def turbidity_state_snapshot(body: TurbidityStateSnapshotRequest) -> dict[str, Any]:
    """
    Point-in-time alert tier, legacy state, and rule warning flags at horizons 6h and 12h.

    Uses the same rules as batch monitoring; does not write files.
    """
    features_path = _resolve_features_csv(body.features_csv_path)
    if not features_path.is_file():
        raise HTTPException(status_code=400, detail=f"features CSV not found: {features_path}")
    thr_path = _resolve_optional_path(body.thresholds_json_path)
    try:
        df = load_features(features_path)
        y = df["63680"]
        prec = df["precipitation_mm"] if "precipitation_mm" in df.columns else None
        q_up = df[UPSTREAM_DISCHARGE_COL] if UPSTREAM_DISCHARGE_COL in df.columns else None
        n = len(y)
        split_info = _split_index_for_holdout(
            n,
            max_horizon=max(WARNING_HORIZONS),
            holdout_fraction=0.2,
            holdout_min_hours=336,
            min_tuning_hours=2000,
        )
        split_ix = int(split_info["split_index"])
        tuning_mask = pd.Series(y.index < y.index[split_ix], index=y.index)
        abs_crit = (
            float(body.absolute_ntu_critical)
            if body.absolute_ntu_critical is not None
            else DEFAULT_ABSOLUTE_NTU_CRITICAL
        )
        if thr_path is not None and thr_path.is_file():
            thresholds = json.loads(thr_path.read_text(encoding="utf-8"))
        else:
            thresholds = compute_thresholds(
                y,
                prec,
                q_up,
                tuning_mask,
                recovery_window_hours=48,
                absolute_ntu_critical=abs_crit,
            )
        if "tier_rules" not in thresholds:
            thresholds["tier_rules"] = build_tier_rules_metadata(thresholds)
        states = label_states(y, thresholds)
        alert_tiers = label_alert_tier(y, thresholds)
        ref = None
        if body.reference_utc and body.reference_utc.strip():
            ref = pd.Timestamp(body.reference_utc.strip())
        return snapshot_at_reference(
            df,
            thresholds,
            states,
            y,
            prec,
            q_up,
            alert_tiers=alert_tiers,
            ref_utc_hour=ref,
            site_no=body.site_no.strip(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/config/puget-default-sites")
def get_puget_default_sites() -> dict[str, Any]:
    """Current merged Puget demo site list (same file used by IV fetch and the monitor UI)."""
    path = _DEFAULT_PUGET_SITES_JSON
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Config not found: {path}")
    try:
        return load_puget_config(path)
    except OSError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot read Puget sites config (permissions or I/O): {path} — {e}",
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=503, detail=f"Invalid Puget sites JSON: {e}") from e


@app.post("/maintenance/discover-puget-sites")
def maintenance_discover_puget_sites(
    body: Annotated[DiscoverPugetSitesRequest | None, Body()] = None,
) -> dict[str, Any]:
    """
    Discover IV sites in the Puget bbox with all core parameters; optionally merge new site_no entries into config.

    Run periodically or after USGS adds instrumentation — not automatic unless you schedule this endpoint.
    """
    eff = body if body is not None else DiscoverPugetSitesRequest()
    bbox_t: tuple[float, float, float, float] = (
        tuple(eff.bbox) if eff.bbox is not None else DEFAULT_PUGET_BBOX
    )
    try:
        discovered, names, coords = discover_core_sites_in_bbox(
            bbox_t,
            days=eff.days,
            params=DEFAULT_CORE_PARAMS,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NWIS discovery failed: {e}") from e

    intersection_count = len(discovered)
    dry_effective = (not eff.merge_into_config) or eff.dry_run
    merge_result = merge_new_sites_into_config(
        _DEFAULT_PUGET_SITES_JSON,
        discovered,
        names,
        coords,
        dry_run=dry_effective,
        max_new=eff.max_new,
    )

    return {
        "bbox": list(bbox_t),
        "days": eff.days,
        "params": list(DEFAULT_CORE_PARAMS),
        "intersection_count": intersection_count,
        "merge": merge_result,
    }


@app.post("/usgs/iv/latest-core-params")
def usgs_iv_latest_core_params(body: UsgsIvLatestCoreRequest) -> dict[str, Any]:
    """
    Latest IV row per site where 00010/00400/00300/00095/63680 are all present.
    Returns 400 if data incomplete.
    """
    csv_path = _resolve_iv_csv(body.iv_csv_path)
    try:
        return latest_complete_core_snapshot(csv_path, body.site_no)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
