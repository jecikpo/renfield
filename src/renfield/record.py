"""The record of 1 step, the record file, and the console lines."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Claude Code prices every call at Anthropic rates, whatever vendor served
# it. Measured on 2026-09-16: a call on meta-llama/llama-3.1-8b-instruct
# reported 0.3141 USD, and OpenRouter charges about 0.002 USD for it.
# docs/design.md, section 9, names the run that recorded this.
ESTIMATED_KINDS = ("subscription", "openrouter")


@dataclass
class StepRecord:
    """What 1 step did, and what it wrote."""

    name: str
    status: str                             # ok | failed
    error_class: str | None = None
    error: str | None = None
    provider: str | None = None
    model: str | None = None
    effort: str | None = None
    model_entry: str | None = None          # the [models.<name>] of the file
    attempts: int = 0
    cost_usd: float = 0.0
    # False when the call was killed and wrote no result event. The cost is
    # then 0.0, and nobody measured it.
    cost_known: bool = True
    cost_estimated: bool = False
    # The largest value that a killed call could have cost. None when the
    # step had no max_usd, because then no limit held it.
    unknown_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    num_turns: int = 0
    duration_s: float = 0.0
    tool_calls: dict[str, int] = field(default_factory=dict)
    run_dir: str | None = None
    prompt: str | None = None               # relative to run_dir
    transcript: str | None = None           # relative to run_dir
    record: str | None = None               # relative to run_dir
    outputs: list[str] = field(default_factory=list)
    # True when each expected output is there and passes its checks. This can
    # be true for a step that failed: a limit can arrive after the agent wrote
    # a complete file.
    outputs_valid: bool = False
    # The exit code of the child. -9 says that SIGKILL ended it, and the cost
    # of that call is lost.
    child_exit_code: int | None = None


def estimated(kind: str) -> bool:
    """Say whether the cost of this provider kind is an estimate."""
    return kind in ESTIMATED_KINDS


def as_dict(record: StepRecord) -> dict:
    """Give the record as data, with the cost rounded."""
    data = asdict(record)
    # json.dumps writes NaN and Infinity as bare words, and jq and
    # JSON.parse reject them. A non-finite number was never measured.
    if not math.isfinite(data["cost_usd"]):
        data["cost_usd"] = 0.0
        data["cost_known"] = False
    if not math.isfinite(data["duration_s"]):
        data["duration_s"] = 0.0
    data["cost_usd"] = round(data["cost_usd"], 6)
    if data["unknown_usd"] is not None:
        data["unknown_usd"] = round(data["unknown_usd"], 6)
    data["duration_s"] = round(data["duration_s"], 1)
    return data


def write_record(path: Path, record: StepRecord) -> None:
    """Write the record file. Build its folder first."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(as_dict(record), indent=2, allow_nan=False) + "\n")


def summary_line(record: StepRecord) -> str:
    """Give the last line of the console, before the record path."""
    parts = [record.status]
    if record.error_class:
        parts.append(record.error_class)
    if record.attempts > 1:
        parts.append(f"{record.attempts} attempts")
    parts.append(f"{record.num_turns} turns")
    parts.append(f"{record.duration_s:.1f} s")
    cost = f"{record.cost_usd:.4f} USD"
    if record.cost_estimated:
        cost += " (estimated)"
    if not record.cost_known:
        cost = "cost not measured"
    parts.append(cost)
    return f"{record.name}: " + ", ".join(parts)
