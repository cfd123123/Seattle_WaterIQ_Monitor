"""Smoke tests for POST /turbidity/risk-explain (MVP-1 L1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from assistant.explain_turbidity import generate_risk_explanation
from assistant.llm_client import CompletionResult
from main import app
from models.turbidity_risk_forecast_12h import run_risk_forecast_12h
from models.turbidity_state_monitoring import build_tier_rules_metadata


def _synthetic_features_csv(path: Path, n: int = 200) -> None:
    idx = pd.date_range("2024-06-01", periods=n, freq="h", tz="UTC")
    y = np.ones(n) * 0.5
    y[150:160] = 12.0
    df = pd.DataFrame(
        {
            "datetime_utc": idx,
            "63680": y,
            "precipitation_mm": np.zeros(n),
            "upstream_discharge_cfs_12116400": np.linspace(100, 200, n),
        }
    )
    df.to_csv(path, index=False)


def _thresholds_json(path: Path, csv: Path) -> None:
    thr = {
        "model_version": "turbidity-state-v2.1-test",
        "site_no": "12117500",
        "features_csv": str(csv.resolve()),
        "tier_rules": build_tier_rules_metadata(
            {
                "theta_low": 1.0,
                "theta_high": 2.0,
                "delta_up_1h": 0.1,
                "y_tuning_p90": 2.0,
                "y_tuning_p95": 4.0,
                "y_tuning_p99": 10.0,
                "delta_up_P90": 0.3,
                "absolute_ntu_critical": 50.0,
            }
        ),
    }
    path.write_text(json.dumps(thr), encoding="utf-8")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def forecast_paths(tmp_path: Path) -> dict[str, Path]:
    csv = tmp_path / "feat.csv"
    thr = tmp_path / "thr.json"
    _synthetic_features_csv(csv)
    _thresholds_json(thr, csv)
    return {"csv": csv, "thr": thr}


def _mock_complete(_messages: list[dict[str, str]]) -> CompletionResult:
    return CompletionResult(
        text=(
            "Site 12117500 is currently at NORMAL tier. "
            "The 12-hour forecast remains NORMAL with no alert recommended."
        ),
        model="qwen2.5:3b",
        provider="ollama",
    )


def test_risk_explain_preserves_decision_fields(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    forecast_paths: dict[str, Path],
) -> None:
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_LLM_MODEL", "qwen2.5:3b")
    monkeypatch.delenv("ASSISTANT_LLM_API_KEY", raising=False)

    frozen = run_risk_forecast_12h(
        features_csv=forecast_paths["csv"],
        thresholds_json=forecast_paths["thr"],
        reference_utc="2024-06-01T05:00:00+00:00",
    )

    def _patched_generate(frozen_in: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return generate_risk_explanation(frozen_in, complete_fn=_mock_complete)

    monkeypatch.setattr("main.generate_risk_explanation", _patched_generate)

    response = client.post(
        "/turbidity/risk-explain",
        json={
            "site_no": "12117500",
            "features_csv_path": str(forecast_paths["csv"]),
            "thresholds_json_path": str(forecast_paths["thr"]),
            "reference_utc": "2024-06-01T05:00:00+00:00",
        },
    )
    assert response.status_code == 200
    body = response.json()

    for key in (
        "recommend_alert",
        "max_tier_forecast",
        "tier_at_t",
        "alert_12h_forecast",
        "rationale_template_key",
    ):
        assert body[key] == frozen[key]

    assert body["explanation_text"]
    assert "NORMAL tier" in body["explanation_text"]
    assert body["explanation_model"] == "qwen2.5:3b"
    assert body["explanation_provider"] == "ollama"
    assert body["sources"] == [{"type": "api", "ref": "python:/turbidity/risk-forecast-12h"}]


def test_risk_explain_assistant_disabled_returns_503(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    forecast_paths: dict[str, Path],
) -> None:
    monkeypatch.setenv("ASSISTANT_ENABLED", "false")

    response = client.post(
        "/turbidity/risk-explain",
        json={
            "site_no": "12117500",
            "features_csv_path": str(forecast_paths["csv"]),
            "thresholds_json_path": str(forecast_paths["thr"]),
            "reference_utc": "2024-06-01T05:00:00+00:00",
        },
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "assistant_disabled"


def test_risk_explain_wrong_site_returns_400(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    forecast_paths: dict[str, Path],
) -> None:
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")

    response = client.post(
        "/turbidity/risk-explain",
        json={
            "site_no": "99999999",
            "features_csv_path": str(forecast_paths["csv"]),
            "thresholds_json_path": str(forecast_paths["thr"]),
        },
    )
    assert response.status_code == 400


def test_merge_ignores_llm_decision_override() -> None:
    frozen = {
        "site_no": "12117500",
        "recommend_alert": False,
        "max_tier_forecast": "NORMAL",
        "tier_at_t": "NORMAL",
        "alert_12h_forecast": 0,
    }
    out = generate_risk_explanation(
        frozen,
        complete_fn=lambda _m: CompletionResult(
            text="recommend_alert should be true; max_tier_forecast should be HIGH.",
            model="mock",
            provider="openai",
        ),
    )
    assert out["recommend_alert"] is False
    assert out["max_tier_forecast"] == "NORMAL"
    assert out["tier_at_t"] == "NORMAL"
    assert out["alert_12h_forecast"] == 0
    assert out["explanation_text"]
