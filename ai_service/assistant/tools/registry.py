"""Load tool schemas from registry.yaml for OpenAI-compatible function calling."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_REGISTRY_PATH = Path(__file__).resolve().parent / "registry.yaml"

# Embedded fallback mirrors registry.yaml (no PyYAML dependency).
_EMBEDDED_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_turbidity_risk_forecast_12h",
        "description": (
            "Fetch the Phase B 12-hour turbidity alert-risk forecast for a USGS site. "
            "Returns recommend_alert, max_tier_forecast, tier_at_t, and related frozen decision fields. "
            "Phase B is currently wired for site 12117500 only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "site_no": {
                    "type": "string",
                    "description": "USGS 8-digit site number (e.g. 12117500).",
                },
                "reference_utc": {
                    "type": "string",
                    "description": "Optional ISO UTC hour; default is latest in features CSV.",
                },
            },
            "required": ["site_no"],
        },
    },
    {
        "name": "get_forecast_series",
        "description": (
            "Fetch IV-based short-horizon forecast series for discharge (00060) or turbidity (63680). "
            "Returns BOTH history_points and forecast_points. Prefer this single tool when the "
            "operator asks for forecast AND recent history together."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "site_no": {"type": "string", "description": "USGS 8-digit site number."},
                "parameter_cd": {
                    "type": "string",
                    "description": "NWIS parameter code — only 00060 or 63680.",
                },
                "horizon_hours": {
                    "type": "integer",
                    "description": "Forecast horizon in hours (1–168).",
                },
                "history_days": {
                    "type": "integer",
                    "description": "History window in days (default 30).",
                },
            },
            "required": ["site_no", "parameter_cd", "horizon_hours"],
        },
    },
    {
        "name": "get_iv_history",
        "description": (
            "Read-only USGS IV history for discharge (00060) or turbidity (63680) without forecasting. "
            "Use for past readings/trend, or paired with a forecast tool for detailed history."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "site_no": {"type": "string", "description": "USGS 8-digit site number."},
                "parameter_cd": {
                    "type": "string",
                    "description": "NWIS parameter code — only 00060 or 63680.",
                },
                "history_days": {
                    "type": "integer",
                    "description": "History window in days (1–90, default 7).",
                },
                "max_points": {
                    "type": "integer",
                    "description": "Max points in history_points tail (1–168, default 48).",
                },
            },
            "required": ["site_no", "parameter_cd"],
        },
    },
    {
        "name": "get_assistant_health",
        "description": "Report assistant module status, LLM configuration, and RAG index readiness.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_turbidity_state_snapshot",
        "description": (
            "Current turbidity alert tier, legacy four-state label, NTU, 1h delta, and 6h/12h "
            "rule-warning flags at one reference hour. Uses turbidity-state v2.1 rules."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "site_no": {
                    "type": "string",
                    "description": "USGS 8-digit site number.",
                },
                "reference_utc": {
                    "type": "string",
                    "description": "Optional ISO UTC hour; default is latest in features CSV.",
                },
                "thresholds_json_path": {
                    "type": "string",
                    "description": "Optional frozen state_thresholds.json path.",
                },
                "features_csv_path": {
                    "type": "string",
                    "description": "Optional features CSV path.",
                },
            },
            "required": ["site_no"],
        },
    },
    {
        "name": "list_puget_default_sites",
        "description": (
            "List USGS sites in the Puget Sound demo config (region_label and site_no/name pairs)."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "search_ops_docs",
        "description": (
            "BM25 search over indexed turbidity operations documentation. "
            "Returns top excerpts with source refs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of chunks to return (1–10).",
                },
            },
            "required": ["query"],
        },
    },
]

_FORBIDDEN_TOOL_NAMES = frozenset(
    {
        "set_recommend_alert",
        "ack_alert",
        "execute_sql",
        "shell_exec",
        "run_turbidity_monitor_write",
    }
)


def _parse_simple_yaml_tools(text: str) -> list[dict[str, Any]] | None:
    """Best-effort parser for the flat registry.yaml layout (no external YAML lib)."""
    if not text.strip():
        return None
    tools: list[dict[str, Any]] = []
    blocks = re.split(r"\n\s*-\s+name:\s*", text)
    if len(blocks) < 2:
        return None
    for block in blocks[1:]:
        name_match = re.match(r"(\w+)\s*\n", block)
        if not name_match:
            continue
        name = name_match.group(1)
        desc_match = re.search(
            r"description:\s*(?:>\s*\n\s*)?(.+?)(?:\n\s*parameters:|\Z)",
            block,
            re.DOTALL,
        )
        description = ""
        if desc_match:
            description = re.sub(r"\s+", " ", desc_match.group(1).strip())
        params_match = re.search(r"parameters:\s*\n((?:\s+.+\n?)+)", block)
        parameters: dict[str, Any] = {"type": "object", "properties": {}}
        if params_match:
            params_blob = params_match.group(1)
            if "type: object" in params_blob:
                properties: dict[str, Any] = {}
                for prop_name in re.findall(r"^\s+(\w+):\s*$", params_blob, re.MULTILINE):
                    if prop_name in {"type", "properties", "required"}:
                        continue
                    prop_type = "string"
                    if re.search(rf"^\s+{prop_name}:\s*\n\s+type:\s+integer", params_blob, re.MULTILINE):
                        prop_type = "integer"
                    desc_m = re.search(
                        rf"^\s+{prop_name}:\s*\n\s+type:\s+\w+\s*\n\s+description:\s+(.+)$",
                        params_blob,
                        re.MULTILINE,
                    )
                    prop: dict[str, Any] = {"type": prop_type}
                    if desc_m:
                        prop["description"] = desc_m.group(1).strip()
                    properties[prop_name] = prop
                parameters["properties"] = properties
            req_match = re.search(r"required:\s*\n((?:\s+-\s+\w+\s*\n?)+)", params_blob)
            if req_match:
                required = re.findall(r"-\s+(\w+)", req_match.group(1))
                if required:
                    parameters["required"] = required
        tools.append({"name": name, "description": description, "parameters": parameters})
    return tools or None


def _load_tool_specs() -> list[dict[str, Any]]:
    if not _REGISTRY_PATH.is_file():
        return list(_EMBEDDED_TOOLS)
    raw = _REGISTRY_PATH.read_text(encoding="utf-8")
    parsed = _parse_simple_yaml_tools(raw)
    if parsed:
        return parsed
    return list(_EMBEDDED_TOOLS)


def get_openai_tools() -> list[dict[str, Any]]:
    """Return OpenAI chat.completions ``tools`` list (function definitions only)."""
    specs = _load_tool_specs()
    out: list[dict[str, Any]] = []
    for spec in specs:
        name = spec["name"]
        if name in _FORBIDDEN_TOOL_NAMES:
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec.get("description", ""),
                    "parameters": spec.get("parameters", {"type": "object", "properties": {}}),
                },
            }
        )
    return out


def get_tool_names() -> list[str]:
    return [t["function"]["name"] for t in get_openai_tools()]


# Value constraints the registry YAML cannot express; applied by property name.
_ARGUMENT_CONSTRAINTS: dict[str, dict[str, Any]] = {
    "site_no": {"pattern": r"^[0-9]{8}$"},
    "parameter_cd": {"enum": ["00060", "63680"]},
}


def get_tool_selection_schema(max_tools: int = 3) -> dict[str, Any]:
    """
    JSON schema for agent-lite tool selection: ``{"tools": [{"tool", "arguments"}, ...]}``.

    One ``anyOf`` branch per whitelisted tool, so constrained decoding can only emit
    known tool names with that tool's own argument names. Guarantees shape, not choice.
    """
    variants: list[dict[str, Any]] = []
    for tool in get_openai_tools():
        fn = tool["function"]
        params = json.loads(json.dumps(fn["parameters"]))
        params["additionalProperties"] = False
        for prop_name, prop in params.get("properties", {}).items():
            prop.update(_ARGUMENT_CONSTRAINTS.get(prop_name, {}))
        variants.append(
            {
                "type": "object",
                "properties": {"tool": {"const": fn["name"]}, "arguments": params},
                "required": ["tool", "arguments"],
                "additionalProperties": False,
            }
        )
    return {
        "type": "object",
        "properties": {
            "tools": {"type": "array", "maxItems": max_tools, "items": {"anyOf": variants}},
        },
        "required": ["tools"],
        "additionalProperties": False,
    }


def tool_spec_json() -> str:
    """Debug helper: serialized tool specs."""
    return json.dumps(_load_tool_specs(), indent=2)
