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
        errors="replace",
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
        try:
            process.stdin.write(prompt)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            # The child exited before it read the prompt. Its own output, or
            # the absence of a result event, carries the reason. Measured: a
            # 500000-character prompt fills the pipe buffer and the write
            # then raises.
            pass
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
    if process.poll() is not None:
        # The child finished on its own, between the end of its stream and
        # the cancel of this timer. That is not a timeout, and a call that
        # succeeded must not be relabelled as one.
        return
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
