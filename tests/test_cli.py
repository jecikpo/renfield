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


def test_a_record_override_changes_the_last_line(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    code = main(argv(tmp_path, program, "--record", "r.json"))
    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-1] == f"record: {tmp_path / 'out' / 'r.json'}"
    assert (tmp_path / "out" / "r.json").is_file()
    assert not (tmp_path / "out" / "record.json").exists()


def test_ctrl_c_exits_130_and_says_so_on_stderr(tmp_path, capsys, monkeypatch):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("renfield.cli.run_step", interrupted)
    program = fake_claude(tmp_path, stream=SUCCESS)
    code = main(argv(tmp_path, program))
    assert code == 130
    assert "Ctrl-C" in capsys.readouterr().err


RATE_LIMIT = json.dumps(
    {"type": "result", "subtype": "success", "is_error": True,
     "api_error_status": 429, "total_cost_usd": 0.1, "result": "slow down"}
) + "\n"

SERVER = json.dumps(
    {"type": "result", "subtype": "error", "is_error": True,
     "api_error_status": 503, "total_cost_usd": 0.2, "result": "upstream"}
) + "\n"

BUDGET = json.dumps(
    {"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
     "total_cost_usd": 4.0, "result": "the budget is spent"}
) + "\n"


@pytest.mark.parametrize(
    "stream,expected_class",
    [
        (AUTH, "auth"),
        (RATE_LIMIT, "rate_limited"),
        (SERVER, "transient"),
        (BUDGET, "budget"),
    ],
)
def test_every_failure_class_exits_4_and_never_5(tmp_path, stream, expected_class):
    """Exit 4 and exit 5 are this CLI's core contract: a caller retries a 4
    and must never retry a 5. The first test covered the auth class only, so
    a mutant that returned 5 for a rate limit or a server failure would have
    passed. --retries 0 keeps the transient case from sleeping 150 s."""
    program = fake_claude(tmp_path, stream=stream)
    code = main(argv(tmp_path, program, "--retries", "0"))
    assert code == 4
    data = json.loads((tmp_path / "out" / "record.json").read_text())
    assert data["error_class"] == expected_class


def test_the_cli_resolves_an_api_key_from_the_environment(tmp_path, monkeypatch):
    """Preflight ruling R1: without env=os.environ in the load() call, load
    sees an empty environment and an api_key_env can never resolve, so only
    the subscription kind works from the CLI. Deleting that argument breaks
    no other test in the suite. This also covers the file-to-flag precedence
    and the openrouter environment of the child."""
    config = tmp_path / "renfield.toml"
    config.write_text(
        '[provider]\n'
        'kind = "openrouter"\n'
        'api_key_env = "OR_KEY"\n'
        'model = "from-the-file"\n'
        'effort = "medium"\n'
    )
    monkeypatch.setenv("OR_KEY", "the-key-of-the-environment")
    program = fake_claude(tmp_path, stream=SUCCESS)

    template = tmp_path / "t.md"
    template.write_text("read $plan\n")
    code = main([
        "run",
        "--template", str(template),
        "--value", "plan=docs/plan.md",
        "--config", str(config),
        "--workdir", str(tmp_path),
        "--run-dir", str(tmp_path / "out"),
        "--executable", str(program),
        "--model", "from-the-flag",
    ])

    assert code == 0
    call = call_record(tmp_path)
    assert call["env"]["ANTHROPIC_AUTH_TOKEN"] == "the-key-of-the-environment"
    assert call["env"]["ANTHROPIC_API_KEY"] == ""
    argv = call["argv"]
    assert argv[argv.index("--model") + 1] == "from-the-flag", "a flag beats the file"
    assert argv[argv.index("--effort") + 1] == "medium", "the file keeps its own key"
