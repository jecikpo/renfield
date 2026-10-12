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


def config_of(tmp_path, text='[models.m]\nmodel = "m"\n', name="cli.toml"):
    """Write the config file of a test. The default name is cli.toml, and not
    renfield.toml: a test that writes its own renfield.toml must not lose it.
    A test that passes its own --config to argv() uses another name, because
    argv() writes cli.toml after the arguments of the call are built."""
    path = tmp_path / name
    path.write_text(text)
    return path


def argv(tmp_path, program, *extra):
    template = tmp_path / "t.md"
    template.write_text("read $plan\n")
    return [
        "run",
        "--template", str(template),
        "--value", "plan=docs/plan.md",
        "--workdir", str(tmp_path),
        "--run-dir", str(tmp_path / "out"),
        "--config", str(config_of(tmp_path)),
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
        "--config", str(config_of(tmp_path)),
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
        "--run-dir", str(tmp_path / "out"),
        "--config", str(config_of(tmp_path)),
        "--model", "m",
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


def test_the_model_flag_selects_1_entry_and_its_key_reaches_the_child(
    tmp_path, monkeypatch
):
    """Preflight ruling R1: without env=os.environ in the load() call, load
    sees an empty environment and an api_key_env can never resolve, so only
    the subscription kind works from the CLI. This also covers the selection
    of an entry that is not the default, and the openrouter environment of
    the child."""
    config = config_of(
        tmp_path,
        'default = "opus"\n\n'
        '[models.opus]\nmodel = "claude-opus-5-5"\neffort = "xhigh"\n\n'
        '[models.flash]\nkind = "openrouter"\napi_key_env = "OR_KEY"\n'
        'model = "deepseek/deepseek-v4.1-flash"\neffort = "medium"\n',
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
        "--model", "flash",
    ])

    assert code == 0
    call = call_record(tmp_path)
    assert call["env"]["ANTHROPIC_AUTH_TOKEN"] == "the-key-of-the-environment"
    assert call["env"]["ANTHROPIC_API_KEY"] == ""
    argv = call["argv"]
    assert argv[argv.index("--model") + 1] == "deepseek/deepseek-v4.1-flash"
    assert argv[argv.index("--effort") + 1] == "medium", "the entry keeps its own key"


def test_a_missing_program_exits_1_with_a_message_and_no_traceback(tmp_path, capsys):
    code = main(argv(tmp_path, tmp_path / "claude-does-not-exist", "--max-usd", "6"))
    assert code == 1
    error = capsys.readouterr().err
    assert "claude-does-not-exist" in error
    assert "Traceback" not in error
    assert not (tmp_path / "out" / "record.json").exists()


# --- the CLI tells a person what is wrong ---

def test_a_missing_template_exits_1_with_a_message(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    args = argv(tmp_path, program)
    args[args.index("--template") + 1] = str(tmp_path / "no-such.md")
    assert main(args) == 1
    error = capsys.readouterr().err
    assert "no-such.md" in error
    assert "Traceback" not in error


def test_a_missing_template_with_render_only_exits_1(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    args = argv(tmp_path, program, "--render-only")
    args[args.index("--template") + 1] = str(tmp_path / "no-such.md")
    assert main(args) == 1
    assert "no-such.md" in capsys.readouterr().err


def test_a_missing_values_file_exits_1(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    code = main(argv(tmp_path, program, "--values", str(tmp_path / "no-values.json")))
    assert code == 1
    assert "no-values.json" in capsys.readouterr().err


def test_a_malformed_values_file_exits_1(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    bad = tmp_path / "values.json"
    bad.write_text("{not json")
    assert main(argv(tmp_path, program, "--values", str(bad))) == 1
    assert "renfield:" in capsys.readouterr().err


def test_a_config_file_that_is_not_utf8_exits_1(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    bad = tmp_path / "renfield.toml"
    bad.write_bytes(b"[models.m]\nmodel = \"caf\xe9\"\n")
    assert main(argv(tmp_path, program, "--config", str(bad))) == 1
    assert "Traceback" not in capsys.readouterr().err


# --- --add-dir ---

def test_an_add_dir_that_is_a_directory_reaches_the_child(tmp_path):
    material = tmp_path / "material"
    material.mkdir()
    program = fake_claude(tmp_path, stream=SUCCESS)
    assert main(argv(tmp_path, program, "--add-dir", str(material))) == 0
    command = call_record(tmp_path)["argv"]
    assert command[command.index(str(material)) - 1] == "--add-dir"


def test_an_add_dir_that_does_not_exist_exits_1_and_names_the_path(tmp_path, capsys):
    """Before this check the folder was dropped with no message, and the
    caller paid for a full run that could not read the material."""
    program = fake_claude(tmp_path, stream=SUCCESS)
    code = main(argv(tmp_path, program, "--add-dir", "/no/such/dir"))
    assert code == 1
    assert "/no/such/dir" in capsys.readouterr().err
    with pytest.raises(FileNotFoundError):
        call_record(tmp_path)


def test_the_default_config_file_is_read_when_no_config_is_given(
    tmp_path, monkeypatch
):
    """Deleting the default_config branch of cli._run passed every other
    test: the config file of each user of the default went unread."""
    (tmp_path / "renfield.toml").write_text(
        '[models.m]\nmodel = "from-the-default-file"\n'
    )
    template = tmp_path / "t.md"
    template.write_text("read $plan\n")
    program = fake_claude(tmp_path, stream=SUCCESS)
    monkeypatch.chdir(tmp_path)
    code = main([
        "run", "--template", str(template), "--value", "plan=x",
        "--workdir", str(tmp_path), "--run-dir", str(tmp_path / "out"),
        "--executable", str(program),
    ])
    assert code == 0
    command = call_record(tmp_path)["argv"]
    assert command[command.index("--model") + 1] == "from-the-default-file"


# --- named models ---

TWO_MODELS = (
    'default = "opus"\n\n'
    '[models.opus]\nmodel = "claude-opus-5-5"\n\n'
    '[models.flash]\nmodel = "deepseek/deepseek-v4.1-flash"\neffort = "medium"\n'
)


@pytest.mark.parametrize("flag", ["--provider", "--api-key-env"])
def test_a_removed_provider_flag_exits_2(tmp_path, flag):
    program = fake_claude(tmp_path, stream=SUCCESS)
    with pytest.raises(SystemExit) as caught:
        main(argv(tmp_path, program, flag, "x"))
    assert caught.value.code == 2


def test_the_first_line_names_the_entry_and_the_model(tmp_path, capsys):
    program = fake_claude(tmp_path, stream=SUCCESS)
    args = argv(
        tmp_path, program,
        "--config", str(config_of(tmp_path, TWO_MODELS, name="two.toml")),
    )
    args[args.index("--model") + 1] = "flash"
    assert main(args) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first == (
        "t: flash (deepseek/deepseek-v4.1-flash), effort medium, no cost limit"
    )


def test_render_only_needs_no_key_in_the_environment(tmp_path, monkeypatch, capsys):
    """A render costs 0 USD. The plugin renders before each paid run, so a
    render that needs the key blocks the check of the template."""
    monkeypatch.delenv("RENFIELD_TEST_ABSENT", raising=False)
    config = config_of(
        tmp_path,
        '[models.m]\nmodel = "m"\nkind = "openrouter"\n'
        'api_key_env = "RENFIELD_TEST_ABSENT"\n',
        name="paid.toml",
    )
    program = fake_claude(tmp_path, stream=SUCCESS)
    args = argv(tmp_path, program, "--config", str(config), "--render-only")
    assert main(args) == 0
    assert (tmp_path / "out" / "prompts" / "t.md").read_text() == "read docs/plan.md\n"


def test_a_paid_run_needs_the_key_in_the_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("RENFIELD_TEST_ABSENT", raising=False)
    config = config_of(
        tmp_path,
        '[models.m]\nmodel = "m"\nkind = "openrouter"\n'
        'api_key_env = "RENFIELD_TEST_ABSENT"\n',
        name="paid.toml",
    )
    program = fake_claude(tmp_path, stream=SUCCESS)
    assert main(argv(tmp_path, program, "--config", str(config))) == 1
    assert "RENFIELD_TEST_ABSENT" in capsys.readouterr().err
