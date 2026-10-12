"""Read the stream-json output of `claude -p`.

The last event of a call is the `result` event. It holds the cost, the tokens,
the number of turns, the time, and the error state.

The shapes come from real transcripts of Claude Code 2.1.273. The fixtures are
in tests/fixtures/stream/.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

# The argument of each tool that goes into the console line.
TOOL_ARGUMENT = {
    "Bash": "command",
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "NotebookEdit": "notebook_path",
    "Glob": "pattern",
    "Grep": "pattern",
    "Task": "description",
    "Skill": "skill",
    "WebFetch": "url",
    "WebSearch": "query",
}

ARGUMENT_MAX = 60


@dataclass
class StepResult:
    """What 1 `claude -p` call reports about itself."""

    ok: bool
    error_class: str | None
    error: str | None
    cost_usd: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    num_turns: int
    duration_s: float
    session_id: str | None
    # How many times the agent called each tool. A document that an agent
    # wrote with 0 Read calls did not look at the material.
    tool_calls: dict[str, int] = field(default_factory=dict)
    # False when the stream has no result event. A killed call gives no cost,
    # and 0.0 USD is then the value of a field that nobody measured. The
    # provider still charges for the work.
    cost_known: bool = True
    # The estimate of Claude Code for the thinking of the last turn. A killed
    # call has no other measure of the work that it did.
    thinking_tokens: int = 0


def read_stream(
    lines: Iterable[str], on_event: Callable[[dict[str, Any]], None] | None = None
) -> StepResult:
    """Read each line of the stream and give the result of the call.

    A line that is not JSON is ignored. The child can write a warning to the same
    stream.
    """
    result_event = None
    thinking = 0
    tools: Counter[str] = Counter()
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        tools.update(_tool_names(event))
        if on_event is not None:
            on_event(event)
        if event.get("subtype") == "thinking_tokens":
            thinking = max(thinking, _number(event, "estimated_tokens", int, 0))
        if event.get("type") == "result":
            result_event = event

    if result_event is None:
        return StepResult(
            ok=False,
            error_class="transient",
            error="the stream has no result event",
            cost_usd=0.0,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            num_turns=0,
            duration_s=0.0,
            session_id=None,
            tool_calls=dict(tools),
            cost_known=False,
            thinking_tokens=thinking,
        )

    usage = result_event.get("usage")
    if not isinstance(usage, Mapping):
        usage = {}
    error_class = _error_class(result_event)
    return StepResult(
        ok=error_class is None,
        error_class=error_class,
        error=None if error_class is None else _error_text(result_event),
        cost_usd=_number(result_event, "total_cost_usd", float, 0.0),
        input_tokens=_number(usage, "input_tokens", int, 0),
        output_tokens=_number(usage, "output_tokens", int, 0),
        cache_read_tokens=_number(usage, "cache_read_input_tokens", int, 0),
        cache_write_tokens=_number(usage, "cache_creation_input_tokens", int, 0),
        num_turns=_number(result_event, "num_turns", int, 0),
        duration_s=_number(result_event, "duration_ms", float, 0.0) / 1000.0,
        session_id=result_event.get("session_id"),
        tool_calls=dict(tools),
        thinking_tokens=thinking,
    )


def _number(source: Mapping[str, Any], key: str, kind, default):
    """Read a number the provider sent, or give the default.

    This module is a reader over JSON that the provider controls. A field
    with an unexpected type must not raise: run_step calls this after the
    agent has been paid for, and a raise here discards the cost that the
    same event carries. Measured: a result event with
    `"num_turns": "many"` raised ValueError and lost 2.50 USD.
    """
    try:
        return kind(source.get(key) or default)
    except (TypeError, ValueError, OverflowError):
        return default


def describe_event(event: dict[str, Any]) -> str | None:
    """Give 1 console line for a tool call, or None for each other event."""
    if event.get("type") != "assistant":
        return None
    content = (event.get("message") or {}).get("content") or []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return f"{block.get('name')}({_argument(block)})"
    return None


def _tool_names(event: dict[str, Any]) -> list[str]:
    """Give the name of each tool that this event calls."""
    if event.get("type") != "assistant":
        return []
    content = (event.get("message") or {}).get("content") or []
    return [
        str(block.get("name"))
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]


def _error_class(result_event: dict[str, Any]) -> str | None:
    """Give the failure class of a result event, or None for a step that works.

    A failure does not always change the subtype. An auth failure has the
    subtype `success`, with `is_error` true and `terminal_reason` `api_error`.
    """
    if not result_event.get("is_error"):
        return None

    subtype = result_event.get("subtype") or ""
    reason = result_event.get("terminal_reason") or ""
    if subtype == "error_max_budget_usd" or reason == "budget_exhausted":
        return "budget"

    status = result_event.get("api_error_status")
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limited"
    if isinstance(status, int) and status >= 500:
        return "transient"

    text = str(result_event.get("result") or "").lower()
    if "not logged in" in text or "/login" in text:
        return "auth"
    # A limit of the subscription. The real event of 2026-09-16 also had the
    # status 429, and a retry of a limit costs 2 waits and a second full call.
    if "session limit" in text or "usage limit" in text:
        return "rate_limited"
    return "transient"


def _error_text(result_event: dict[str, Any]) -> str:
    text = result_event.get("result")
    if text:
        return str(text)
    subtype = result_event.get("subtype") or "error"
    reason = result_event.get("terminal_reason") or "unknown"
    return f"{subtype}: {reason}"


def _argument(block: dict[str, Any]) -> str:
    arguments = block.get("input") or {}
    key = TOOL_ARGUMENT.get(str(block.get("name")))
    value = arguments.get(key) if key else None
    if value is None:
        return ""
    value = str(value)
    if key and key.endswith("path"):
        value = Path(value).name
    value = " ".join(value.split())
    if len(value) > ARGUMENT_MAX:
        value = value[: ARGUMENT_MAX - 1] + "…"
    return value
