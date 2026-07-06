#!/usr/bin/env python3
"""
训练 USGS 参数异常检测模型（Isolation Forest）。
默认把 Excellent/Good 视为正常样本。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

FEATURES = ["00010", "00400", "00300", "00095", "63680"]
MODEL_VERSION = "usgs-iforest-v1"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train USGS anomaly model")
    p.add_argument("--input", default=str(Path(__file__).resolve().parent / "data" / "usgs_ml_training_v2_90d.csv"))
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "usgs_anomaly_iforest_v1.pkl"))
    p.add_argument("--metrics-out", default=str(Path(__file__).resolve().parent / "data" / "usgs_anomaly_metrics_v1.json"))
    p.add_argument("--threshold-quantile", type=float, default=0.95)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    need = FEATURES + ["Pollution_Level"]
    for c in need:
        if c not in df.columns:
            raise SystemExit(f"missing column: {c}")
    work = df.dropna(subset=FEATURES).copy()
    normal = work[work["Pollution_Level"].isin(["Excellent", "Good"])].copy()
    if len(normal) < 500:
        raise SystemExit(f"normal samples too few: {len(normal)}")

    X = normal[FEATURES].astype(float).values
    scaler = RobustScaler()
    Xs = scaler.fit_transform(X)
    model = IsolationForest(
        n_estimators=300,
        contamination="auto",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(Xs)
    scores = -model.score_samples(Xs)  # higher -> more anomalous
    threshold = float(np.quantile(scores, args.threshold_quantile))
    imputation_defaults = {f: float(normal[f].median()) for f in FEATURES}

    artifact = {
        "version": MODEL_VERSION,
        "features": FEATURES,
        "scaler": scaler,
        "model": model,
        "threshold": threshold,
        "threshold_quantile": args.threshold_quantile,
        "normal_rows": int(len(normal)),
        "total_rows": int(len(work)),
        "imputation_defaults": imputation_defaults,
    }
    joblib.dump(artifact, args.out)

    metrics = {
        "version": MODEL_VERSION,
        "features": FEATURES,
        "total_rows": int(len(work)),
        "normal_rows": int(len(normal)),
        "threshold": threshold,
        "threshold_quantile": args.threshold_quantile,
        "score_mean": float(scores.mean()),
        "score_p95": float(np.quantile(scores, 0.95)),
        "score_p99": float(np.quantile(scores, 0.99)),
    }
    out = Path(args.metrics_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved model: {Path(args.out).resolve()}")
    print(f"saved metrics: {out.resolve()}")


if __name__ == "__main__":
    main()
