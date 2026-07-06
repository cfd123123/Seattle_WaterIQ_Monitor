"""Unit tests for turbidity gap report."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from models.turbidity_gap_report import (
    flood_window_summary,
    monthly_validity_table,
    run_gap_report,
)


def test_monthly_validity_table_counts() -> None:
    idx = pd.date_range("2024-01-01", periods=48, freq="h", tz="UTC")
    y = pd.Series([1.0] * 40 + [np.nan] * 8, index=idx)
    monthly = monthly_validity_table(y)
    assert len(monthly) == 1
    assert monthly.iloc[0]["grid_hours"] == 48
    assert monthly.iloc[0]["y_valid_n"] == 40
    assert monthly.iloc[0]["y_missing_rate"] == round(8 / 48, 6)


def test_flood_window_summary() -> None:
    idx = pd.date_range("2025-12-09", periods=24 * 9, freq="h", tz="UTC")
    y = pd.Series(np.nan, index=idx)
    y.iloc[0] = 5.5
    y.iloc[10] = 12.0
    out = flood_window_summary(y)
    assert out["grid_hours"] == len(idx)
    assert out["y_valid_n"] == 2
    assert out["y_max_if_valid"] == 12.0
    assert "missing" in out["note"].lower()


def test_run_gap_report_writes_artifacts() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        csv = td_path / "feat.csv"
        idx = pd.date_range("2022-01-01", periods=5000, freq="h", tz="UTC")
        df = pd.DataFrame(
            {
                "datetime_utc": idx,
                "63680": np.linspace(1.0, 2.0, len(idx)),
                "precipitation_mm": np.zeros(len(idx)),
                "upstream_discharge_cfs_12116400": np.linspace(100, 200, len(idx)),
            }
        )
        df.to_csv(csv, index=False)
        out = td_path / "out"
        report = run_gap_report(csv, out_dir=out, write_plot=False)
        assert (out / "gap_report.json").is_file()
        assert (out / "gap_report_monthly.csv").is_file()
        loaded = json.loads((out / "gap_report.json").read_text(encoding="utf-8"))
        assert loaded["segments"]["full"]["y_missing_rate"] == 0.0
        assert report["segments"]["tuning"]["grid_hours"] > 0
