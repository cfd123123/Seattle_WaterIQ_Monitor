#!/usr/bin/env python3
"""
训练 USGS-only 分类模型（v1）。
输入列：00010,00400,00300,00095,63680 + Pollution_Level
按时间切分训练/验证，避免随机泄漏。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import LabelEncoder

FEATURES = ["00010", "00400", "00300", "00095", "63680"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train USGS-only ML model")
    p.add_argument(
        "--input",
        default=str(Path(__file__).resolve().parent / "data" / "usgs_ml_training_v1.csv"),
    )
    p.add_argument(
        "--model-out",
        default=str(Path(__file__).resolve().parent / "usgs_ml_model_v1.pkl"),
    )
    p.add_argument(
        "--encoder-out",
        default=str(Path(__file__).resolve().parent / "usgs_ml_label_encoder_v1.pkl"),
    )
    p.add_argument(
        "--metrics-out",
        default=str(Path(__file__).resolve().parent / "data" / "usgs_ml_metrics_v1.json"),
    )
    p.add_argument("--train-ratio", type=float, default=0.8)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    if df.empty:
        raise SystemExit("训练数据为空")
    for c in [*FEATURES, "Pollution_Level", "datetime"]:
        if c not in df.columns:
            raise SystemExit(f"缺少列: {c}")

    work = df.dropna(subset=FEATURES + ["Pollution_Level"]).copy()
    work["datetime"] = pd.to_datetime(work["datetime"], utc=True, errors="coerce")
    work = work.dropna(subset=["datetime"]).sort_values("datetime")
    if len(work) < 200:
        raise SystemExit(f"样本过少: {len(work)}")

    split_idx = int(len(work) * float(args.train_ratio))
    split_idx = max(100, min(split_idx, len(work) - 50))
    train_df = work.iloc[:split_idx]
    test_df = work.iloc[split_idx:]

    le = LabelEncoder()
    y_train = le.fit_transform(train_df["Pollution_Level"])
    y_test = le.transform(test_df["Pollution_Level"])

    model = RandomForestClassifier(
        n_estimators=400,
        random_state=42,
        min_samples_leaf=2,
        class_weight="balanced_subsample",
        n_jobs=-1,
    )
    model.fit(train_df[FEATURES], y_train)
    pred = model.predict(test_df[FEATURES])
    acc = float(accuracy_score(y_test, pred))
    report = classification_report(y_test, pred, target_names=list(le.classes_), output_dict=True)

    joblib.dump(model, args.model_out)
    joblib.dump(le, args.encoder_out)

    metrics = {
        "model": "usgs-ml-rf-v1",
        "features": FEATURES,
        "rows_total": int(len(work)),
        "rows_train": int(len(train_df)),
        "rows_test": int(len(test_df)),
        "train_start": str(train_df["datetime"].min()),
        "train_end": str(train_df["datetime"].max()),
        "test_start": str(test_df["datetime"].min()),
        "test_end": str(test_df["datetime"].max()),
        "accuracy": round(acc, 6),
        "classification_report": report,
    }
    out = Path(args.metrics_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"accuracy={acc:.4f}")
    print(f"model={Path(args.model_out).resolve()}")
    print(f"encoder={Path(args.encoder_out).resolve()}")
    print(f"metrics={out.resolve()}")


if __name__ == "__main__":
    main()
