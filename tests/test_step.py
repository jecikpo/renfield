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


# --- fix round 1 ---

def test_a_child_that_writes_invalid_utf8_keeps_the_events_before_it(tmp_path):
    """Measured: text=True alone raises UnicodeDecodeError while the stream is
    read, and the valid events before the bad bytes are lost with it.
    errors="replace" keeps them and read_stream ignores the bad line."""
    program = tmp_path / "bad-bytes"
    program.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdin.read()\n"
        f"sys.stdout.write({json.dumps(SUCCESS)})\n"
        "sys.stdout.flush()\n"
        "sys.stdout.buffer.write(b'\\xff\\xfe bad\\n')\n"
    )
    program.chmod(0o755)
    record = call(tmp_path, program)
    assert record.status == "ok"
    assert record.cost_usd == 1.25
    transcript = (tmp_path / "out" / "transcripts" / "review.jsonl").read_text()
    assert "�" in transcript, "the bad bytes reach the transcript as U+FFFD"


def test_a_child_that_exits_before_it_reads_the_prompt_gives_a_record(tmp_path):
    """Measured: a 500000-character prompt fills the pipe buffer, and the
    write then raises BrokenPipeError when the child has already exited.
    run_step is called after the agent may already have been paid for, so it
    must return a record rather than raise."""
    program = tmp_path / "quick-exit"
    program.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n")
    program.chmod(0o755)
    record = call(
        tmp_path, program, step=a_step(retries=0), values={"plan": "A" * 500000}
    )
    assert record.status == "failed"
    assert record.error_class == "transient"
    assert record.attempts == 1


def test_the_watchdog_does_not_call_a_finished_call_a_timeout():
    """The timer can fire between the end of the stream and the cancel. A
    child that already exited must not be relabelled as a timeout. This
    reaches a private function on purpose: the race cannot be driven from
    run_step without making the test depend on timing."""
    import subprocess
    import threading

    from renfield.step import _kill_group

    done = subprocess.Popen(["/usr/bin/true"], start_new_session=True)
    done.wait()
    flag = threading.Event()
    _kill_group(done, flag, 0.1)
    assert not flag.is_set()
