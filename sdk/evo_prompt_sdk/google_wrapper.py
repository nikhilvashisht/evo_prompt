"""
google_wrapper.py — Extraction logic for Google GenAI tracing
=============================================================
Contains only field-extraction helpers and the _build_trace assembler.
Proxy/model classes live in dto/google_models.py.

Google GenAI message structure (as of 2025):
  contents: [
    { "role": "user",  "parts": [{"text": "..."}] },
    { "role": "model", "parts": [{"text": "..."}] }
  ]
  system_instruction: "..."  ← top-level kwarg, NOT inside contents

Tool call in response:
  candidates[0].content.parts[n].function_call
    .name  → str
    .args  → dict  (native dict — no JSON string parsing needed)

Text response:
  response.text               ← SDK convenience shortcut
  candidates[0].content.parts[n].text  ← manual fallback
"""

from __future__ import annotations

import uuid
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .tracer import EvoTracer

# Re-export GoogleTracedClient so callers can import from here if needed
from .dto.google_models import GoogleTracedClient  # noqa: F401


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------

def _extract_query(args: tuple, kwargs: dict) -> str:
    """
    Pull the user-facing query out of a generate_content call.

    Google accepts contents as:
      - A plain string:  generate_content(model=..., contents="hello")
      - A list of Content objects or dicts (multi-turn conversation)
      - Positional arg:  generate_content("gemini-...", "hello")
    For multi-turn, we extract the last user turn only.
    """
    contents = kwargs.get("contents")
    if contents is None and len(args) >= 2:
        contents = args[1]
    elif contents is None and len(args) == 1:
        contents = args[0]

    if contents is None:
        return ""

    if isinstance(contents, str):
        return contents

    if isinstance(contents, list):
        # Walk backwards to find the last user turn
        for item in reversed(contents):
            if isinstance(item, dict):
                if item.get("role", "user") == "user":
                    parts = item.get("parts", [])
                    texts = [
                        p.get("text", "") if isinstance(p, dict) else getattr(p, "text", "")
                        for p in parts
                    ]
                    return " ".join(t for t in texts if t).strip()
            else:
                # SDK Content object
                if getattr(item, "role", "user") == "user":
                    parts = getattr(item, "parts", [])
                    texts = [getattr(p, "text", "") for p in parts]
                    return " ".join(t for t in texts if t).strip()

    return str(contents)


def _extract_system_prompt(kwargs: dict) -> Optional[str]:
    """
    system_instruction is a top-level kwarg in google-genai — not inside contents.
    Can be a plain string or a Content / GenerateContentConfig object.
    """
    system_instruction = kwargs.get("system_instruction")
    if isinstance(system_instruction, str):
        return system_instruction

    config = kwargs.get("config")
    if config and hasattr(config, "system_instruction"):
        raw = config.system_instruction
        if isinstance(raw, str):
            return raw
        if hasattr(raw, "parts"):
            return " ".join(getattr(part, "text", "") for part in raw.parts)

    return None


def _extract_tool_calls(response: Any) -> list:
    """
    Walk response.candidates[].content.parts looking for function_call parts.
    Returns a list of normalized dicts matching evo_prompt's ToolCallSchema.
    """
    tool_calls = []
    for candidate in getattr(response, "candidates", []):
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", []) if content else []
        for part in parts:
            function_call = getattr(part, "function_call", None)
            if function_call:
                tool_calls.append({
                    "tool_name": getattr(function_call, "name", "unknown"),
                    "arguments": dict(getattr(function_call, "args", {})),
                    "result": None,
                    "error": None,
                })
    return tool_calls


def _extract_response_text(response: Any) -> str:
    """
    Use the SDK's .text shortcut first, then fall back to manual part walking.
    """
    text = getattr(response, "text", None)
    if text:
        return text

    for candidate in getattr(response, "candidates", []):
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", []) if content else []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                return part_text

    return ""


def _extract_model(args: tuple, kwargs: dict) -> str:
    model = kwargs.get("model")
    if model:
        return str(model)
    if args:
        return str(args[0])
    return "unknown"


# ---------------------------------------------------------------------------
# Trace assembler
# ---------------------------------------------------------------------------

def _build_trace(
    tracer: "EvoTracer",
    args: tuple,
    kwargs: dict,
    response: Any,
    latency_ms: float,
) -> dict:
    """
    Assembles a normalized trace dict from a completed generate_content call.
    Called by the proxy classes in dto/google_models.py after each response.
    """
    tool_calls = _extract_tool_calls(response)
    llm_response = _extract_response_text(response)

    # If model made tool calls and returned no text, describe what it called
    if not llm_response and tool_calls:
        llm_response = f"[tool calls: {', '.join(tc['tool_name'] for tc in tool_calls)}]"

    return {
        "trace_id": str(uuid.uuid4()),
        "prompt_version_id": tracer.prompt_version_id,
        "user_query": _extract_query(args, kwargs),
        "llm_response": llm_response,
        "tool_calls": tool_calls,
        "metadata": {
            "model": _extract_model(args, kwargs),
            "latency_ms": round(latency_ms, 1),
            "provider": "google-genai",
            "system_prompt": _extract_system_prompt(kwargs),
        },
    }
