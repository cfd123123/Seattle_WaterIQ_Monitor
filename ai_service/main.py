"""
FastAPI service: USGS IV short-horizon forecast, IV maintenance, anomaly helpers, and turbidity batch reads.

- IV CSV refresh: ``POST /refresh/usgs-iv`` overwrites ``data/usgs_puget_iv.csv``.
- Short-horizon forecast: ``POST /forecast``, ``POST /forecast/series`` (``forecast_engine``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel, Field

from fetch_usgs_puget_sound import run_fetch
from usgs_site_verify import nwis_site_verify_json
from forecast_engine import forecast_from_iv_csv, forecast_series_from_iv_csv
from usgs_iv_core_snapshot import latest_complete_core_snapshot
from site_param_anomaly_on_demand import site_param_anomaly_from_iv_csv
from turbidity_threshold_iv import site_nos_with_nonnull_63680, turbidity_threshold_batch_sites

app = FastAPI(title="USGS IV Forecast & Maintenance")

_DEFAULT_IV_CSV = Path(__file__).resolve().parent / "data" / "usgs_puget_iv.csv"


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


def _resolve_iv_csv(p: str | None) -> Path:
    if p is None or (isinstance(p, str) and not p.strip()):
        return _DEFAULT_IV_CSV
    path = Path(p.strip())
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


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


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


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
