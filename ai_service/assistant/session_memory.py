"""In-memory session store for multi-turn Copilot chat (MVP — no Redis/DB)."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from typing import Any

MAX_TURNS_PER_SESSION = 10
MAX_SESSIONS = 500
CACHE_TTL_SECONDS = 30 * 60
HISTORY_LIMIT = 8

FRESH_DATA_KEYWORDS = (
    "refresh",
    "update",
    "latest",
    "again",
    "re-run",
    "rerun",
    "new forecast",
    "run again",
    "fetch again",
)

FOLLOW_UP_KEYWORDS = (
    "why",
    "what about",
    "explain",
    "detail",
    "more about",
    "mean",
    "recommend",
    "how",
    "which",
    "tell me more",
    "break down",
    "clarify",
)


class _SessionState:
    __slots__ = ("turns", "tool_cache", "tool_cache_ts", "last_tool_audit", "site_no")

    def __init__(self) -> None:
        self.turns: list[dict[str, str]] = []
        self.tool_cache: dict[str, Any] | None = None
        self.tool_cache_ts: float = 0.0
        self.last_tool_audit: list[dict[str, Any]] = []
        self.site_no: str | None = None


class SessionStore:
    """Thread-safe LRU session store with TTL tool-result cache."""

    def __init__(
        self,
        *,
        max_sessions: int = MAX_SESSIONS,
        max_turns: int = MAX_TURNS_PER_SESSION,
        cache_ttl: float = CACHE_TTL_SECONDS,
    ) -> None:
        self._max_sessions = max_sessions
        self._max_turns = max_turns
        self._cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, _SessionState] = OrderedDict()

    def resolve_session_id(self, session_id: str | None) -> str:
        sid = (session_id or "").strip()
        return sid if sid else str(uuid.uuid4())

    def _get_or_create(self, session_id: str) -> _SessionState:
        if session_id in self._sessions:
            self._sessions.move_to_end(session_id)
            return self._sessions[session_id]
        state = _SessionState()
        self._sessions[session_id] = state
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)
        return state

    def merge_history(
        self,
        session_id: str,
        client_history: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        """Return recent turns, preferring server store then client-supplied history."""
        with self._lock:
            state = self._get_or_create(session_id)
            if state.turns:
                return list(state.turns[-HISTORY_LIMIT:])
        if not client_history:
            return []
        cleaned: list[dict[str, str]] = []
        for turn in client_history:
            role = str(turn.get("role", "")).strip()
            content = str(turn.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                cleaned.append({"role": role, "content": content})
        return cleaned[-HISTORY_LIMIT:]

    def append_turn(self, session_id: str, role: str, content: str) -> None:
        text = content.strip()
        if not text or role not in ("user", "assistant"):
            return
        with self._lock:
            state = self._get_or_create(session_id)
            state.turns.append({"role": role, "content": text})
            if len(state.turns) > self._max_turns:
                state.turns = state.turns[-self._max_turns :]

    def cache_tool_result(
        self,
        session_id: str,
        site_no: str | None,
        audit: list[dict[str, Any]],
        tool_payloads: list[dict[str, Any]] | None = None,
    ) -> None:
        if not audit:
            return
        with self._lock:
            state = self._get_or_create(session_id)
            state.tool_cache = {
                "audit": audit,
                "payloads": tool_payloads or [],
            }
            state.tool_cache_ts = time.monotonic()
            state.last_tool_audit = list(audit)
            state.site_no = site_no

    def get_cached_tools(
        self,
        session_id: str,
        site_no: str | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None or state.tool_cache is None:
                return None
            if time.monotonic() - state.tool_cache_ts > self._cache_ttl:
                return None
            cached_site = state.site_no
            if site_no and cached_site and site_no != cached_site:
                return None
            cache = state.tool_cache
            audit = cache.get("audit") or []
            payloads = cache.get("payloads") or []
            return list(audit), list(payloads)

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


def looks_like_follow_up(message: str, history: list[dict[str, str]]) -> bool:
    """Heuristic: short or detail-oriented question after prior turns."""
    if not history:
        return False
    lowered = message.lower()
    if any(k in lowered for k in FRESH_DATA_KEYWORDS):
        return False
    if any(k in lowered for k in FOLLOW_UP_KEYWORDS):
        return True
    return len(message.split()) <= 14


def format_cached_tool_context(
    audit: list[dict[str, Any]],
    payloads: list[dict[str, Any]],
) -> str:
    """Build a system-side context block from cached tool results."""
    import json

    lines = [
        "Cached tool results from this session (reuse for follow-up — do NOT re-fetch unless the user asks for fresh data):"
    ]
    for entry in audit:
        name = entry.get("name", "unknown")
        preview = entry.get("result_preview")
        if preview:
            lines.append(f"- {name}: {json.dumps(preview, default=str)}")
        elif entry.get("ok"):
            lines.append(f"- {name}: ok")
    for payload in payloads:
        if isinstance(payload, dict) and payload.get("ok"):
            data = payload.get("data")
            if data is not None:
                lines.append(f"Full tool JSON:\n{json.dumps(payload, default=str)}")
    return "\n".join(lines)


# Module-level singleton for MVP in-memory store.
session_store = SessionStore()
