# Renfield Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `renfield`, a package that runs 1 AI agent as a child process against a prompt template, and reports what the agent did and what it wrote.

**Architecture:** 8 small modules under `src/renfield/`, each with 1 responsibility, plus a CLI. The only module that starts a child process is `step.py`. Every other module is a pure function over text, paths, or JSON. The test suite runs against a fake `claude` program, so it needs no network and no money.

**Tech Stack:** Python 3.11 or later, `jsonschema`, `tomllib` from the standard library, `pytest`, `uv`.

**Spec:** `docs/design.md` in this repository. The spec is the authority. Where this plan and the spec disagree, the spec wins, and the disagreement is a defect of this plan.

## Global Constraints

- **Documents and console messages use ASD-STE100.** Procedural sentences take 20 words maximum, descriptive sentences 25. Active voice. No "-ing" form as a verb. Code, identifiers, paths, commands, and log excerpts are exempt.
- **Measure, do not assume.** A claim about Claude Code, about a cost, or about a signal needs a recorded run or a fixture. Write the measured value and its date beside the code.
- **Each parameter gets a range.** Each numeric and each enumerated key gets a smallest value and a largest value, or the list of values it accepts. Check the range where the program reads the key. The message names the key, the range, and the value. A type check is not a range check.
- **Test first.** Write the test, watch it fail for the right reason, then write the code.
- **1 commit for each task.** The commit message names the task.
- **No test uses the network, and no test spends money.** Each test that needs an agent uses `renfield.testing.fake_claude`.
- **The code of a task is the requirement, and a count of tests is advice.** If a step says "9 passed" and the code of that step holds 10 tests, the code wins. Never delete a test to reach a number, and never invent one.
- **POSIX only.** `os.killpg` and the process group rule have no Windows path. Do not add one.
- **Do not commit `renfield.toml` or `runs/`.** The first can hold a key. The second holds prompts, transcripts, and agent output.
- **The 4 behaviours below are not preferences. Each one is a bug that somebody already paid for. Do not simplify any of them.**
  1. The child environment starts from the 9-name allowlist, and not from the parent environment.
  2. The failure classifier reads `is_error`, and never `subtype` alone. A measured rate limit reports `subtype: "success"` with `is_error: true`.
  3. A timeout sends SIGINT to the **process group**, then SIGKILL after 15 s.
  4. `outputs_valid` is a field of its own, separate from `status`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `pyproject.toml` | The package, the dependency list, the `renfield` script | 1 |
| `src/renfield/version.py` | The version, in its own module, so no import is a cycle | 1 |
| `src/renfield/__init__.py` | The public names | 1, 9 |
| `src/renfield/testing.py` | `fake_claude`: a fake agent for a test | 1 |
| `src/renfield/stream.py` | The `stream-json` reader, and the failure classes | 2 |
| `src/renfield/provider.py` | The environment of the child | 3 |
| `src/renfield/paths.py` | The 4 paths, and the placeholders | 4 |
| `src/renfield/config.py` | The TOML file, the precedence, the ranges | 5 |
| `src/renfield/outputs.py` | The output file checks | 6 |
| `src/renfield/record.py` | `StepRecord`, `record.json`, and the console lines | 7 |
| `src/renfield/step.py` | `run_step`: the command, the retry, the timeout | 8 |
| `src/renfield/cli.py` | `renfield run` | 9 |
| `README.md` | How to use it | 9 |

**The dependency direction is 1 way.** `step.py` imports from `stream`, `provider`, `paths`, `outputs`, `record`. `cli.py` imports from each module. **No module imports `step.py`**, and no module imports `cli.py`.

`record.py` comes before `step.py`, because `run_step` writes the record file itself. A caller then always has that file, and never has to remember to write it.

## Rulings this plan makes

These 2 decisions remove code that the Skarp source has. The spec does not name either one. A reviewer who finds them absent must not add them back.

| Ruling | Decision | Cost if wrong |
|---|---|---|
| P1 | **Drop the `blocked: true` convention** of `llm.py:359`. Skarp treats a JSON output with that key as a failed step. | A caller that wants an agent to refuse a job must check for its own key, which is 3 lines in the caller. |
| P2 | **Drop `over_budget`** of `record.py:55`. It guards a budget across several steps. | A caller that runs 5 steps adds its own total and its own limit. Renfield runs 1 step and reports its cost. |

---

## Task 1: The skeleton, and the fake agent

**Files:**
- Create: `pyproject.toml`
- Create: `src/renfield/__init__.py`
- Create: `src/renfield/testing.py`
- Create: `tests/test_testing.py`
- Create: `tests/fixtures/stream/` (6 files, copied, see step 2)

**Interfaces:**
- Produces: `fake_claude(tmp_path, stream=..., exit_code=0, sleep_s=0.0, writes=None, before="", on_int=None) -> Path`, and `call_record(tmp_path) -> dict`. Each later task uses both.

**Why this task is first.** Each later test needs a program that behaves like `claude -p` and costs nothing. The fake records what it received, so a test can assert the exact command and the exact environment that `step.py` built.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "renfield"
version = "0.1.0"
description = "Run 1 AI agent as a child process, and report what it did"
requires-python = ">=3.11"
dependencies = [
    "jsonschema>=4.23",
]

[project.scripts]
renfield = "renfield.cli:main"

[dependency-groups]
dev = [
    "pytest>=8.3",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/renfield"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Copy the 6 stream fixtures**

These are real transcripts of Claude Code 2.1.273. **Do not write a fixture by hand.** A hand-written event has the shape that the author expects, and the measured shapes are the reason the classifier works.

```bash
mkdir -p tests/fixtures/stream
cp ~/Projects/solana-workbench/skarp/tests/fixtures/stream/*.jsonl tests/fixtures/stream/
ls tests/fixtures/stream/
# auth-401.jsonl  auth-not-logged-in.jsonl  budget-exhausted.jsonl
# success.jsonl   timeout-killed.jsonl      tool-call.jsonl
```

If that path does not exist, stop and report. **Do not invent the fixtures.**

- [ ] **Step 3: Write the failing test of the fake agent**

`tests/test_testing.py`:

```python
import json
import subprocess
from pathlib import Path

from renfield.testing import call_record, fake_claude

SUCCESS = json.dumps(
    {"type": "result", "subtype": "success", "is_error": False,
     "total_cost_usd": 0.5, "num_turns": 3, "duration_ms": 1200,
     "usage": {"input_tokens": 10, "output_tokens": 20}}
) + "\n"


def test_the_fake_records_what_it_received(tmp_path):
    program = fake_claude(tmp_path, stream=SUCCESS)
    done = subprocess.run(
        [str(program), "-p", "--model", "x"],
        input="the prompt",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin", "SECRET": "shh"},
    )
    assert done.returncode == 0
    assert done.stdout == SUCCESS
    call = call_record(tmp_path)
    assert call["argv"] == ["-p", "--model", "x"]
    assert call["stdin"] == "the prompt"
    assert call["env"]["SECRET"] == "shh"
    assert call["cwd"] == str(tmp_path)


def test_the_fake_writes_the_files_of_the_test(tmp_path):
    program = fake_claude(tmp_path, writes={"verdict.json": '{"ok": true}'})
    subprocess.run([str(program)], input="", capture_output=True, text=True,
                   cwd=str(tmp_path))
    assert json.loads((tmp_path / "verdict.json").read_text()) == {"ok": True}


def test_the_fake_gives_the_exit_code_of_the_test(tmp_path):
    program = fake_claude(tmp_path, stream="", exit_code=3)
    done = subprocess.run([str(program)], input="", capture_output=True, text=True,
                          cwd=str(tmp_path))
    assert done.returncode == 3
```

- [ ] **Step 4: Run it and watch it fail**

Run: `uv run pytest tests/test_testing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'renfield'`

- [ ] **Step 5: Write `src/renfield/testing.py`**

```python
"""A fake `claude` program, for a test that must not cost money.

Each test of this package runs against this program. It records what it
received, so a test can assert the exact command and the exact environment
that `step.py` built.
"""

from __future__ import annotations

import json
from pathlib import Path

CALL_FILE = "call.json"


def fake_claude(
    tmp_path: Path,
    stream: str = "",
    exit_code: int = 0,
    sleep_s: float = 0.0,
    writes: dict[str, str] | None = None,
    before: str = "",
    on_int: str | None = None,
) -> Path:
    """Write a fake `claude` program, and give its path.

    `stream` is the text that the fake writes to its standard output, as a
    `stream-json` stream. `writes` is a map of file path to text: the fake
    writes each file, as an agent writes its output. `before` is the part of
    the stream that the fake writes before the sleep, as a model that works
    and then is killed. `on_int` is `ignore`, `stream`, or None, and it drives
    the escalation from SIGINT to SIGKILL.
    """
    path = Path(tmp_path) / "fake-claude"
    record = str(Path(tmp_path) / CALL_FILE)
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, signal, sys, time\n"
        f"record = {json.dumps(record)}\n"
        "open(record, 'w').write(json.dumps({'argv': sys.argv[1:],"
        " 'env': dict(os.environ), 'cwd': os.getcwd(), 'pid': os.getpid(),"
        " 'stdin': sys.stdin.read()}))\n"
        f"for name, text in {json.dumps(writes or {})}.items():\n"
        "    open(name, 'w').write(text)\n"
        + _on_int(on_int, stream)
        + f"sys.stdout.write({json.dumps(before)})\n"
        "sys.stdout.flush()\n"
        f"time.sleep({sleep_s})\n"
        f"sys.stdout.write({json.dumps(stream)})\n"
        "sys.stdout.flush()\n"
        f"sys.exit({exit_code})\n"
    )
    path.chmod(0o755)
    return path


def _on_int(kind: str | None, stream: str) -> str:
    """Give the SIGINT handler of the fake program."""
    if kind == "ignore":
        return "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
    if kind == "stream":
        return (
            "def _answer(number, frame):\n"
            f"    sys.stdout.write({json.dumps(stream)})\n"
            "    sys.stdout.flush()\n"
            "    sys.exit(0)\n"
            "signal.signal(signal.SIGINT, _answer)\n"
        )
    return ""


def call_record(tmp_path: Path) -> dict:
    """Give what the fake program received: argv, env, cwd, pid, stdin."""
    return json.loads((Path(tmp_path) / CALL_FILE).read_text())
```

- [ ] **Step 6: Write `src/renfield/version.py` and `src/renfield/__init__.py`**

**The version lives in its own module, and not in `__init__.py`.** Task 9 makes
`__init__.py` import `step.py`, which imports `record.py`. If `record.py` then
reads `__version__` from the package root, the import is a cycle and it fails.

`src/renfield/version.py`:

```python
"""The version of the package. Its own module, so that no import is a cycle."""

__version__ = "0.1.0"
```

`src/renfield/__init__.py`:

```python
"""Renfield runs 1 AI agent as a child process, and reports what it did."""

from renfield.version import __version__

__all__ = ["__version__"]
```

- [ ] **Step 7: Run the test and watch it pass**

Run: `uv run pytest tests/test_testing.py -v`
Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/renfield tests
git commit -m "feat: the package skeleton, and the fake agent for a test"
```

---

## Task 2: `stream.py`, the reader and the failure classes

**Files:**
- Create: `src/renfield/stream.py`
- Create: `tests/test_stream.py`

**Interfaces:**
- Consumes: `tests/fixtures/stream/*.jsonl` from task 1.
- Produces: `StepResult`, `read_stream(lines, on_event=None) -> StepResult`, `describe_event(event) -> str | None`.

**The trap this module exists to close.** An auth failure and a subscription rate limit both report `subtype: "success"`. A classifier that reads `subtype` calls a 401 a success, and the caller then reads an empty output file and reports a bad prompt. Read `is_error` first.

- [ ] **Step 1: Write the failing test**

`tests/test_stream.py`:

```python
import json
from pathlib import Path

import pytest

from renfield.stream import describe_event, read_stream

FIXTURES = Path(__file__).parent / "fixtures" / "stream"


def lines_of(name):
    return (FIXTURES / name).read_text().splitlines(keepends=True)


def test_a_success_gives_the_cost_and_the_tokens():
    result = read_stream(lines_of("success.jsonl"))
    assert result.ok is True
    assert result.error_class is None
    assert result.cost_usd > 0
    assert result.num_turns > 0
    assert result.cost_known is True


def test_an_auth_failure_is_not_a_success_although_its_subtype_says_so():
    """The measured trap. The event holds subtype success and is_error true."""
    raw = [line for line in lines_of("auth-401.jsonl") if line.strip()]
    # Line 1 of this fixture is a plain-text warning of the child, so the
    # JSON filter is not optional here. `raw` still holds that line, and
    # read_stream below must ignore it.
    events = [json.loads(line) for line in raw if line.startswith("{")]
    result_event = [e for e in events if e.get("type") == "result"][0]
    assert result_event["subtype"] == "success", "the fixture lost its trap"
    assert result_event["is_error"] is True

    result = read_stream(raw)
    assert result.ok is False
    assert result.error_class == "auth"


def test_a_login_message_is_an_auth_failure():
    result = read_stream(lines_of("auth-not-logged-in.jsonl"))
    assert result.error_class == "auth"


def test_an_exhausted_budget_has_its_own_class():
    result = read_stream(lines_of("budget-exhausted.jsonl"))
    assert result.error_class == "budget"


def test_a_stream_with_no_result_event_is_transient_and_unmeasured():
    result = read_stream(lines_of("timeout-killed.jsonl"))
    assert result.error_class == "transient"
    assert result.cost_known is False
    assert result.cost_usd == 0.0


def test_the_tool_calls_are_counted_by_name():
    result = read_stream(lines_of("tool-call.jsonl"))
    assert sum(result.tool_calls.values()) >= 1
    assert all(isinstance(name, str) for name in result.tool_calls)


def test_a_line_that_is_not_json_is_ignored():
    stream = ["a warning of the child\n", *lines_of("success.jsonl")]
    assert read_stream(stream).ok is True


def test_a_rate_limit_reads_the_status_and_not_the_subtype():
    event = {"type": "result", "subtype": "success", "is_error": True,
             "api_error_status": 429, "result": "whatever"}
    result = read_stream([json.dumps(event) + "\n"])
    assert result.error_class == "rate_limited"


def test_a_session_limit_in_the_text_is_a_rate_limit():
    event = {"type": "result", "subtype": "success", "is_error": True,
             "result": "You've hit your session limit · resets 4:40pm"}
    assert read_stream([json.dumps(event) + "\n"]).error_class == "rate_limited"


@pytest.mark.parametrize("status", [500, 503, 599])
def test_a_server_failure_is_transient_and_gets_a_retry(status):
    event = {"type": "result", "subtype": "error", "is_error": True,
             "api_error_status": status, "result": "x"}
    assert read_stream([json.dumps(event) + "\n"]).error_class == "transient"


def test_a_client_failure_that_is_not_401_403_or_429_is_transient():
    """There is no class for a 4xx that the measured set does not hold, and
    `transient` gets a retry. A retry of a 400 costs 1 call and fails again.
    Open item: measure a 400 before you give it a class of its own."""
    event = {"type": "result", "subtype": "error", "is_error": True,
             "api_error_status": 400, "result": "bad request"}
    assert read_stream([json.dumps(event) + "\n"]).error_class == "transient"


def test_describe_event_gives_a_line_for_a_tool_call_and_none_otherwise():
    call = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/a/b/plan.md"}}]}}
    assert describe_event(call) == "Read(plan.md)"
    assert describe_event({"type": "result"}) is None


def test_a_long_argument_is_cut_and_marked():
    call = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "x" * 200}}]}}
    line = describe_event(call)
    assert len(line) < 80
    assert line.endswith("…)")
```

- [ ] **Step 2: Run it and watch each test fail**

Run: `uv run pytest tests/test_stream.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'renfield.stream'`

**Read the failure of `test_an_auth_failure_...` first.** If the fixture does not hold `subtype: "success"` with `is_error: true`, the fixture is wrong, and the assertion in that test says so. Stop and report.

- [ ] **Step 3: Write `src/renfield/stream.py`**

Take this code from `skarp/src/skarp/common/stream.py` with no change of behaviour. The whole file is 205 lines, and the parts that matter are below. The docstring of the module must name the Claude Code version of the fixtures.

```python
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
from typing import Any, Callable, Iterable

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
```

`read_stream`, `describe_event`, `_tool_names`, `_error_class`, `_error_text`, and `_argument` come over as they are. The classifier is the part to copy exactly:

```python
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
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_stream.py -v`
Expected: each test passes.

- [ ] **Step 5: Commit**

```bash
git add src/renfield/stream.py tests/test_stream.py tests/fixtures
git commit -m "feat: the stream-json reader, and the failure classes"
```

---

## Task 3: `provider.py`, the environment of the child

**Files:**
- Create: `src/renfield/provider.py`
- Create: `tests/test_provider.py`

**Interfaces:**
- Produces: `Provider`, `ALLOWLIST`, `OPENROUTER_BASE_URL`, `ProviderError`, `build_env(provider, parent, config_dir=None) -> dict[str, str]`.

**What this module protects.** The parent of the child is your shell, or a Claude Code session. It holds your keys, and it holds the `CLAUDE_CODE_*` variables of the parent session. A child that inherits them bills the wrong account, or reads the configuration of the operator. The child therefore starts from an allowlist of 9 names.

- [ ] **Step 1: Write the failing test**

`tests/test_provider.py`:

```python
import pytest

from renfield.provider import (
    ALLOWLIST,
    OPENROUTER_BASE_URL,
    Provider,
    ProviderError,
    build_env,
)

PARENT = {
    "PATH": "/usr/bin",
    "HOME": "/home/x",
    "ANTHROPIC_API_KEY": "the-key-of-the-parent",
    "CLAUDE_CODE_SSE_PORT": "1234",
    "AWS_SECRET_ACCESS_KEY": "shh",
}


def test_a_subscription_child_gets_no_key_and_no_secret_of_the_parent():
    env = build_env(Provider(kind="subscription"), PARENT)
    assert env == {"PATH": "/usr/bin", "HOME": "/home/x"}
    assert "ANTHROPIC_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "CLAUDE_CODE_SSE_PORT" not in env


def test_the_allowlist_holds_9_names_and_no_secret():
    assert len(ALLOWLIST) == 9
    assert not [name for name in ALLOWLIST if "KEY" in name or "TOKEN" in name]


def test_an_api_child_gets_the_key_of_the_config_and_not_of_the_parent():
    env = build_env(Provider(kind="anthropic-api", api_key="mine"), PARENT)
    assert env["ANTHROPIC_API_KEY"] == "mine"


def test_an_openrouter_child_gets_the_base_url_and_an_empty_api_key():
    env = build_env(Provider(kind="openrouter", api_key="or-key"), PARENT)
    assert env["ANTHROPIC_BASE_URL"] == OPENROUTER_BASE_URL
    assert env["ANTHROPIC_AUTH_TOKEN"] == "or-key"
    # An empty value, and not an absent name. An absent name lets the child
    # find a key elsewhere and bill the wrong account.
    assert env["ANTHROPIC_API_KEY"] == ""


def test_a_base_url_of_the_config_wins_over_the_default():
    env = build_env(
        Provider(kind="openrouter", api_key="k", base_url="https://proxy/api"), PARENT
    )
    assert env["ANTHROPIC_BASE_URL"] == "https://proxy/api"


def test_a_kind_that_needs_a_key_and_has_none_stops_the_run():
    with pytest.raises(ProviderError, match="no key"):
        build_env(Provider(kind="openrouter"), PARENT)


def test_an_unknown_kind_stops_the_run_and_names_the_kind():
    with pytest.raises(ProviderError, match="moonshot"):
        build_env(Provider(kind="moonshot"), PARENT)


def test_a_config_dir_keeps_the_user_configuration_out_of_the_child(tmp_path):
    env = build_env(Provider(kind="subscription"), PARENT, config_dir=tmp_path)
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'renfield.provider'`

- [ ] **Step 3: Write `src/renfield/provider.py`**

```python
"""Build the environment of a child `claude` process.

The child starts from an allowlist, and not from the environment of the
parent. This keeps the key of the parent, the CLAUDE_CODE_* variables of a
parent session, and each other secret out of the child.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

ALLOWLIST = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "TERM",
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api"

KINDS = ("subscription", "anthropic-api", "openrouter")


class ProviderError(Exception):
    """The provider part of the configuration is not usable."""


@dataclass
class Provider:
    kind: str = "subscription"
    api_key: str | None = None
    base_url: str | None = None


def build_env(
    provider: Provider,
    parent: Mapping[str, str],
    config_dir: Path | None = None,
) -> dict[str, str]:
    """Give the environment for 1 child process."""
    env = {name: parent[name] for name in ALLOWLIST if name in parent}

    if provider.kind == "subscription":
        pass
    elif provider.kind == "anthropic-api":
        env["ANTHROPIC_API_KEY"] = _key(provider)
    elif provider.kind == "openrouter":
        env["ANTHROPIC_BASE_URL"] = provider.base_url or OPENROUTER_BASE_URL
        env["ANTHROPIC_AUTH_TOKEN"] = _key(provider)
        # An empty value, and not an absent name. An absent name lets the
        # child find a key elsewhere and bill the wrong account.
        env["ANTHROPIC_API_KEY"] = ""
    else:
        raise ProviderError(
            f"unknown provider kind: {provider.kind!r}. "
            f"The kinds are {', '.join(KINDS)}."
        )

    if config_dir is not None:
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)

    return env


def _key(provider: Provider) -> str:
    if not provider.api_key:
        raise ProviderError(f"provider kind {provider.kind!r} has no key")
    return provider.api_key
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_provider.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/renfield/provider.py tests/test_provider.py
git commit -m "feat: the environment of the child, from an allowlist"
```

---

## Task 4: `paths.py`, the 4 paths and the placeholders

**Files:**
- Create: `src/renfield/paths.py`
- Create: `tests/test_paths.py`

**Interfaces:**
- Produces: `Paths` (the templates), `RunPaths` (the resolved paths), `PathError`, `STAMP_FORMAT`, `PLACEHOLDERS`, `render(paths, step, stamp=None) -> RunPaths`, `make_dirs(run) -> None`.

**Why 2 types.** `Paths` holds what a person wrote, with `{step}` and `{stamp}` still in it. `RunPaths` holds finished paths. A function that takes `RunPaths` cannot receive a template by mistake.

- [ ] **Step 1: Write the failing test**

`tests/test_paths.py`:

```python
import re

import pytest

from renfield.paths import (
    PLACEHOLDERS,
    STAMP_FORMAT,
    PathError,
    Paths,
    make_dirs,
    render,
)


def test_the_default_layout():
    run = render(Paths(), step="review", stamp="2026-10-12T14-03-51")
    assert str(run.run_dir) == "runs/2026-10-12T14-03-51-review"
    assert str(run.prompt) == "runs/2026-10-12T14-03-51-review/prompts/review.md"
    assert str(run.transcript) == (
        "runs/2026-10-12T14-03-51-review/transcripts/review.jsonl"
    )
    assert str(run.artifacts) == "runs/2026-10-12T14-03-51-review/artifacts"
    assert str(run.record) == "runs/2026-10-12T14-03-51-review/record.json"


def test_a_step_name_with_a_dot_keeps_its_last_part():
    run = render(Paths(), step="review.deep", stamp="s")
    assert run.prompt.name == "deep.md"


def test_an_absent_stamp_is_the_time_now_in_the_documented_format():
    run = render(Paths(), step="x")
    stamp = run.run_dir.name.removesuffix("-x")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}", stamp), stamp
    assert STAMP_FORMAT == "%Y-%m-%dT%H-%M-%S"


def test_each_of_the_4_paths_is_configurable():
    run = render(
        Paths(
            run_dir="out",
            prompt="p.md",
            transcript="t.jsonl",
            artifacts="files",
            record="r.json",
        ),
        step="x",
        stamp="s",
    )
    assert str(run.run_dir) == "out"
    assert str(run.prompt) == "out/p.md"
    assert str(run.transcript) == "out/t.jsonl"
    assert str(run.artifacts) == "out/files"
    assert str(run.record) == "out/r.json"


def test_the_placeholders_are_the_2_that_the_spec_names():
    assert set(PLACEHOLDERS) == {"step", "stamp"}


def test_an_unknown_placeholder_is_an_error_and_names_the_allowed_ones():
    with pytest.raises(PathError) as caught:
        render(Paths(run_dir="runs/{stepp}"), step="x", stamp="s")
    message = str(caught.value)
    assert "run_dir" in message
    assert "stepp" in message
    assert "step" in message and "stamp" in message


@pytest.mark.parametrize("bad", ["runs/{step!x}", "runs/{step:d}"])
def test_a_bad_conversion_or_format_spec_is_a_path_error(bad):
    """`_check` passes these, because the placeholder name is `step`.
    `.format` then raises a bare ValueError. Measured: "Unknown conversion
    specifier x" and "Unknown format code 'd' for object of type 'str'"."""
    with pytest.raises(PathError) as caught:
        render(Paths(run_dir=bad), step="x", stamp="s")
    message = str(caught.value)
    assert "run_dir" in message
    assert bad in message


@pytest.mark.parametrize("bad", ["runs/{step", "runs/step}", "runs/{{step}"])
def test_an_unbalanced_brace_is_a_path_error_and_names_the_key(bad):
    """`Formatter().parse` raises a bare ValueError for these 3 forms. The CLI
    catches PathError only, so a bare ValueError would reach a person as a
    traceback."""
    with pytest.raises(PathError) as caught:
        render(Paths(run_dir=bad), step="x", stamp="s")
    message = str(caught.value)
    assert "run_dir" in message
    assert bad in message


def test_an_absolute_value_for_a_relative_key_is_an_error():
    """pathlib drops the left side of a join with an absolute path, so a
    value of /tmp/p.md would leave run_dir with no warning."""
    with pytest.raises(PathError, match="prompt"):
        render(Paths(prompt="/tmp/p.md"), step="x", stamp="s")


def test_an_absolute_run_dir_is_allowed():
    run = render(Paths(run_dir="/tmp/out"), step="x", stamp="s")
    assert str(run.run_dir) == "/tmp/out"


def test_make_dirs_builds_the_parent_of_each_file_and_the_artifacts_folder(tmp_path):
    run = render(Paths(run_dir=str(tmp_path / "out")), step="x", stamp="s")
    make_dirs(run)
    assert run.artifacts.is_dir()
    assert run.prompt.parent.is_dir()
    assert run.transcript.parent.is_dir()
    assert run.record.parent.is_dir()
    assert not run.prompt.exists(), "make_dirs writes no file"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'renfield.paths'`

- [ ] **Step 3: Write `src/renfield/paths.py`**

```python
"""The 4 paths of 1 run, and the 2 placeholders of a path.

`Paths` holds what a person wrote, with the placeholders still in it.
`RunPaths` holds finished paths. A function that takes `RunPaths` cannot
receive a template by mistake.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from string import Formatter

STAMP_FORMAT = "%Y-%m-%dT%H-%M-%S"
PLACEHOLDERS = ("step", "stamp")

# Each key below `run_dir` is relative to it.
RELATIVE = ("prompt", "transcript", "artifacts", "record")


class PathError(Exception):
    """A path of the configuration is not usable."""


@dataclass
class Paths:
    """The path templates. Each value accepts {step} and {stamp}."""

    run_dir: str = "runs/{stamp}-{step}"
    prompt: str = "prompts/{step}.md"
    transcript: str = "transcripts/{step}.jsonl"
    artifacts: str = "artifacts"
    record: str = "record.json"


@dataclass
class RunPaths:
    """The finished paths of 1 run."""

    run_dir: Path
    prompt: Path
    transcript: Path
    artifacts: Path
    record: Path


def render(paths: Paths, *, step: str, stamp: str | None = None) -> RunPaths:
    """Fill the placeholders of each path, and give the finished paths.

    `step` keeps its last part only, so `review.deep` gives `deep`.
    """
    short = step.rsplit(".", 1)[-1]
    values = {
        "step": short,
        "stamp": stamp if stamp is not None else datetime.now().strftime(STAMP_FORMAT),
    }

    filled = {}
    for key in ("run_dir", *RELATIVE):
        template = getattr(paths, key)
        _check(key, template)
        try:
            filled[key] = template.format(**values)
        except (ValueError, KeyError, IndexError) as error:
            # `_check` passes a template whose placeholder names are known,
            # and `.format` can still fail on a conversion or a format spec.
            # Measured: "{step!x}" and "{step:d}" both raise ValueError.
            # Task 9's CLI catches PathError only.
            raise PathError(
                f"{key}: the value {template!r} is not a usable path: {error}"
            ) from error

    for key in RELATIVE:
        if Path(filled[key]).is_absolute():
            raise PathError(
                f"{key}: the value {filled[key]!r} is an absolute path, and "
                f"{key} is relative to run_dir"
            )

    run_dir = Path(filled["run_dir"])
    return RunPaths(
        run_dir=run_dir,
        prompt=run_dir / filled["prompt"],
        transcript=run_dir / filled["transcript"],
        artifacts=run_dir / filled["artifacts"],
        record=run_dir / filled["record"],
    )


def _check(key: str, template: str) -> None:
    """Stop a template that names a placeholder that does not exist."""
    try:
        names = [
            name for _, name, _, _ in Formatter().parse(template) if name is not None
        ]
    except ValueError as error:
        # `Formatter().parse` raises ValueError for an unbalanced brace. The
        # CLI of task 9 catches PathError, so a bare ValueError would reach a
        # person as a traceback.
        raise PathError(
            f"{key}: the value {template!r} is not a usable path: {error}"
        ) from error
    unknown = [name for name in names if name not in PLACEHOLDERS]
    if unknown:
        raise PathError(
            f"{key}: the placeholder {unknown[0]!r} does not exist. "
            f"The placeholders are {', '.join('{%s}' % p for p in PLACEHOLDERS)}."
        )


def make_dirs(run: RunPaths) -> None:
    """Build the folder of each path. Write no file."""
    run.artifacts.mkdir(parents=True, exist_ok=True)
    for path in (run.prompt, run.transcript, run.record):
        path.parent.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_paths.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/renfield/paths.py tests/test_paths.py
git commit -m "feat: the 4 run paths, and the 2 placeholders"
```

---

## Task 5: `config.py`, the file, the precedence, and the ranges

**Files:**
- Create: `src/renfield/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: `Provider` from task 3, `Paths` from task 4.
- Produces: `Skill`, `Step`, `Settings`, `ConfigError`, `EFFORTS`, `TIMEOUT_RANGE`, `MAX_USD_RANGE`, `RETRIES_RANGE`, `NAME_PATTERN`, `load(path=None, *, overrides=None, env=None) -> Settings`.

**The rule that makes this module worth its own task.** An unknown key in the file is an error, and not a value that Renfield ignores. A person who writes `timout_min = 60` must read a message, and must not get the default of 20 with no word about it.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
import pytest

from renfield.config import ConfigError, Settings, load

FULL = """
[provider]
kind        = "openrouter"
api_key_env = "OR_KEY"
model       = "deepseek/deepseek-v4.1-flash"
effort      = "medium"

[step]
timeout_min = 30
max_usd     = 4.0
retries     = 1

[paths]
run_dir = "out/{step}"
record  = "r.json"
"""


def write(tmp_path, text):
    path = tmp_path / "renfield.toml"
    path.write_text(text)
    return path


def test_a_file_with_no_step_table_gives_the_documented_defaults(tmp_path):
    settings = load(write(tmp_path, '[provider]\nmodel = "m"\n'), env={})
    assert isinstance(settings, Settings)
    assert settings.provider.kind == "subscription"
    assert settings.step.effort == "high"
    assert settings.step.timeout_min == 20
    assert settings.step.max_usd is None
    assert settings.step.retries == 2
    assert settings.paths.run_dir == "runs/{stamp}-{step}"


def test_the_file_wins_over_the_defaults(tmp_path):
    settings = load(write(tmp_path, FULL), env={"OR_KEY": "k"})
    assert settings.provider.kind == "openrouter"
    assert settings.provider.api_key == "k"
    assert settings.step.model == "deepseek/deepseek-v4.1-flash"
    assert settings.step.effort == "medium"
    assert settings.step.timeout_min == 30
    assert settings.step.max_usd == 4.0
    assert settings.step.retries == 1
    assert settings.paths.run_dir == "out/{step}"
    assert settings.paths.record == "r.json"
    # A key that the file does not set keeps its default.
    assert settings.paths.prompt == "prompts/{step}.md"


def test_an_override_wins_over_the_file_and_changes_1_key_only(tmp_path):
    settings = load(
        write(tmp_path, FULL),
        overrides={"model": "claude-opus-5", "effort": None},
        env={"OR_KEY": "k"},
    )
    assert settings.step.model == "claude-opus-5"
    # effort was None, so the file value stands.
    assert settings.step.effort == "medium"


def test_no_file_and_no_model_names_both_ways_to_set_it():
    with pytest.raises(ConfigError) as caught:
        load(None, overrides={"name": "x"}, env={})
    assert "model" in str(caught.value)
    assert "--model" in str(caught.value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("timeout_min", 0),
        ("timeout_min", 241),
        ("retries", -1),
        ("retries", 3),
        ("max_usd", 0.0),
        ("max_usd", 1000.1),
    ],
)
def test_a_number_outside_its_range_names_the_key_the_range_and_the_value(
    tmp_path, key, value
):
    text = f'[provider]\nmodel = "m"\n\n[step]\n{key} = {value}\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    message = str(caught.value)
    assert key in message
    # Not `str(value) in message`: for timeout_min=0 the "240" of the range
    # satisfies that, so the assertion would pass if the message dropped the
    # value. Measured.
    assert f"the value is {value}" in message
    assert " to " in message, "the message must name the range"


@pytest.mark.parametrize("value", ["low", "medium", "high", "xhigh", "max"])
def test_each_documented_effort_is_accepted(tmp_path, value):
    text = f'[provider]\nmodel = "m"\neffort = "{value}"\n'
    assert load(write(tmp_path, text), env={}).step.effort == value


def test_an_effort_that_is_not_in_the_list_names_the_list(tmp_path):
    text = '[provider]\nmodel = "m"\neffort = "ultra"\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    assert "ultra" in str(caught.value)
    assert "xhigh" in str(caught.value)


def test_an_unknown_key_of_the_file_is_an_error_and_not_a_silent_default(tmp_path):
    text = '[provider]\nmodel = "m"\n\n[step]\ntimout_min = 60\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    assert "timout_min" in str(caught.value)


def test_an_unknown_table_of_the_file_is_an_error(tmp_path):
    text = '[provider]\nmodel = "m"\n\n[steps]\ntimeout_min = 60\n'
    with pytest.raises(ConfigError, match="steps"):
        load(write(tmp_path, text), env={})


def test_a_key_and_a_key_variable_together_is_an_error(tmp_path):
    text = (
        '[provider]\nmodel = "m"\nkind = "openrouter"\n'
        'api_key = "literal"\napi_key_env = "OR_KEY"\n'
    )
    with pytest.raises(ConfigError, match="api_key"):
        load(write(tmp_path, text), env={"OR_KEY": "k"})


def test_a_key_variable_that_the_environment_does_not_hold_names_it(tmp_path):
    text = '[provider]\nmodel = "m"\nkind = "openrouter"\napi_key_env = "OR_KEY"\n'
    with pytest.raises(ConfigError, match="OR_KEY"):
        load(write(tmp_path, text), env={})


def test_a_kind_that_needs_a_key_and_has_no_source_stops_at_the_config(tmp_path):
    text = '[provider]\nmodel = "m"\nkind = "anthropic-api"\n'
    with pytest.raises(ConfigError, match="anthropic-api"):
        load(write(tmp_path, text), env={})


def test_a_subscription_needs_no_key(tmp_path):
    settings = load(write(tmp_path, '[provider]\nmodel = "m"\n'), env={})
    assert settings.provider.api_key is None


def test_a_file_that_is_not_there_is_an_error_that_names_the_path(tmp_path):
    with pytest.raises(ConfigError, match="missing.toml"):
        load(tmp_path / "missing.toml", env={})


@pytest.mark.parametrize("name", ["review", "a", "review.deep", "a-b_c.1"])
def test_a_good_step_name_is_accepted(name):
    assert load(None, overrides={"name": name, "model": "m"}, env={}).step.name == name


@pytest.mark.parametrize("name", ["Review", "a b", "x" * 65, "", "a/b"])
def test_a_bad_step_name_is_an_error(name):
    with pytest.raises(ConfigError, match="name"):
        load(None, overrides={"name": name, "model": "m"}, env={})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'renfield.config'`

- [ ] **Step 3: Write `src/renfield/config.py`**

```python
"""The input file, the precedence, and the range of each key.

The precedence is: built-in defaults, then the file, then the call.

Each numeric and each enumerated key has a range, checked here, with a
message that names the key, the range, and the value. A type check is not a
range check: `timeout_min = 0` passes a type check and kills the child at
once.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from renfield.paths import Paths
from renfield.provider import KINDS, Provider

EFFORTS = ("low", "medium", "high", "xhigh", "max")
TIMEOUT_RANGE = (1, 240)
MAX_USD_RANGE = (0.01, 1000.0)
RETRIES_RANGE = (0, 2)
NAME_PATTERN = re.compile(r"^[a-z0-9._-]{1,64}$")

PROVIDER_KEYS = ("kind", "model", "effort", "api_key", "api_key_env", "base_url")
STEP_KEYS = ("timeout_min", "max_usd", "retries")
PATH_KEYS = ("run_dir", "prompt", "transcript", "artifacts", "record")
TABLES = {"provider": PROVIDER_KEYS, "step": STEP_KEYS, "paths": PATH_KEYS}


class ConfigError(Exception):
    """The configuration is not usable."""


@dataclass
class Skill:
    plugin: Path
    invoke: str | None = None


@dataclass
class Step:
    name: str
    model: str
    effort: str = "high"
    timeout_min: int = 20
    max_usd: float | None = None
    retries: int = 2
    add_dirs: list[Path] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)


@dataclass
class Settings:
    provider: Provider
    step: Step
    paths: Paths


def load(
    path: Path | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Read the file, apply the overrides, check each range, and give the settings."""
    data = _read(path)
    given = {key: value for key, value in (overrides or {}).items() if value is not None}
    env = {} if env is None else env

    def pick(table: str, key: str, default: Any = None) -> Any:
        if key in given:
            return given[key]
        return data.get(table, {}).get(key, default)

    # The file cannot set the name: 1 file serves many steps. The CLI passes
    # it, and the default serves a direct call of the library.
    name = given.get("name", "step")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise ConfigError(
            f"name: the value {name!r} is not 1 to 64 characters of a-z, 0-9, "
            f"'-', '_', and '.'"
        )

    model = pick("provider", "model")
    if not model:
        raise ConfigError(
            "model: no value. Set [provider] model in the file, or pass --model."
        )

    kind = _one_of("kind", pick("provider", "kind", "subscription"), KINDS)
    effort = _one_of("effort", pick("provider", "effort", "high"), EFFORTS)
    timeout_min = _in_range(
        "timeout_min", pick("step", "timeout_min", 20), TIMEOUT_RANGE, int
    )
    retries = _in_range("retries", pick("step", "retries", 2), RETRIES_RANGE, int)
    max_usd = pick("step", "max_usd")
    if max_usd is not None:
        max_usd = _in_range("max_usd", max_usd, MAX_USD_RANGE, float)

    provider = Provider(
        kind=kind,
        api_key=_api_key(kind, pick, env),
        base_url=pick("provider", "base_url"),
    )
    step = Step(
        name=name,
        model=str(model),
        effort=effort,
        timeout_min=timeout_min,
        max_usd=max_usd,
        retries=retries,
        add_dirs=[Path(p) for p in given.get("add_dirs", [])],
        skills=list(given.get("skills", [])),
    )
    paths = replace(
        Paths(),
        **{key: str(pick("paths", key)) for key in PATH_KEYS if pick("paths", key)},
    )
    return Settings(provider=provider, step=step, paths=paths)


def _read(path: Path | None) -> dict:
    """Read the TOML file, and stop on an unknown table or an unknown key."""
    if path is None:
        return {}
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"the file {path} is not there")
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error

    for table, values in data.items():
        if table not in TABLES:
            raise ConfigError(
                f"unknown table [{table}]. The tables are "
                f"{', '.join('[%s]' % name for name in TABLES)}."
            )
        if not isinstance(values, dict):
            raise ConfigError(f"[{table}] must be a table")
        for key in values:
            if key not in TABLES[table]:
                raise ConfigError(
                    f"unknown key {key!r} in [{table}]. The keys are "
                    f"{', '.join(TABLES[table])}."
                )
    return data


def _api_key(kind: str, pick, env: Mapping[str, str]) -> str | None:
    literal = pick("provider", "api_key")
    variable = pick("provider", "api_key_env")
    if literal and variable:
        raise ConfigError(
            "api_key and api_key_env are both set. Use 1 of them."
        )
    if literal:
        return str(literal)
    if variable:
        value = env.get(str(variable))
        if not value:
            raise ConfigError(
                f"api_key_env names {variable!r}, and that variable is empty "
                f"or absent"
            )
        return value
    if kind != "subscription":
        raise ConfigError(
            f"the provider kind {kind!r} needs a key. Set api_key_env or api_key."
        )
    return None


def _one_of(key: str, value: Any, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ConfigError(
            f"{key}: the value {value!r} is not one of {', '.join(allowed)}"
        )
    return str(value)


def _in_range(key: str, value: Any, limits: tuple, kind) -> Any:
    low, high = limits
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"{key}: the value {value!r} is not a number. The range is {low} to {high}."
        )
    if not low <= value <= high:
        raise ConfigError(
            f"{key}: the range is {low} to {high}, and the value is {value}"
        )
    if kind is int and value != int(value):
        # `int(30.9)` is 30, so without this the program would use a value
        # that the person did not write, and say nothing. A float that is
        # exactly whole, such as 30.0, is still accepted.
        raise ConfigError(f"{key}: the value {value} is not a whole number")
    return kind(value)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: each test passes.

- [ ] **Step 5: Commit**

```bash
git add src/renfield/config.py tests/test_config.py
git commit -m "feat: the input file, the precedence, and the range of each key"
```

---

## Task 6: `outputs.py`, the output file checks

**Files:**
- Create: `src/renfield/outputs.py`
- Create: `tests/test_outputs.py`

**Interfaces:**
- Produces: `check_outputs(artifacts, outputs, schemas) -> tuple[bool, str | None]`.

**The 3 checks, in this order:** the file is there, the file is not empty, and the data matches its schema. The order matters, because "the agent wrote nothing" and "the agent wrote the wrong shape" send a caller to 2 different places.

- [ ] **Step 1: Write the failing test**

`tests/test_outputs.py`:

```python
import json

from renfield.outputs import check_outputs

SCHEMA = {
    "type": "object",
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"enum": ["high", "medium", "low"]},
                },
            },
        }
    },
}


def schema_file(tmp_path, data=SCHEMA, name="verdict.schema.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def test_a_file_that_is_there_and_matches_its_schema_passes(tmp_path):
    (tmp_path / "verdict.json").write_text('{"findings": []}')
    ok, reason = check_outputs(
        tmp_path, ["verdict.json"], {"verdict.json": schema_file(tmp_path)}
    )
    assert (ok, reason) == (True, None)


def test_a_file_the_agent_did_not_write(tmp_path):
    ok, reason = check_outputs(tmp_path, ["verdict.json"], {})
    assert ok is False
    assert reason == "the agent did not write verdict.json"


def test_a_file_of_only_whitespace_is_empty(tmp_path):
    (tmp_path / "report.md").write_text("   \n\n")
    ok, reason = check_outputs(tmp_path, ["report.md"], {})
    assert ok is False
    assert reason == "report.md is empty"


def test_a_json_file_that_does_not_parse(tmp_path):
    (tmp_path / "verdict.json").write_text("{not json")
    ok, reason = check_outputs(tmp_path, ["verdict.json"], {})
    assert ok is False
    assert reason.startswith("verdict.json is not valid JSON")


def test_a_schema_failure_names_the_place_in_the_file(tmp_path):
    (tmp_path / "verdict.json").write_text(
        json.dumps({"findings": [{"severity": "high"}, {"severity": "blocker"}]})
    )
    ok, reason = check_outputs(
        tmp_path, ["verdict.json"], {"verdict.json": schema_file(tmp_path)}
    )
    assert ok is False
    assert reason.startswith("verdict.json: findings.1.severity:")
    assert "blocker" in reason


def test_a_missing_required_key_names_the_file(tmp_path):
    (tmp_path / "verdict.json").write_text("{}")
    ok, reason = check_outputs(
        tmp_path, ["verdict.json"], {"verdict.json": schema_file(tmp_path)}
    )
    assert ok is False
    assert reason.startswith("verdict.json: ")
    assert "findings" in reason


def test_a_file_with_no_schema_needs_only_to_be_there_and_not_empty(tmp_path):
    (tmp_path / "report.md").write_text("# the report\n")
    assert check_outputs(tmp_path, ["report.md"], {}) == (True, None)


def test_the_first_problem_is_the_one_that_is_reported(tmp_path):
    (tmp_path / "second.json").write_text("{not json")
    ok, reason = check_outputs(tmp_path, ["first.md", "second.json"], {})
    assert reason == "the agent did not write first.md"


def test_a_schema_for_a_file_that_is_not_an_output_is_an_error(tmp_path):
    (tmp_path / "verdict.json").write_text("{}")
    ok, reason = check_outputs(
        tmp_path, ["verdict.json"], {"other.json": schema_file(tmp_path)}
    )
    assert ok is False
    assert "other.json" in reason


def test_a_schema_file_that_is_not_there_is_an_error(tmp_path):
    (tmp_path / "verdict.json").write_text("{}")
    ok, reason = check_outputs(
        tmp_path, ["verdict.json"], {"verdict.json": tmp_path / "gone.json"}
    )
    assert ok is False
    assert "gone.json" in reason


def test_no_output_at_all_passes(tmp_path):
    assert check_outputs(tmp_path, [], {}) == (True, None)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_outputs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'renfield.outputs'`

- [ ] **Step 3: Write `src/renfield/outputs.py`**

```python
"""The checks of the files that the agent had to write.

A step that failed can still have written a good file. A rate limit or a
timeout can arrive after the work. `run_step` calls this function in that
case too, so that finished work is visible in the record.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema
from jsonschema.exceptions import best_match


def check_outputs(
    artifacts: Path,
    outputs: Sequence[str],
    schemas: Mapping[str, Path],
) -> tuple[bool, str | None]:
    """Say whether each output is there and correct, and why not."""
    reason = _first_problem(Path(artifacts), outputs, schemas)
    return (reason is None, reason)


def _first_problem(
    artifacts: Path, outputs: Sequence[str], schemas: Mapping[str, Path]
) -> str | None:
    extra = [name for name in schemas if name not in outputs]
    if extra:
        return (
            f"the schema list names {extra[0]!r}, and that name is not an output"
        )

    for name in outputs:
        path = artifacts / name
        if not path.is_file():
            return f"the agent did not write {name}"
        text = path.read_text().strip()
        if not text:
            return f"{name} is empty"

        if path.suffix != ".json":
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            return f"{name} is not valid JSON: {error}"

        schema_path = schemas.get(name)
        if schema_path is None:
            continue
        try:
            schema = _schema(str(schema_path))
        except (OSError, json.JSONDecodeError) as error:
            return f"the schema {schema_path} cannot be read: {error}"

        problem = _validate(data, schema)
        if problem is not None:
            return f"{name}: {problem}"
    return None


@lru_cache(maxsize=None)
def _schema(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _validate(data: Any, schema: dict) -> str | None:
    """Give the reason the data does not match, with the place in the file."""
    validator = jsonschema.Draft202012Validator(schema)
    error = best_match(validator.iter_errors(data))
    if error is None:
        return None
    place = ".".join(str(part) for part in error.absolute_path)
    return f"{place}: {error.message}" if place else error.message
```

**A file whose name ends in `.json` is parsed, with or without a schema.** A truncated file is a real failure of a killed agent, and the parse costs nothing. A schema is the second check, and it runs only when the caller gives one.

**The `blocked: true` key of `llm.py:359` is not here.** That is ruling P1. A caller that wants an agent to refuse a job checks its own key in its own schema.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_outputs.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/renfield/outputs.py tests/test_outputs.py
git commit -m "feat: the output file checks, with the place in the file"
```

---

## Task 7: `record.py`, the record and the console lines

**Files:**
- Create: `src/renfield/record.py`
- Create: `tests/test_record.py`

**Interfaces:**
- Produces: `StepRecord`, `ESTIMATED_KINDS`, `estimated(kind) -> bool`, `as_dict(record) -> dict`, `write_record(path, record) -> None`, `summary_line(record) -> str`.

**The field that this task exists for.** `cost_estimated` travels beside `cost_usd`. Claude Code prices every call at Anthropic rates, whatever vendor served it. A measured call on `meta-llama/llama-3.1-8b-instruct` reported 0.3141 USD where OpenRouter charges about 0.002 USD. A reader who adds an estimated cost to an invoice is wrong by 2 orders of 10.

- [ ] **Step 1: Write the failing test**

`tests/test_record.py`:

```python
import json

from renfield.record import (
    ESTIMATED_KINDS,
    StepRecord,
    as_dict,
    estimated,
    summary_line,
    write_record,
)


def a_record(**changes):
    values = dict(
        name="review",
        status="ok",
        provider="openrouter",
        model="deepseek/deepseek-v4.1-flash",
        effort="high",
        attempts=1,
        cost_usd=6.1630154321,
        num_turns=41,
        duration_s=318.2,
    )
    values.update(changes)
    return StepRecord(**values)


def test_a_subscription_and_an_openrouter_cost_are_estimates():
    assert set(ESTIMATED_KINDS) == {"subscription", "openrouter"}
    assert estimated("subscription") is True
    assert estimated("openrouter") is True


def test_only_an_api_key_cost_is_a_price():
    assert estimated("anthropic-api") is False


def test_the_cost_is_rounded_to_6_places_in_the_record():
    data = as_dict(a_record())
    assert data["cost_usd"] == 6.163015


def test_a_record_with_no_limit_has_no_unknown_cost_bound():
    """A killed step with no max_usd has no largest value that it could cost."""
    record = a_record(cost_known=False, cost_usd=0.0, unknown_usd=None)
    data = as_dict(record)
    assert data["cost_known"] is False
    assert data["unknown_usd"] is None


def test_a_killed_step_with_a_limit_reports_that_limit_as_the_bound():
    data = as_dict(a_record(cost_known=False, cost_usd=0.0, unknown_usd=4.0))
    assert data["unknown_usd"] == 4.0


def test_write_record_writes_valid_json_and_builds_the_folder(tmp_path):
    path = tmp_path / "deep" / "record.json"
    write_record(path, a_record())
    data = json.loads(path.read_text())
    assert data["name"] == "review"
    assert data["model"] == "deepseek/deepseek-v4.1-flash"


def test_the_summary_line_marks_an_estimated_cost(tmp_path):
    line = summary_line(a_record(cost_estimated=True))
    assert "review: ok" in line
    assert "41 turns" in line
    assert "318.2 s" in line
    assert "(estimated)" in line


def test_the_summary_line_of_a_price_does_not_say_estimated():
    line = summary_line(a_record(provider="anthropic-api", cost_estimated=False))
    assert "(estimated)" not in line


def test_the_summary_line_of_a_failed_step_names_its_class():
    line = summary_line(a_record(status="failed", error_class="rate_limited"))
    assert "failed" in line
    assert "rate_limited" in line


def test_the_summary_line_says_how_many_attempts_only_when_there_was_a_retry():
    assert "attempt" not in summary_line(a_record(attempts=1))
    assert "3 attempts" in summary_line(a_record(attempts=3))

```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_record.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'renfield.record'`

- [ ] **Step 3: Write `src/renfield/record.py`**

```python
"""The record of 1 step, the record file, and the console lines."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Claude Code prices every call at Anthropic rates, whatever vendor served
# it. Measured on 2026-09-16: a call on meta-llama/llama-3.1-8b-instruct
# reported 0.3141 USD, and OpenRouter charges about 0.002 USD for it.
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
    outputs: list[str] = field(default_factory=list)
    # True when each expected output is there and passes its checks. This can
    # be true for a step that failed: a limit can arrive after the agent wrote
    # a complete file.
    outputs_valid: bool = False


def estimated(kind: str) -> bool:
    """Say whether the cost of this provider kind is an estimate."""
    return kind in ESTIMATED_KINDS


def as_dict(record: StepRecord) -> dict:
    """Give the record as data, with the cost rounded."""
    data = asdict(record)
    data["cost_usd"] = round(data["cost_usd"], 6)
    if data["unknown_usd"] is not None:
        data["unknown_usd"] = round(data["unknown_usd"], 6)
    data["duration_s"] = round(data["duration_s"], 1)
    return data


def write_record(path: Path, record: StepRecord) -> None:
    """Write the record file. Build its folder first."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(as_dict(record), indent=2) + "\n")


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

```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_record.py -v`
Expected: each test passes.

- [ ] **Step 5: Commit**

```bash
git add src/renfield/record.py tests/test_record.py
git commit -m "feat: the step record, the record file, and the console lines"
```

---

## Task 8: `step.py`, the child process

**Files:**
- Create: `src/renfield/step.py`
- Create: `tests/test_step.py`

**Interfaces:**
- Consumes: each earlier module.
- Produces: `run_step(...) -> StepRecord`, `render_prompt(template, values, skills, path) -> str`, `RETRY_WAITS`, `STOP_WAIT_S`, `PromptError`.

**This is the only module that starts a child process.** It holds the 3 behaviours that a reviewer must not simplify: the process group, the SIGINT before the SIGKILL, and the retry that fires for 1 class only.

**2 arguments exist for the tests, and the spec does not name them.** `timeout_s` overrides `step.timeout_min * 60`, and `grace_s` overrides `STOP_WAIT_S`. Without them a timeout test waits 60 seconds and a kill test waits 15 more. Document both as "for a test" in the docstring.

**A measured race that will make a timeout test flake.** The fake agent installs its SIGINT handler after the Python interpreter starts, which takes about 0.1 s to 0.3 s. A test with `timeout_s=0.3` sends SIGINT before the handler exists, and the child dies with `-2` and an empty log. **Use `timeout_s=1.0` or more in a kill test.** This was measured on 2026-09-29.

- [ ] **Step 1: Write the failing test**

`tests/test_step.py`:

```python
import json
from pathlib import Path

import pytest

from renfield.config import Skill, Step
from renfield.paths import Paths
from renfield.provider import Provider
from renfield.step import PromptError, RETRY_WAITS, render_prompt, run_step
from renfield.testing import call_record, fake_claude

SUCCESS = json.dumps(
    {"type": "result", "subtype": "success", "is_error": False,
     "total_cost_usd": 1.25, "num_turns": 7, "duration_ms": 2000,
     "session_id": "abc",
     "usage": {"input_tokens": 10, "output_tokens": 20,
               "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40}}
) + "\n"

AUTH = json.dumps(
    {"type": "result", "subtype": "success", "is_error": True,
     "api_error_status": 401, "total_cost_usd": 0.1, "num_turns": 1,
     "result": "unauthorized"}
) + "\n"

TRANSIENT = json.dumps(
    {"type": "result", "subtype": "error", "is_error": True,
     "api_error_status": 503, "total_cost_usd": 0.2, "num_turns": 1,
     "result": "upstream"}
) + "\n"


def a_step(**changes):
    values = dict(name="review", model="m", effort="high", timeout_min=20)
    values.update(changes)
    return Step(**values)


def template_of(tmp_path, text="read $plan\n"):
    path = tmp_path / "t.md"
    path.write_text(text)
    return path


def call(tmp_path, program, *, step=None, values=None, waits=None, **extra):
    """Run 1 step against the fake program, in a fresh output folder."""
    taken = []
    record = run_step(
        step or a_step(),
        Provider(kind="subscription"),
        workdir=tmp_path,
        template=template_of(tmp_path),
        values=values if values is not None else {"plan": "docs/plan.md"},
        paths=Paths(run_dir=str(tmp_path / "out")),
        executable=str(program),
        parent_env={"PATH": "/usr/bin:/bin", "SECRET": "shh"},
        sleep=taken.append,
        **extra,
    )
    if waits is not None:
        waits.extend(taken)
    return record


# --- the command and the environment ---

def test_the_command_holds_each_measured_flag(tmp_path):
    call(tmp_path, fake_claude(tmp_path, stream=SUCCESS))
    argv = call_record(tmp_path)["argv"]
    assert argv[0] == "-p"
    for flag in ("--model", "--effort", "--output-format", "--verbose",
                 "--no-session-persistence", "--setting-sources",
                 "--strict-mcp-config", "--dangerously-skip-permissions"):
        assert flag in argv, flag
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--setting-sources") + 1] == ""


def test_a_step_with_no_limit_passes_no_budget_flag(tmp_path):
    call(tmp_path, fake_claude(tmp_path, stream=SUCCESS), step=a_step(max_usd=None))
    assert "--max-budget-usd" not in call_record(tmp_path)["argv"]


def test_a_step_with_a_limit_passes_it_to_the_child(tmp_path):
    call(tmp_path, fake_claude(tmp_path, stream=SUCCESS), step=a_step(max_usd=4.0))
    argv = call_record(tmp_path)["argv"]
    assert argv[argv.index("--max-budget-usd") + 1] == "4.0"


def test_each_skill_becomes_a_plugin_dir(tmp_path):
    step = a_step(skills=[Skill(plugin=tmp_path / "p", invoke="a:b")])
    call(tmp_path, fake_claude(tmp_path, stream=SUCCESS), step=step)
    argv = call_record(tmp_path)["argv"]
    assert argv[argv.index("--plugin-dir") + 1] == str(tmp_path / "p")


def test_the_child_gets_no_secret_of_the_parent(tmp_path):
    call(tmp_path, fake_claude(tmp_path, stream=SUCCESS))
    env = call_record(tmp_path)["env"]
    assert "SECRET" not in env
    assert env["PATH"] == "/usr/bin:/bin"


def test_the_prompt_goes_to_the_standard_input_of_the_child(tmp_path):
    call(tmp_path, fake_claude(tmp_path, stream=SUCCESS))
    assert call_record(tmp_path)["stdin"] == "read docs/plan.md\n"


def test_the_child_runs_in_the_working_directory(tmp_path):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    run_step(
        a_step(),
        Provider(kind="subscription"),
        workdir=workdir,
        template=template_of(tmp_path),
        values={"plan": "p"},
        paths=Paths(run_dir=str(tmp_path / "out")),
        executable=str(fake_claude(tmp_path, stream=SUCCESS)),
        parent_env={"PATH": "/usr/bin:/bin"},
    )
    assert call_record(tmp_path)["cwd"] == str(workdir)


# --- the prompt ---

def test_a_missing_value_stops_the_call_and_names_the_placeholder(tmp_path):
    with pytest.raises(PromptError, match="plan"):
        call(tmp_path, fake_claude(tmp_path, stream=SUCCESS), values={})


def test_the_invoke_skills_placeholder_holds_1_line_for_each_skill(tmp_path):
    text = render_prompt(
        "$invoke_skills",
        {},
        [Skill(plugin=Path("a"), invoke="x:y"), Skill(plugin=Path("b"))],
    )
    assert text == "/x:y"


def test_a_double_dollar_is_a_literal_dollar(tmp_path):
    assert render_prompt("cost $$5", {}, []) == "cost $5"


# --- the files of the run ---

def test_the_prompt_and_the_transcript_and_the_record_are_written(tmp_path):
    record = call(tmp_path, fake_claude(tmp_path, stream=SUCCESS))
    out = tmp_path / "out"
    assert (out / "prompts" / "review.md").read_text() == "read docs/plan.md\n"
    assert SUCCESS in (out / "transcripts" / "review.jsonl").read_text()
    written = json.loads((out / "record.json").read_text())
    assert written["status"] == "ok"
    assert record.run_dir == str(out)
    assert record.prompt == "prompts/review.md"


# --- what the result says ---

def test_a_success_carries_the_cost_the_tokens_and_the_tools(tmp_path):
    record = call(tmp_path, fake_claude(tmp_path, stream=SUCCESS))
    assert record.status == "ok"
    assert record.attempts == 1
    assert record.cost_usd == 1.25
    assert record.cache_read_tokens == 30
    assert record.cache_write_tokens == 40
    assert record.num_turns == 7
    assert record.cost_known is True


def test_a_subscription_cost_is_marked_as_an_estimate(tmp_path):
    record = call(tmp_path, fake_claude(tmp_path, stream=SUCCESS))
    assert record.cost_estimated is True


# --- the retry ---

def test_only_a_transient_failure_gets_a_retry(tmp_path):
    waits = []
    record = call(tmp_path, fake_claude(tmp_path, stream=TRANSIENT), waits=waits)
    assert record.attempts == 3
    assert waits == list(RETRY_WAITS)
    # The cost of each attempt is in the sum.
    assert record.cost_usd == pytest.approx(0.6)


def test_an_auth_failure_makes_1_attempt_only(tmp_path):
    waits = []
    record = call(tmp_path, fake_claude(tmp_path, stream=AUTH), waits=waits)
    assert record.attempts == 1
    assert record.error_class == "auth"
    assert waits == []


def test_retries_0_makes_1_attempt_of_a_transient_failure(tmp_path):
    record = call(tmp_path, fake_claude(tmp_path, stream=TRANSIENT),
                  step=a_step(retries=0))
    assert record.attempts == 1


# --- the timeout and the process group ---

def test_a_timeout_gives_the_timeout_class_and_names_the_limit(tmp_path):
    program = fake_claude(tmp_path, stream=SUCCESS, sleep_s=30)
    record = call(tmp_path, program, timeout_s=1.0, grace_s=0.5)
    assert record.error_class == "timeout"
    assert record.status == "failed"
    assert "minute" in record.error


def test_a_child_that_ignores_sigint_is_killed(tmp_path):
    """The escalation. The fake traps SIGINT and never stops, so only SIGKILL
    ends it. `timeout_s` is 1.0 and not 0.3: a smaller value sends SIGINT
    before the interpreter of the fake installs its handler, and the child
    then dies with -2 for the wrong reason. Measured on 2026-09-29."""
    program = fake_claude(tmp_path, stream=SUCCESS, sleep_s=30, on_int="ignore")
    record = call(tmp_path, program, timeout_s=1.0, grace_s=0.5)
    assert record.error_class == "timeout"
    assert record.child_exit_code == -9


def test_a_child_that_answers_sigint_reports_its_cost(tmp_path):
    """SIGINT gives a cost and SIGKILL does not. Measured by
    skarp/tools/probe-sigint.py."""
    program = fake_claude(tmp_path, stream=SUCCESS, sleep_s=30, on_int="stream")
    record = call(tmp_path, program, timeout_s=1.0, grace_s=5.0)
    assert record.error_class == "timeout"
    assert record.cost_usd == 1.25
    assert record.cost_known is True


def test_a_killed_call_reports_the_limit_as_the_unknown_cost(tmp_path):
    program = fake_claude(tmp_path, stream="", sleep_s=30, on_int="ignore")
    record = call(tmp_path, program, step=a_step(max_usd=4.0),
                  timeout_s=1.0, grace_s=0.5)
    assert record.cost_known is False
    assert record.unknown_usd == 4.0


def test_a_killed_call_with_no_limit_has_no_unknown_cost_bound(tmp_path):
    program = fake_claude(tmp_path, stream="", sleep_s=30, on_int="ignore")
    record = call(tmp_path, program, timeout_s=1.0, grace_s=0.5)
    assert record.cost_known is False
    assert record.unknown_usd is None


# --- the outputs ---

def test_a_step_that_wrote_its_output_is_ok(tmp_path):
    program = fake_claude(
        tmp_path, stream=SUCCESS, writes={str(tmp_path / "out" / "artifacts" / "v.json"): "{}"}
    )
    record = call(tmp_path, program, outputs=["v.json"])
    assert record.status == "ok"
    assert record.outputs_valid is True
    assert record.outputs == ["v.json"]


def test_a_step_that_wrote_nothing_gets_the_invalid_output_class(tmp_path):
    record = call(tmp_path, fake_claude(tmp_path, stream=SUCCESS), outputs=["v.json"])
    assert record.status == "failed"
    assert record.error_class == "invalid_output"
    assert "v.json" in record.error
    assert record.outputs_valid is False


def test_a_failed_step_that_wrote_a_good_file_says_so(tmp_path):
    """A limit can arrive after the work. 1 measured run wrote 42 KB and then
    hit a limit. `outputs_valid` must not hide that file."""
    program = fake_claude(
        tmp_path, stream=AUTH,
        writes={str(tmp_path / "out" / "artifacts" / "v.json"): "{}"},
    )
    record = call(tmp_path, program, outputs=["v.json"])
    assert record.status == "failed"
    assert record.error_class == "auth", "the failure keeps its own class"
    assert record.outputs_valid is True
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_step.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'renfield.step'`

- [ ] **Step 3: Write `src/renfield/step.py`**

`StepRecord` gains 1 field that task 7 did not need: `child_exit_code: int | None = None`. Add it to `record.py` in this task, with its comment, and keep the test of task 7 green.

```python
"""Run 1 agent as a child process, and give its record.

This is the only module that starts a child process.

3 behaviours here are measured facts, and not preferences:

1. The child starts in its own session, so a timeout stops the whole process
   group. The child starts children of its own.
2. A timeout sends SIGINT first. Claude Code answers it with its result
   event, which holds the cost. SIGKILL cannot be caught, so it loses that
   cost.
3. Only the class `transient` gets a retry. A retry of a rate limit costs 2
   waits and a second full call, and it fails again.
"""

from __future__ import annotations

import os
import signal
import string
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from renfield.config import Skill, Step
from renfield.outputs import check_outputs
from renfield.paths import Paths, make_dirs, render as render_paths
from renfield.provider import Provider, build_env
from renfield.record import StepRecord, estimated, write_record
from renfield.stream import describe_event, read_stream

RETRY_CLASS = "transient"
RETRY_WAITS = (30, 120)
# The wait between SIGINT and SIGKILL.
STOP_WAIT_S = 15.0


class PromptError(Exception):
    """The template needs a value that the caller did not give."""


def render_prompt(
    text: str, values: Mapping[str, str], skills: Sequence[Skill]
) -> str:
    """Fill the template, and give the text.

    A missing value raises. It does not write an empty string: a prompt that
    lost a section is worse than a call that did not start.
    """
    filled = dict(values)
    filled["invoke_skills"] = "\n".join(
        f"/{skill.invoke}" for skill in skills if skill.invoke
    )
    try:
        return string.Template(text).substitute(filled)
    except KeyError as error:
        raise PromptError(
            f"the template needs the value {error.args[0]!r}, and the call "
            f"did not give it"
        ) from error
    except ValueError as error:
        raise PromptError(
            f"the template holds a bad placeholder: {error}. Write a literal "
            f"dollar as $$."
        ) from error


def run_step(
    step: Step,
    provider: Provider,
    *,
    workdir: Path,
    template: Path,
    values: Mapping[str, str],
    paths: Paths,
    outputs: Sequence[str] = (),
    schemas: Mapping[str, Path] | None = None,
    executable: str = "claude",
    parent_env: Mapping[str, str] | None = None,
    config_dir: Path | None = None,
    on_line: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    timeout_s: float | None = None,
    grace_s: float = STOP_WAIT_S,
) -> StepRecord:
    """Run 1 step, write its files, and give its record.

    `timeout_s` and `grace_s` are for a test. A test cannot wait 60 seconds
    for `timeout_min`, and it cannot wait 15 more for the escalation.
    """
    run = render_paths(paths, step=step.name)
    make_dirs(run)

    prompt = render_prompt(template.read_text(), values, step.skills)
    run.prompt.write_text(prompt)

    record = StepRecord(
        name=step.name,
        status="failed",
        provider=provider.kind,
        model=step.model,
        effort=step.effort,
        cost_estimated=estimated(provider.kind),
        run_dir=str(run.run_dir),
        prompt=str(run.prompt.relative_to(run.run_dir)),
        transcript=str(run.transcript.relative_to(run.run_dir)),
    )

    command = _command(step, run, executable)
    env = build_env(provider, parent_env or os.environ, config_dir)
    limit_s = timeout_s if timeout_s is not None else step.timeout_min * 60
    waits = RETRY_WAITS[: step.retries]

    for attempt in range(1, len(waits) + 2):
        record.attempts = attempt
        result, child_exit_code = _run_once(
            command,
            prompt,
            env=env,
            workdir=Path(workdir),
            transcript_path=run.transcript,
            timeout_s=limit_s,
            grace_s=grace_s,
            on_line=on_line,
        )
        record.cost_usd += result.cost_usd
        record.input_tokens = result.input_tokens
        record.output_tokens = result.output_tokens
        record.cache_read_tokens = result.cache_read_tokens
        record.cache_write_tokens = result.cache_write_tokens
        record.num_turns = result.num_turns
        record.tool_calls = result.tool_calls
        record.duration_s = result.duration_s
        record.error_class = result.error_class
        record.error = result.error
        record.cost_known = result.cost_known
        record.child_exit_code = child_exit_code
        record.unknown_usd = None if result.cost_known else step.max_usd

        if result.error_class != RETRY_CLASS or attempt == len(waits) + 1:
            break
        sleep(waits[attempt - 1])

    if not record.cost_known and record.error:
        limit = (
            f"Its limit is {step.max_usd} USD."
            if step.max_usd is not None
            else "The step had no limit, so no value bounds it."
        )
        record.error += f". Renfield did not measure the cost of this step. {limit}"

    valid, failure = check_outputs(run.artifacts, outputs, schemas or {})
    record.outputs_valid = valid
    if record.error_class is None:
        if valid:
            record.status = "ok"
            record.outputs = list(outputs)
        else:
            record.error_class = "invalid_output"
            record.error = failure
    elif valid:
        record.outputs = list(outputs)

    write_record(run.record, record)
    return record


def _command(step: Step, run, executable: str) -> list[str]:
    """Build the command of docs/design.md, section 3.1."""
    command = [
        executable,
        "-p",
        "--model",
        step.model,
        "--effort",
        step.effort,
        "--input-format",
        "text",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        # The child must not read the settings, the hooks, or the MCP servers
        # of the person who started it.
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--dangerously-skip-permissions",
    ]
    if step.max_usd is not None:
        command += ["--max-budget-usd", str(step.max_usd)]
    for folder in (run.artifacts, *step.add_dirs):
        if Path(folder).is_dir():
            command += ["--add-dir", str(folder)]
    for skill in step.skills:
        command += ["--plugin-dir", str(skill.plugin)]
    return command


def _run_once(
    command: Sequence[str],
    prompt: str,
    *,
    env: Mapping[str, str],
    workdir: Path,
    transcript_path: Path,
    timeout_s: float,
    grace_s: float,
    on_line: Callable[[str], None] | None,
):
    """Start 1 child, read its stream to the end, and give the result."""
    started = time.monotonic()
    process = subprocess.Popen(
        list(command),
        cwd=str(workdir),
        env=dict(env),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    timed_out = threading.Event()
    watchdog = threading.Timer(
        timeout_s, _kill_group, args=(process, timed_out, grace_s)
    )
    watchdog.start()
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(prompt)
        process.stdin.close()
        with transcript_path.open("a") as transcript:
            result = read_stream(
                _lines(process.stdout, transcript),
                on_event=_console(on_line) if on_line else None,
            )
        process.wait()
    except KeyboardInterrupt:
        # Ctrl-C. Kill the child and wait for it, so that no paid call stays
        # alive after the run stops.
        _kill(process)
        process.wait()
        raise
    finally:
        watchdog.cancel()

    if timed_out.is_set():
        result.ok = False
        result.error_class = "timeout"
        result.error = f"the step passed its limit of {timeout_s / 60:g} minutes"
        if result.thinking_tokens:
            result.error += f", after about {result.thinking_tokens} thinking tokens"
        result.duration_s = time.monotonic() - started
    return result, process.returncode


def _lines(stdout, transcript) -> Iterator[str]:
    for line in stdout:
        transcript.write(line if line.endswith("\n") else line + "\n")
        transcript.flush()
        yield line


def _console(on_line: Callable[[str], None]) -> Callable[[dict[str, Any]], None]:
    def handle(event: dict[str, Any]) -> None:
        line = describe_event(event)
        if line:
            on_line(line)

    return handle


def _kill_group(
    process: subprocess.Popen, timed_out: threading.Event, grace_s: float
) -> None:
    """Stop the child of a step that passed its limit.

    SIGINT first: Claude Code answers it with its result event, which holds
    the cost of the call. SIGKILL cannot be caught, so it loses that cost. A
    child that does not stop in `grace_s` seconds gets SIGKILL.
    """
    timed_out.set()
    _signal(process, signal.SIGINT)
    end = time.monotonic() + grace_s
    while time.monotonic() < end:
        if process.poll() is not None:
            return
        time.sleep(0.05)
    _kill(process)


def _kill(process: subprocess.Popen) -> None:
    """Kill the process group of the child.

    The child starts in a new session, so a signal of the terminal does not
    reach it. Without this call the model keeps working, and the call keeps
    paying.
    """
    _signal(process, signal.SIGKILL)


def _signal(process: subprocess.Popen, number: int) -> None:
    """Send 1 signal to the process group of the child.

    A child that the parent has not yet reaped can lose its group, so a
    missing group is not an error here.
    """
    try:
        os.killpg(os.getpgid(process.pid), number)
    except (ProcessLookupError, PermissionError):
        pass
```

- [ ] **Step 4: Add `child_exit_code` to `record.py`**

```python
    # The exit code of the child. -9 says that SIGKILL ended it, and the cost
    # of that call is lost.
    child_exit_code: int | None = None
```

- [ ] **Step 5: Run each test and watch them pass**

Run: `uv run pytest -v`
Expected: each test of each module passes.

**If `test_a_child_that_ignores_sigint_is_killed` fails with `-2` and not `-9`**, the test is wrong and not the code. Read the measured race in the heading of this task.

- [ ] **Step 6: Commit**

```bash
git add src/renfield/step.py src/renfield/record.py tests/test_step.py
git commit -m "feat: run 1 agent as a child, with the retry and the process group"
```

---

## Task 9: `cli.py`, the public names, and the README

**Files:**
- Create: `src/renfield/cli.py`
- Modify: `src/renfield/__init__.py`
- Create: `tests/test_cli.py`
- Create: `README.md`

**Interfaces:**
- Consumes: each module.
- Produces: `main(argv=None) -> int`, and the `renfield` script of `pyproject.toml`.

**The contract that your calling agent depends on.** Exit 4 and exit 5 must stay apart. A caller retries a 4. A caller must never retry a 5, because a 5 says the prompt is wrong, and the next call writes the same bad file.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
import json

import pytest

from renfield.cli import main
from renfield.testing import call_record, fake_claude

SUCCESS = json.dumps(
    {"type": "result", "subtype": "success", "is_error": False,
     "total_cost_usd": 1.25, "num_turns": 7, "duration_ms": 2000,
     "usage": {"input_tokens": 1, "output_tokens": 2}}
) + "\n"

AUTH = json.dumps(
    {"type": "result", "subtype": "success", "is_error": True,
     "api_error_status": 401, "total_cost_usd": 0.1, "result": "unauthorized"}
) + "\n"


def argv(tmp_path, program, *extra):
    template = tmp_path / "t.md"
    template.write_text("read $plan\n")
    return [
        "run",
        "--template", str(template),
        "--value", "plan=docs/plan.md",
        "--workdir", str(tmp_path),
        "--run-dir", str(tmp_path / "out"),
        "--model", "m",
        "--executable", str(program),
        *extra,
    ]


def test_a_step_that_works_exits_0_and_names_the_record_last(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    code = main(argv(tmp_path, program))
    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-1] == f"record: {tmp_path / 'out' / 'record.json'}"
    assert json.loads((tmp_path / "out" / "record.json").read_text())["status"] == "ok"


def test_a_value_outside_its_range_exits_1_and_writes_to_stderr(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    code = main(argv(tmp_path, program, "--timeout-min", "0"))
    assert code == 1
    error = capsys.readouterr().err
    assert "timeout_min" in error
    assert "1 to 240" in error


def test_a_step_that_failed_exits_4(tmp_path):
    program = fake_claude(tmp_path, stream=AUTH)
    assert main(argv(tmp_path, program)) == 4


def test_a_missing_output_exits_5_and_not_4(tmp_path):
    """A caller retries a 4 and must never retry a 5."""
    program = fake_claude(tmp_path, stream=SUCCESS)
    assert main(argv(tmp_path, program, "--output", "verdict.json")) == 5


def test_an_output_that_is_there_exits_0(tmp_path):
    out = tmp_path / "out" / "artifacts" / "verdict.json"
    program = fake_claude(tmp_path, stream=SUCCESS, writes={str(out): "{}"})
    assert main(argv(tmp_path, program, "--output", "verdict.json")) == 0


def test_an_output_that_fails_its_schema_exits_5(tmp_path, capsys):
    schema = tmp_path / "v.schema.json"
    schema.write_text(json.dumps({"type": "object", "required": ["findings"]}))
    out = tmp_path / "out" / "artifacts" / "verdict.json"
    program = fake_claude(tmp_path, stream=SUCCESS, writes={str(out): "{}"})
    code = main(
        argv(tmp_path, program, "--output", "verdict.json",
             "--schema", f"verdict.json={schema}")
    )
    assert code == 5
    assert "findings" in capsys.readouterr().err


def test_render_only_writes_the_prompt_and_starts_no_child(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    code = main(argv(tmp_path, program, "--render-only"))
    assert code == 0
    assert (tmp_path / "out" / "prompts" / "t.md").read_text() == "read docs/plan.md\n"
    with pytest.raises(FileNotFoundError):
        call_record(tmp_path)
    assert "prompts/t.md" in capsys.readouterr().out


def test_the_step_name_comes_from_the_template_when_no_name_is_given(tmp_path):
    program = fake_claude(tmp_path, stream=SUCCESS)
    main(argv(tmp_path, program))
    assert json.loads((tmp_path / "out" / "record.json").read_text())["name"] == "t"


def test_a_name_flag_wins_over_the_template_stem(tmp_path):
    program = fake_claude(tmp_path, stream=SUCCESS)
    main(argv(tmp_path, program, "--name", "review"))
    data = json.loads((tmp_path / "out" / "record.json").read_text())
    assert data["name"] == "review"
    assert (tmp_path / "out" / "prompts" / "review.md").is_file()


def test_a_value_keeps_each_equals_sign_after_the_first(tmp_path):
    template = tmp_path / "t.md"
    template.write_text("$q\n")
    program = fake_claude(tmp_path, stream=SUCCESS)
    code = main([
        "run", "--template", str(template), "--value", "q=a=b=c",
        "--workdir", str(tmp_path), "--run-dir", str(tmp_path / "out"),
        "--model", "m", "--executable", str(program),
    ])
    assert code == 0
    assert (tmp_path / "out" / "prompts" / "t.md").read_text() == "a=b=c\n"


def test_a_value_with_no_equals_sign_exits_1(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    code = main(argv(tmp_path, program, "--value", "plan"))
    assert code == 1
    assert "plan" in capsys.readouterr().err


def test_a_template_that_needs_a_value_nobody_gave_exits_1(tmp_path, capsys):
    template = tmp_path / "t.md"
    template.write_text("$missing\n")
    program = fake_claude(tmp_path, stream=SUCCESS)
    code = main([
        "run", "--template", str(template), "--workdir", str(tmp_path),
        "--run-dir", str(tmp_path / "out"), "--model", "m",
        "--executable", str(program),
    ])
    assert code == 1
    assert "missing" in capsys.readouterr().err


def test_a_bad_placeholder_in_a_path_exits_1(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    code = main(argv(tmp_path, program, "--run-dir", "runs/{stepp}"))
    assert code == 1
    assert "stepp" in capsys.readouterr().err


def test_the_console_shows_each_tool_call_of_the_agent(tmp_path, capsys):
    tool = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/a/plan.md"}}]}})
    program = fake_claude(tmp_path, stream=tool + "\n" + SUCCESS)
    main(argv(tmp_path, program))
    assert "Read(plan.md)" in capsys.readouterr().out
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'renfield.cli'`

- [ ] **Step 3: Write `src/renfield/cli.py`**

```python
"""The `renfield run` command."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from renfield.config import ConfigError, Skill, load
from renfield.paths import PathError, make_dirs, render as render_paths
from renfield.provider import ProviderError
from renfield.record import summary_line
from renfield.step import PromptError, render_prompt, run_step

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_STEP = 4
EXIT_OUTPUT = 5
EXIT_INTERRUPT = 130

# A failure of the output is the caller's prompt, and not the provider. It
# gets its own code, because a caller must not retry it.
OUTPUT_CLASS = "invalid_output"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="renfield", description="Run 1 AI agent, and report what it did"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run 1 agent step")

    run.add_argument("--template", type=Path, required=True, help="the prompt template")
    run.add_argument("--value", action="append", default=[], metavar="KEY=VALUE",
                     help="1 placeholder value. Repeatable.")
    run.add_argument("--values", type=Path, help="a JSON file of placeholder values")
    run.add_argument("--output", action="append", default=[], metavar="NAME",
                     help="a file the agent must write. Repeatable.")
    run.add_argument("--schema", action="append", default=[], metavar="NAME=PATH",
                     help="a JSON schema for an output. Repeatable.")
    run.add_argument("--workdir", type=Path, default=Path("."),
                     help="the working directory of the child")
    run.add_argument("--config", type=Path, help="the TOML file")
    run.add_argument("--config-dir", type=Path,
                     help="a CLAUDE_CONFIG_DIR for the child")
    run.add_argument("--name", help="the step name. Default: the stem of the template.")
    run.add_argument("--executable", default="claude", help="the agent program")
    run.add_argument("--add-dir", action="append", default=[], type=Path)
    run.add_argument("--skill", action="append", default=[], metavar="PLUGIN[=INVOKE]")
    for key in ("run-dir", "prompt", "transcript", "artifacts", "record"):
        run.add_argument(f"--{key}", help=f"override the {key.replace('-', '_')} path")
    run.add_argument("--provider", dest="kind")
    run.add_argument("--api-key-env")
    run.add_argument("--model")
    run.add_argument("--effort")
    run.add_argument("--timeout-min", type=int)
    run.add_argument("--max-usd", type=float)
    run.add_argument("--retries", type=int)
    run.add_argument("--render-only", action="store_true",
                     help="write the prompt and stop. 0 USD.")
    run.set_defaults(handler=_run)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (ConfigError, PathError, PromptError, ProviderError) as error:
        print(f"renfield: {error}", file=sys.stderr)
        return EXIT_CONFIG
    except KeyboardInterrupt:
        print("\nCtrl-C: the step stopped.", file=sys.stderr)
        return EXIT_INTERRUPT


def _run(args) -> int:
    default_config = Path("renfield.toml")
    config_path = args.config
    if config_path is None and default_config.is_file():
        config_path = default_config

    overrides = {
        "name": args.name or args.template.stem,
        "kind": args.kind,
        "api_key_env": args.api_key_env,
        "model": args.model,
        "effort": args.effort,
        "timeout_min": args.timeout_min,
        "max_usd": args.max_usd,
        "retries": args.retries,
        "run_dir": args.run_dir,
        "prompt": args.prompt,
        "transcript": args.transcript,
        "artifacts": args.artifacts,
        "record": args.record,
        "add_dirs": args.add_dir or None,
        "skills": _skills(args.skill) or None,
    }
    settings = load(config_path, overrides=overrides, env=os.environ)
    values = _values(args.values, args.value)
    schemas = _schemas(args.schema)

    if args.render_only:
        run = render_paths(settings.paths, step=settings.step.name)
        make_dirs(run)
        text = render_prompt(
            args.template.read_text(), values, settings.step.skills
        )
        run.prompt.write_text(text)
        print(f"prompt: {run.prompt}")
        return EXIT_OK

    limit = (
        f"limit {settings.step.max_usd} USD"
        if settings.step.max_usd is not None
        else "no cost limit"
    )
    print(
        f"{settings.step.name}: {settings.step.model}, "
        f"effort {settings.step.effort}, {limit}"
    )
    record = run_step(
        settings.step,
        settings.provider,
        workdir=args.workdir,
        template=args.template,
        values=values,
        paths=settings.paths,
        outputs=args.output,
        schemas=schemas,
        executable=args.executable,
        config_dir=args.config_dir,
        on_line=lambda line: print(f"  {line}"),
    )
    print(summary_line(record))
    if record.error:
        print(f"renfield: {record.error}", file=sys.stderr)
    print(f"record: {Path(record.run_dir) / 'record.json'}")

    if record.status == "ok":
        return EXIT_OK
    return EXIT_OUTPUT if record.error_class == OUTPUT_CLASS else EXIT_STEP


def _values(path: Path | None, pairs: Sequence[str]) -> dict[str, str]:
    """Read the values of the file, then the values of the flags."""
    values: dict[str, str] = {}
    if path is not None:
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict):
            raise ConfigError(f"{path} must hold a JSON object")
        values.update({str(key): str(value) for key, value in data.items()})
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ConfigError(
                f"--value {pair!r} has no '=' sign. Write --value key=value."
            )
        values[key] = value
    return values


def _schemas(pairs: Sequence[str]) -> dict[str, Path]:
    schemas: dict[str, Path] = {}
    for pair in pairs:
        name, sep, path = pair.partition("=")
        if not sep or not name or not path:
            raise ConfigError(
                f"--schema {pair!r} is not NAME=PATH. "
                f"Write --schema verdict.json=schemas/verdict.schema.json."
            )
        schemas[name] = Path(path)
    return schemas


def _skills(pairs: Sequence[str]) -> list[Skill]:
    skills = []
    for pair in pairs:
        plugin, _, invoke = pair.partition("=")
        skills.append(Skill(plugin=Path(plugin), invoke=invoke or None))
    return skills


if __name__ == "__main__":
    raise SystemExit(main())
```

**`record.json` is named in 2 places, and that is 1 too many.** `_run` prints `Path(record.run_dir) / "record.json"`, and the path is configurable. Give `StepRecord` a `record` field, set it in `run_step` beside `prompt` and `transcript`, and print `Path(record.run_dir) / record.record`. Add a test that a `--record r.json` override changes the last line.

- [ ] **Step 4: Write `src/renfield/__init__.py`**

```python
"""Renfield runs 1 AI agent as a child process, and reports what it did."""

from renfield.config import ConfigError, Settings, Skill, Step, load
from renfield.outputs import check_outputs
from renfield.paths import PathError, Paths, RunPaths
from renfield.provider import Provider, ProviderError, build_env
from renfield.record import StepRecord, summary_line, write_record
from renfield.step import PromptError, render_prompt, run_step
from renfield.stream import StepResult, read_stream
from renfield.version import __version__

__all__ = [
    "ConfigError",
    "PathError",
    "PromptError",
    "Paths",
    "Provider",
    "ProviderError",
    "RunPaths",
    "Settings",
    "Skill",
    "Step",
    "StepRecord",
    "StepResult",
    "__version__",
    "build_env",
    "check_outputs",
    "load",
    "read_stream",
    "render_prompt",
    "run_step",
    "summary_line",
    "write_record",
]
```

- [ ] **Step 5: Run each test and watch them pass**

Run: `uv run pytest -v`
Expected: each test of each module passes.

- [ ] **Step 6: Write `README.md`**

````markdown
# Renfield

Renfield runs 1 AI agent as a child process, against a prompt template, and
reports what the agent did and what it wrote.

It is the servant, and never the master. You decide what the agent must do.
Renfield starts it, watches it, kills it when it runs too long, checks what it
wrote, and gives you 1 record.

The design is in [`docs/design.md`](docs/design.md).

## Warning

**Renfield starts an agent with the permission checks off.** The agent can run
shell commands with your rights. The working directory is the material of the
task, and a file of that directory can hold text that is written for an agent
to read.

Use Renfield only on material that you trust.

## Requirements

| Program | Version | Why |
|---|---|---|
| Python | 3.11 or later | Renfield itself |
| [Claude Code](https://claude.com/claude-code) | measured with 2.1.285 | the agent is 1 `claude -p` child process |

You need 1 provider: a Claude subscription, an Anthropic API key, or an
OpenRouter key.

## Install

```sh
uv add git+https://github.com/<you>/renfield
```

## Use it from the command line

```sh
renfield run \
  --template prompts/review.md \
  --value plan=docs/plan.md \
  --output verdict.json \
  --schema verdict.json=schemas/verdict.schema.json \
  --workdir . \
  --model claude-opus-5
```

A value is text, and Renfield reads no file for it. `--value plan=docs/plan.md`
puts those 12 characters into the prompt, and the agent reads the file with its
own tools.

**Read the prompt before you pay for it:**

```sh
renfield run --template prompts/review.md --value plan=docs/plan.md --render-only
```

## Use it from Python

```python
from pathlib import Path
from renfield import Paths, Provider, Step, run_step

record = run_step(
    Step(name="review", model="claude-opus-5", effort="high", timeout_min=20),
    Provider(kind="subscription"),
    workdir=Path("."),
    template=Path("prompts/review.md"),
    values={"plan": "docs/plan.md"},
    paths=Paths(),
    outputs=["verdict.json"],
    schemas={"verdict.json": Path("schemas/verdict.schema.json")},
)
print(record.status, record.cost_usd, record.outputs_valid)
```

## Configuration

```toml
# renfield.toml
[provider]
kind        = "openrouter"
api_key_env = "OPENROUTER_API_KEY"
model       = "deepseek/deepseek-v4.1-flash"
effort      = "high"

[step]
timeout_min = 20
max_usd     = 6.0
retries     = 2

[paths]
run_dir    = "runs/{stamp}-{step}"
prompt     = "prompts/{step}.md"
transcript = "transcripts/{step}.jsonl"
artifacts  = "artifacts"
record      = "record.json"
```

The precedence is: built-in defaults, then this file, then the CLI flag.
**Do not commit `renfield.toml`.** It can hold a key.

## What 1 run writes

```
runs/2026-10-12T14-03-51-review/
  prompts/review.md          the prompt, as sent
  transcripts/review.jsonl   every event of the agent
  artifacts/verdict.json     what the agent wrote
  record.json                status, cost, tokens, tool calls
```

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | The step finished, and each output passed its schema |
| 1 | Config error, or a value outside its range |
| 4 | The step failed: auth, rate limit, budget, transient, or timeout |
| 5 | The step finished, and an output is missing or fails its schema |
| 130 | Ctrl-C |

**Exit 4 and exit 5 are not the same.** Retry a 4. Never retry a 5: it says the
prompt is wrong, and the next call writes the same bad file.

## The cost is an estimate, except with an API key

Claude Code prices every call at Anthropic rates, whatever vendor served it. A
measured call on `meta-llama/llama-3.1-8b-instruct` reported 0.3141 USD, and
OpenRouter charges about 0.002 USD for it.

`record.json` carries `cost_estimated`. **With `openrouter`, `max_usd` is a turn
governor and not a spend limit.** Set it high, and set it on purpose.

## Development

```sh
uv run pytest        # no network, no money
```

Each test runs against `renfield.testing.fake_claude`, a fake agent program.
Your own project can use it to test your prompts for 0 USD.
````

- [ ] **Step 7: Commit**

```bash
git add src/renfield/cli.py src/renfield/__init__.py tests/test_cli.py README.md
git commit -m "feat: the renfield run command, the public names, and the README"
```

---

## Self-review of this plan

I checked this plan against `docs/design.md` after I wrote it. The 5 defects
below were in the plan, and each one is fixed above. They are listed because a
reviewer who finds the fix must not read it as an accident.

| # | Defect | Fix |
|---|---|---|
| 1 | `outputs.py` skipped the JSON parse when no schema was given, and a test of a truncated `.json` file could never pass. | The parse keys on the `.json` suffix. A schema is the second check. |
| 2 | `config.py` read the step name from the `[step]` table, and `_read` rejects an unknown key, so the name could never arrive that way. | The name comes from the call, and the file cannot set it. |
| 3 | A test was named "a server failure is transient **and a client failure is not**" and covered only server failures. | 2 tests, and a 400 is now covered with its open item. |
| 4 | 2 brittle test counts, and the "the code wins" rule lived in 1 task. | The rule is a global constraint, and the counts are advisory. |
| 5 | `record.py` imported `__version__` from the package root, and task 9 makes the root import `step.py`, which imports `record.py`. An import cycle. | `version.py` is its own module. |
| 6 | The README step used a 3-backtick fence and holds `sh` and `toml` blocks. The first inner fence closed the outer one. | A 4-backtick outer fence. |
| 7 | A step with no `max_usd` printed `limit None USD` on the first console line. | The line says "no cost limit". |
| 8 | Task 2's auth test ran `json.loads` on every non-blank line of `auth-401.jsonl`, and line 1 of that fixture is a plain-text warning of the child. The test could not run. Found by the task 2 implementer. | The list comprehension keeps only the lines that start with `{`. `raw` still carries the warning line into `read_stream`. |
| 9 | `paths.py` let a bare `ValueError` out of `Formatter().parse` for an unbalanced brace, and task 9's CLI catches `PathError` only. `renfield run --run-dir "runs/{step"` would have printed a traceback. Found by the task 4 implementer, measured by the controller. | `_check` wraps the comprehension and raises `PathError` naming the key and the reason. 3 forms get a test. |
| 10 | The defect 9 fix guarded `Formatter().parse` and left `.format` open to the same leak. `"runs/{step!x}"` and `"runs/{step:d}"` both raise a bare `ValueError`. Found by the task 4 reviewer, measured by the controller. | `render` wraps the `.format` call too, and 2 more forms get a test. |
| 11 | `_in_range` ended with `return kind(value)`, so `timeout_min = 30.9` passed the range check and became 30, with no message. The module exists to stop exactly that. Found by the task 5 reviewer, measured by the controller. | A whole-number check for the `int` keys. `30.0` still passes. |
| 12 | Task 5's range test asserted `str(value) in message`, which the `240` of the range satisfies for `timeout_min = 0`. 3 of its 6 cases passed whatever the code printed. Found by the task 5 reviewer, measured by the controller. | The assertion is the exact phrase `f"the value is {value}"`. |
| 13 | Task 5 had no test that an in-range boundary is accepted, so changing `<=` to `<` would have left the suite green. It also had no test for an out-of-range override, a non-number value, or an unknown `kind`. Found by the task 5 reviewer. | 5 added tests: both ends of all 3 ranges, an override, a bool and a string, an unknown kind, and both fraction cases. |

**Spec coverage.** Each section of `docs/design.md` has a task: section 3 is
tasks 3 and 8, section 4 is tasks 5, 7 and 8, section 5 is tasks 4 and 5,
sections 6 and 7 are tasks 6 and 8, section 8 is tasks 2, 8 and 9, section 9 is
task 7, section 10 is task 9, section 11 is task 1, and section 13 is the file
structure table.

**Not covered, and deliberately so.** Section 12 of the spec is a caution for a
reader, and it needs code in no task. Section 15 holds the open items, and an
open item is not work.

**1 thing this plan adds that the spec does not hold.** `StepRecord` gains
`child_exit_code`. Without it, no test can tell a SIGINT death from a SIGKILL
death, and the escalation of section 8.3 then has no test that can fail.

---

## Preflight rulings

The controller scanned this plan before task 1, and ruled on what the scan
found. Each ruling is already applied above.

| Ruling | Decision | Cost if wrong |
|---|---|---|
| R1 | `cli.py` passes `env=os.environ` to `load`. Without it `env` defaults to `{}`, and an `api_key_env` can never resolve. | The `openrouter` and `anthropic-api` kinds fail from the CLI with "that variable is empty or absent", and only `subscription` works. |
| R2 | `environment()` and `_version_of` leave task 7. Nothing consumes them, and `docs/design.md`, section 4.4, has no version field. | A caller who wants the version of the agent program runs `claude --version` itself, which is 1 line. |
| R3 | The work happens on the branch `renfield-build` of this repository, and not in a git worktree. | A plan that must be abandoned costs 1 `git branch -D`. Nothing else is in flight in this repository. |
