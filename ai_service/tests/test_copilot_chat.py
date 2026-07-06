"""Tests for POST /copilot/chat (MVP-2 RAG copilot)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from assistant.config import RagConfig
from assistant.copilot import answer_copilot_question
from assistant.llm_client import CompletionResult
from assistant.rag.indexer import rebuild_index
from assistant.rag.search import ensure_rag_index, invalidate_rag_index, search_ops_docs
from main import app


@pytest.fixture
def service_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def rag_config(tmp_path: Path, service_root: Path, monkeypatch: pytest.MonkeyPatch) -> RagConfig:
    index_dir = tmp_path / "rag_store"
    monkeypatch.setenv("ASSISTANT_RAG_INDEX_DIR", str(index_dir))
    monkeypatch.setenv("ASSISTANT_RAG_TOP_K", "5")
    cfg = RagConfig.from_environ()
    # Use real repo markdown sources for retrieval tests.
    assert (service_root / "docs" / "turbidity_operations.md").exists()
    return cfg


@pytest.fixture
def built_index(rag_config: RagConfig) -> RagConfig:
    invalidate_rag_index()
    rebuild_index(rag_config)
    ensure_rag_index(rag_config)
    return rag_config


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _mock_router_ops_doc(question_fragment: str = "Phase B"):
    def _mock_classify(messages: list[dict[str, str]]) -> CompletionResult:
        user = messages[-1]["content"]
        assert question_fragment in user or "Phase B" in user
        return CompletionResult(
            text='{"intent": "ops_doc", "retrieval_query": "Phase B recommend_alert online alert"}',
            model="mock-qwen",
            provider="ollama",
            usage={"prompt_tokens": 3, "completion_tokens": 2},
        )

    return _mock_classify


def _mock_complete_factory(expected_substrings: list[str]):
    def _mock_complete(messages: list[dict[str, str]]) -> CompletionResult:
        user_msg = messages[-1]["content"]
        for needle in expected_substrings:
            assert needle.lower() in user_msg.lower() or any(
                needle.lower() in part.lower() for part in user_msg.split("---")
            )
        return CompletionResult(
            text="Phase B is the online 12h alert-risk track; LLM must not change recommend_alert.",
            model="mock-qwen",
            provider="ollama",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )

    return _mock_complete


def test_search_hits_turbidity_operations(built_index: RagConfig) -> None:
    # Query tuned for ops manual §8 (Phase B online); generic "What is Phase B?" may rank plan docs higher after English indexing.
    hits = search_ops_docs("Phase B 12h alert risk online", config=built_index)
    assert hits, "expected at least one BM25 hit"
    refs = {hit.chunk.source_path for hit in hits}
    assert "docs/turbidity_operations.md" in refs
    combined = " ".join(hit.chunk.text.lower() for hit in hits)
    assert "phase b" in combined or "recommend_alert" in combined


def test_search_recommend_alert_policy(built_index: RagConfig) -> None:
    hits = search_ops_docs("Can LLM change recommend_alert?", config=built_index)
    assert hits
    combined = " ".join(hit.chunk.text.lower() for hit in hits)
    assert "recommend_alert" in combined
    assert "llm" in combined or "must not" in combined or "only" in combined or "forbidden" in combined


def test_answer_copilot_question_mock_llm(built_index: RagConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "ollama")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "true")

    payload = answer_copilot_question(
        "What is Phase B?",
        classify_fn=_mock_router_ops_doc("What is Phase B?"),
        complete_fn=_mock_complete_factory(["Phase B"]),
        config=None,
    )
    assert payload["answer"]
    assert payload["model"] == "mock-qwen"
    assert payload["provider"] == "ollama"
    assert payload["intent"] == "ops_doc"
    assert payload["retrieval_query"]
    assert len(payload["sources"]) >= 1


def test_copilot_chat_endpoint_mock_llm(
    built_index: RagConfig,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "ollama")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")

    from assistant import copilot as copilot_module

    monkeypatch.setattr(
        copilot_module,
        "answer_copilot_question",
        lambda question, site_no=None, config=None, complete_fn=None, top_k=None: {
            "answer": "LLM must not modify recommend_alert.",
            "sources": [{"type": "doc", "ref": "docs/turbidity_operations.md#9-r10-future-llm", "heading": "R10"}],
            "model": "mock-qwen",
            "provider": "ollama",
            "usage": None,
        },
    )

    response = client.post(
        "/copilot/chat",
        json={"question": "Can LLM change recommend_alert?", "site_no": "12117500"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "recommend_alert" in body["answer"]
    assert body["provider"] == "ollama"
    assert body["sources"]
    assert "turbidity_operations.md" in body["sources"][0]["ref"]


def test_copilot_chat_disabled_returns_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASSISTANT_LLM_API_KEY", raising=False)
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")

    response = client.post("/copilot/chat", json={"question": "What is Phase B?"})
    assert response.status_code == 503


def test_health_rag_index_ready_after_build(
    built_index: RagConfig,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")

    response = client.get("/assistant/health")
    assert response.status_code == 200
    assert response.json()["rag_index_ready"] is True


def test_sanitize_usage_strips_ollama_nested_nulls() -> None:
    from assistant.llm_client import LLMClient, sanitize_usage
    from assistant.config import AssistantConfig

    raw = {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
        "prompt_tokens_details": {"cached_tokens": None, "audio_tokens": None},
        "completion_tokens_details": {"reasoning_tokens": None},
    }
    assert sanitize_usage(raw) == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }

    cfg = AssistantConfig(
        master_enabled=True,
        api_key="ollama",
        base_url="http://localhost:11434/v1",
        model="qwen2.5:3b",
        provider="ollama",
        llm_configured=True,
        enabled=True,
        max_tool_rounds=5,
        query_transform=True,
    )
    client = LLMClient(cfg)

    class _FakeUsage:
        def model_dump(self) -> dict:
            return raw

    class _FakeChoice:
        message = type("M", (), {"content": "Hello from copilot."})()

    class _FakeResponse:
        choices = [_FakeChoice()]
        model = "qwen2.5:3b"
        usage = _FakeUsage()

    client._client = type(
        "C",
        (),
        {
            "chat": type(
                "Chat",
                (),
                {
                    "completions": type(
                        "Comp",
                        (),
                        {"create": staticmethod(lambda **kwargs: _FakeResponse())},
                    )()
                },
            )()
        },
    )()

    result = client.complete([{"role": "user", "content": "你好"}])
    assert result.usage == {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}


def test_copilot_chat_chinese_greeting_no_search(
    built_index: RagConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "ollama")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "true")

    search_called = False
    original_search = search_ops_docs

    def _tracking_search(*args, **kwargs):
        nonlocal search_called
        search_called = True
        return original_search(*args, **kwargs)

    monkeypatch.setattr("assistant.copilot.search_ops_docs", _tracking_search)

    payload = answer_copilot_question("你好")
    assert payload["intent"] == "chitchat"
    assert search_called is False
    assert "assistant" in payload["answer"].lower()
    assert payload["sources"] == []


def test_copilot_chinese_phase_b_ops_doc(
    built_index: RagConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "ollama")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "true")

    payload = answer_copilot_question(
        "Phase B 是什么",
        classify_fn=_mock_router_ops_doc("Phase B 是什么"),
        complete_fn=_mock_complete_factory(["Phase B 是什么"]),
    )
    assert payload["intent"] == "ops_doc"
    assert payload["retrieval_query"] is not None
    assert "Phase B" in payload["retrieval_query"]
    assert payload["sources"]


def test_copilot_empty_hits_low_confidence(
    built_index: RagConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "ollama")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_QUERY_TRANSFORM", "true")

    def _mock_classify(_messages: list[dict[str, str]]) -> CompletionResult:
        return CompletionResult(
            text='{"intent": "ops_doc", "retrieval_query": "xyzzy_nonexistent_term_12345"}',
            model="mock-qwen",
            provider="ollama",
        )

    answer_called = False

    def _should_not_answer(_messages: list[dict[str, str]]) -> CompletionResult:
        nonlocal answer_called
        answer_called = True
        return CompletionResult(text="should not run", model="x", provider="ollama")

    payload = answer_copilot_question(
        "What is xyzzy?",
        classify_fn=_mock_classify,
        complete_fn=_should_not_answer,
    )
    assert payload["intent"] == "ops_doc"
    assert "could not find" in payload["answer"].lower()
    assert payload["sources"] == []
    assert answer_called is False


def test_copilot_chat_chinese_greeting_mock_llm(
    built_index: RagConfig,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "ollama")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")

    from assistant import copilot as copilot_module

    def _mock_greeting(question: str, site_no=None, config=None, complete_fn=None, top_k=None):
        assert question == "你好"
        return {
            "answer": "Hello! I am the turbidity operations copilot. Ask me about ops documentation.",
            "sources": [],
            "model": "mock-qwen",
            "provider": "ollama",
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        }

    monkeypatch.setattr(copilot_module, "answer_copilot_question", _mock_greeting)

    response = client.post(
        "/copilot/chat",
        json={"question": "你好", "site_no": "12117000"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "copilot" in body["answer"].lower()
    assert body["provider"] == "ollama"


def test_copilot_chat_nested_usage_from_llm_mock(
    built_index: RagConfig,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "ollama")
    monkeypatch.setenv("ASSISTANT_ENABLED", "true")

    from assistant import copilot as copilot_module

    monkeypatch.setattr(
        copilot_module,
        "answer_copilot_question",
        lambda question, site_no=None, config=None, complete_fn=None, top_k=None: {
            "answer": "Phase B overview.",
            "sources": [],
            "model": "mock-qwen",
            "provider": "ollama",
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens_details": {"reasoning_tokens": None},
            },
        },
    )

    response = client.post("/copilot/chat", json={"question": "What is Phase B?"})
    assert response.status_code == 502
    assert response.json()["detail"]["error"] == "invalid_copilot_response"
