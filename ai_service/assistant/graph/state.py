"""Assistant LangGraph state schema."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class AssistantState(TypedDict):
    """State flowing through the unified assistant graph."""

    message: str
    site_no: NotRequired[str | None]
    session_id: NotRequired[str | None]
    history: NotRequired[list[dict[str, str]]]
    intent: NotRequired[str | None]
    retrieval_query: NotRequired[str | None]
    answer: NotRequired[str]
    sources: NotRequired[list[dict[str, str]]]
    tool_calls: NotRequired[list[dict[str, Any]]]
    tool_trace: NotRequired[list[str]]
    mode: NotRequired[str]
    model: NotRequired[str | None]
    provider: NotRequired[str]
    usage: NotRequired[dict[str, int | float] | None]
    skip_classify: NotRequired[bool]
    done: NotRequired[bool]
    reflect_count: NotRequired[int]
    reflect_issues: NotRequired[list[str]]
    reflect_action: NotRequired[str | None]
    skip_reflect: NotRequired[bool]
