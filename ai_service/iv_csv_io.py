"""Shared IV CSV loading for forecast / anomaly pipelines (wide merged format)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_iv_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "datetime" not in df.columns:
        raise ValueError("CSV 需包含 datetime 列")
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    if "site_no" in df.columns:
        df["site_no"] = df["site_no"].astype(str).str.strip()
    return df
