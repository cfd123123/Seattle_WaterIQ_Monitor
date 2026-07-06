"""Smoke tests for GET /assistant/health (M1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from assistant.config import AssistantConfig
from assistant.health import build_health_payload
from assistant.rag.search import invalidate_rag_index
from main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_assistant_health_no_key(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    tmp_path,
) -> None:
    invalidate_rag_index()
    monkeypatch.setenv("ASSISTANT_RAG_INDEX_DIR", str(tmp_path / "rag-empty"))
    monkeypatch.delenv("ASSISTANT_LLM_API_KEY", raising=False)
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")

    response = client.get("/assistant/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["enabled"] is False
    assert body["assistant_enabled"] is False
    assert body["configured"] is False
    assert body["llm_configured"] is False
    assert body["provider"] == "none"
    assert body["model"] == "gpt-4o-mini"
    assert body["llm_reachable"] is False
    assert body["rag_index_ready"] is False


def test_assistant_health_with_api_key(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")

    response = client.get("/assistant/health")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["configured"] is True
    assert body["llm_configured"] is True
    assert body["provider"] == "openai"


def test_assistant_health_ollama_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASSISTANT_LLM_API_KEY", raising=False)
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")

    payload = build_health_payload(AssistantConfig.from_environ())
    assert payload["enabled"] is True
    assert payload["configured"] is True
    assert payload["llm_configured"] is True
    assert payload["provider"] == "ollama"


def test_assistant_health_master_switch_off(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("ASSISTANT_ENABLED", "false")

    response = client.get("/assistant/health")
    body = response.json()
    assert body["enabled"] is False
    assert body["configured"] is True
    assert body["llm_configured"] is True
