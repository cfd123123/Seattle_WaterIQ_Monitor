"""
短时预测：基于 USGS IV 导出的 CSV（fetch_usgs_puget_sound.py），按站点 + parameter_cd 建小时序列，
用滞后特征的 Ridge 回归做逐步递归外推（MVP，非业务预报承诺）。

与 11 项规则评分解耦；冷启动：历史小时点数不足则 forecast_available=false。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

FORECAST_MODEL_VERSION = "forecast-ridge-recursive-v1"
MIN_HOURLY_POINTS = 48
MAX_HORIZON_HOURS = 168
MAX_LAG = 36


def load_hourly_series(csv_path: Path, site_no: str, parameter_cd: str) -> pd.Series:
    """读取 IV CSV，筛选站点，将指定 parameter 列重采样为 1h 均值序列（UTC 索引）。"""
    if not csv_path.is_file():
        return pd.Series(dtype=float)
    df = pd.read_csv(csv_path)
    if "datetime" not in df.columns or "site_no" not in df.columns:
        return pd.Series(dtype=float)
    if parameter_cd not in df.columns:
        return pd.Series(dtype=float)
    sub = df[df["site_no"].astype(str).str.strip() == str(site_no).strip()].copy()
    if sub.empty:
        return pd.Series(dtype=float)
    sub["datetime"] = pd.to_datetime(sub["datetime"], utc=True, errors="coerce")
    sub = sub.dropna(subset=["datetime"])
    s = sub.set_index("datetime")[parameter_cd].astype(float)
    s = s.sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s = s.resample("1h").mean()
    s = s.dropna()
    return s


def _build_lag_dataset(y: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(y)
    rows_x: list[np.ndarray] = []
    rows_y: list[float] = []
    for i in range(lag, n):
        rows_x.append(y[i - lag : i])
        rows_y.append(y[i])
    if not rows_y:
        return np.empty((0, lag)), np.empty((0,))
    return np.stack(rows_x, axis=0), np.asarray(rows_y, dtype=float)


def _fit_and_predict_recursive(
    y: np.ndarray,
    horizon: int,
    max_lag: int,
) -> tuple[float | None, str | None]:
    """返回 horizon 步后的预测值；失败时 (None, reason_code)。"""
    n = len(y)
    if n < MIN_HOURLY_POINTS:
        return None, "insufficient_history"
    lag = min(max_lag, n // 3, n - 10)
    lag = max(lag, 6)
    if n < lag + 5:
        return None, "insufficient_history"

    X, y_tr = _build_lag_dataset(y, lag)
    if X.shape[0] < 20:
        return None, "insufficient_history"

    try:
        model = Ridge(alpha=2.0)
        model.fit(X, y_tr)
    except ValueError:
        return None, "fit_failed"

    window = y[-lag:].astype(float).copy()
    last_pred = float(window[-1])
    for _ in range(horizon):
        pred = float(model.predict(window.reshape(1, -1))[0])
        last_pred = pred
        window = np.append(window[1:], pred)
    return last_pred, None


def forecast_from_iv_csv(
    csv_path: Path,
    site_no: str,
    parameter_cd: str,
    horizon_hours: int,
) -> dict[str, Any]:
    """
    :param csv_path: fetch_usgs_puget_sound 产出的合并 CSV
    :return: 统一字典，含 forecast_available、forecast_value、model_version 等
    """
    site_no = str(site_no).strip()
    parameter_cd = str(parameter_cd).strip()
    h = int(horizon_hours)
    if h < 1 or h > MAX_HORIZON_HOURS:
        return {
            "site_no": site_no,
            "parameter_cd": parameter_cd,
            "horizon_hours": h,
            "forecast_available": False,
            "forecast_value": None,
            "model_version": FORECAST_MODEL_VERSION,
            "data_points_used": 0,
            "reason": "invalid_horizon",
        }

    s = load_hourly_series(csv_path, site_no, parameter_cd)
    if s.empty:
        return {
            "site_no": site_no,
            "parameter_cd": parameter_cd,
            "horizon_hours": h,
            "forecast_available": False,
            "forecast_value": None,
            "model_version": FORECAST_MODEL_VERSION,
            "data_points_used": 0,
            "reason": "no_series_or_column",
        }

    y = s.values.astype(float)
    n = len(y)
    pred, err = _fit_and_predict_recursive(y, h, MAX_LAG)
    if pred is None:
        return {
            "site_no": site_no,
            "parameter_cd": parameter_cd,
            "horizon_hours": h,
            "forecast_available": False,
            "forecast_value": None,
            "model_version": FORECAST_MODEL_VERSION,
            "data_points_used": n,
            "reason": err or "forecast_unavailable",
        }

    return {
        "site_no": site_no,
        "parameter_cd": parameter_cd,
        "horizon_hours": h,
        "forecast_available": True,
        "forecast_value": round(pred, 4),
        "model_version": FORECAST_MODEL_VERSION,
        "data_points_used": n,
        "reason": None,
        "series_last_timestamp": s.index[-1].isoformat(),
    }


def forecast_series_from_iv_csv(
    csv_path: Path,
    site_no: str,
    parameter_cd: str,
    horizon_hours: int,
    history_days: int = 30,
) -> dict[str, Any]:
    """
    返回“历史实线 + 未来虚线”所需数据：
    - history_points: 最近 history_days 天的小时序列
    - forecast_points: 从下一小时起的递归多步预测序列（1..horizon）
    """
    base = forecast_from_iv_csv(csv_path, site_no, parameter_cd, horizon_hours)
    site_no = str(site_no).strip()
    parameter_cd = str(parameter_cd).strip()
    h = int(horizon_hours)
    d = int(history_days)
    if d < 1 or d > 90:
        d = 30

    s = load_hourly_series(csv_path, site_no, parameter_cd)
    if s.empty:
        base["history_points"] = []
        base["forecast_points"] = []
        base["history_days"] = d
        return base

    hist = s[s.index >= (s.index[-1] - pd.Timedelta(days=d))]
    history_points = [
        {"timestamp": ts.isoformat(), "value": round(float(v), 4)}
        for ts, v in hist.items()
    ]
    base["history_points"] = history_points
    base["history_days"] = d

    if not bool(base.get("forecast_available")):
        base["forecast_points"] = []
        return base

    y = s.values.astype(float)
    n = len(y)
    lag = min(MAX_LAG, n // 3, n - 10)
    lag = max(lag, 6)
    X, y_tr = _build_lag_dataset(y, lag)
    if X.shape[0] < 20:
        base["forecast_points"] = []
        return base

    model = Ridge(alpha=2.0)
    model.fit(X, y_tr)
    window = y[-lag:].astype(float).copy()
    last_ts = s.index[-1]
    pred_points: list[dict[str, Any]] = []
    for step in range(1, h + 1):
        pred = float(model.predict(window.reshape(1, -1))[0])
        window = np.append(window[1:], pred)
        pred_points.append(
            {
                "timestamp": (last_ts + pd.Timedelta(hours=step)).isoformat(),
                "value": round(pred, 4),
            }
        )
    base["forecast_points"] = pred_points
    return base


def _self_test() -> None:
    rng = np.random.default_rng(0)
    t = 120
    x = np.arange(t, dtype=float)
    y = 100 + 0.1 * x + rng.normal(0, 2, size=t)
    p, e = _fit_and_predict_recursive(y, horizon=6, max_lag=24)
    assert e is None and p is not None
    path = Path(__file__).resolve().parent / "data" / "usgs_puget_iv.csv"
    if path.is_file():
        out = forecast_from_iv_csv(path, "12117000", "00060", 12)
        assert "forecast_available" in out


if __name__ == "__main__":
    _self_test()
    print("forecast_engine self-test ok")
