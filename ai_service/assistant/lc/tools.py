"""Wrap whitelist tools from registry.yaml as LangChain StructuredTools."""

from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from assistant.tools.executor import execute_tool
from assistant.tools.registry import get_openai_tools


def _json_schema_type_to_python(type_name: str) -> type:
    mapping: dict[str, type] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    return mapping.get(type_name, str)


def _args_model_for_spec(name: str, parameters: dict[str, Any]) -> type[BaseModel]:
    properties = parameters.get("properties") or {}
    required = set(parameters.get("required") or [])
    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue
        py_type = _json_schema_type_to_python(str(prop_schema.get("type") or "string"))
        description = str(prop_schema.get("description") or "")
        if prop_name in required:
            fields[prop_name] = (py_type, Field(description=description))
        else:
            fields[prop_name] = (py_type | None, Field(default=None, description=description))
    if not fields:
        # Tools with empty properties still need a BaseModel.
        return create_model(f"{name}_Args")
    return create_model(f"{name}_Args", **fields)  # type: ignore[call-overload]


def _make_tool_func(tool_name: str) -> Callable[..., str]:
    def _run(**kwargs: Any) -> str:
        cleaned = {k: v for k, v in kwargs.items() if v is not None}
        result = execute_tool(tool_name, cleaned)
        return json.dumps(result, default=str)

    _run.__name__ = tool_name
    _run.__doc__ = f"Execute read-only tool {tool_name}."
    return _run


def build_readonly_langchain_tools() -> list[StructuredTool]:
    """Build LangChain tools mirroring the OpenAI function-calling whitelist."""
    tools: list[StructuredTool] = []
    for item in get_openai_tools():
        fn = item.get("function") or {}
        name = str(fn.get("name") or "")
        if not name:
            continue
        description = str(fn.get("description") or "")
        parameters = fn.get("parameters") or {"type": "object", "properties": {}}
        args_model = _args_model_for_spec(name, parameters if isinstance(parameters, dict) else {})
        tools.append(
            StructuredTool.from_function(
                func=_make_tool_func(name),
                name=name,
                description=description,
                args_schema=args_model,
            )
        )
    return tools


def get_tool_by_name(name: str) -> StructuredTool | None:
    for tool in build_readonly_langchain_tools():
        if tool.name == name:
            return tool
    return None
