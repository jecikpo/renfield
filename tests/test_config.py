import pytest

from pathlib import Path

from renfield.config import ConfigError, Settings, Skill, Step, load

FULL = """
default = "flash"

[step]
timeout_min = 30
max_usd     = 4.0
retries     = 1

[models.flash]
kind        = "openrouter"
api_key_env = "OR_KEY"
model       = "deepseek/deepseek-v4.1-flash"
effort      = "medium"

[models.opus]
model       = "claude-opus-5-5"
effort      = "xhigh"
timeout_min = 40
max_usd     = 6.0

[paths]
run_dir = "out/{step}"
record  = "r.json"
"""

ONE = '[models.m]\nmodel = "m"\n'


def write(tmp_path, text):
    path = tmp_path / "renfield.toml"
    path.write_text(text)
    return path


def test_a_file_with_no_step_table_gives_the_documented_defaults(tmp_path):
    settings = load(write(tmp_path, '[models.m]\nmodel = "m"\n'), env={})
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


def test_an_override_wins_over_the_entry_and_changes_1_key_only(tmp_path):
    settings = load(
        write(tmp_path, FULL),
        overrides={"timeout_min": 50, "effort": None},
        env={"OR_KEY": "k"},
    )
    assert settings.step.timeout_min == 50
    # effort was None, so the entry value stands.
    assert settings.step.effort == "medium"


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
    text = f'[models.m]\nmodel = "m"\n\n[step]\n{key} = {value}\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    message = str(caught.value)
    assert key in message
    assert f"the value is {value}" in message
    assert " to " in message, "the message must name the range"


@pytest.mark.parametrize("value", ["low", "medium", "high", "xhigh", "max"])
def test_each_documented_effort_is_accepted(tmp_path, value):
    text = f'[models.m]\nmodel = "m"\neffort = "{value}"\n'
    assert load(write(tmp_path, text), env={}).step.effort == value


def test_an_effort_that_is_not_in_the_list_names_the_list(tmp_path):
    text = '[models.m]\nmodel = "m"\neffort = "ultra"\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    assert "ultra" in str(caught.value)
    assert "xhigh" in str(caught.value)


def test_an_unknown_key_of_the_file_is_an_error_and_not_a_silent_default(tmp_path):
    text = '[models.m]\nmodel = "m"\n\n[step]\ntimout_min = 60\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    assert "timout_min" in str(caught.value)


def test_an_unknown_table_of_the_file_is_an_error(tmp_path):
    text = '[models.m]\nmodel = "m"\n\n[steps]\ntimeout_min = 60\n'
    with pytest.raises(ConfigError, match="steps"):
        load(write(tmp_path, text), env={})


def test_a_key_and_a_key_variable_together_is_an_error(tmp_path):
    text = (
        '[models.m]\nmodel = "m"\nkind = "openrouter"\n'
        'api_key = "literal"\napi_key_env = "OR_KEY"\n'
    )
    with pytest.raises(ConfigError, match="api_key"):
        load(write(tmp_path, text), env={"OR_KEY": "k"})


def test_a_key_variable_that_the_environment_does_not_hold_names_it(tmp_path):
    text = '[models.m]\nmodel = "m"\nkind = "openrouter"\napi_key_env = "OR_KEY"\n'
    with pytest.raises(ConfigError, match="OR_KEY"):
        load(write(tmp_path, text), env={})


def test_a_kind_that_needs_a_key_and_has_no_source_stops_at_the_config(tmp_path):
    text = '[models.m]\nmodel = "m"\nkind = "anthropic-api"\n'
    with pytest.raises(ConfigError, match="anthropic-api"):
        load(write(tmp_path, text), env={})


def test_a_subscription_needs_no_key(tmp_path):
    settings = load(write(tmp_path, '[models.m]\nmodel = "m"\n'), env={})
    assert settings.provider.api_key is None


def test_a_file_that_is_not_there_is_an_error_that_names_the_path(tmp_path):
    with pytest.raises(ConfigError, match="missing.toml"):
        load(tmp_path / "missing.toml", env={})


@pytest.mark.parametrize("name", ["review", "a", "review.deep", "a-b_c.1"])
def test_a_good_step_name_is_accepted(tmp_path, name):
    assert load(write(tmp_path, ONE), overrides={"name": name}, env={}).step.name == name


@pytest.mark.parametrize("name", ["Review", "a b", "x" * 65, "", "a/b"])
def test_a_bad_step_name_is_an_error(tmp_path, name):
    with pytest.raises(ConfigError, match="name"):
        load(write(tmp_path, ONE), overrides={"name": name}, env={})


@pytest.mark.parametrize(
    "key,value",
    [
        ("timeout_min", 1),
        ("timeout_min", 240),
        ("retries", 0),
        ("retries", 2),
        ("max_usd", 0.01),
        ("max_usd", 1000.0),
    ],
)
def test_each_end_of_each_range_is_accepted(tmp_path, key, value):
    """A change of <= to < on either end is the range rule's own failure
    mode, and nothing else in this file would catch it."""
    text = f'[models.m]\nmodel = "m"\n\n[step]\n{key} = {value}\n'
    settings = load(write(tmp_path, text), env={})
    assert getattr(settings.step, key) == value


def test_an_override_outside_the_range_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="timeout_min"):
        load(
            write(tmp_path, '[models.m]\nmodel = "m"\n'),
            overrides={"timeout_min": 0},
            env={},
        )


@pytest.mark.parametrize("value", ["true", '"30"'])
def test_a_value_that_is_not_a_number_names_the_range(tmp_path, value):
    """A bool is an int in Python, so the bool guard must come first."""
    text = f'[models.m]\nmodel = "m"\n\n[step]\ntimeout_min = {value}\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    message = str(caught.value)
    assert "timeout_min" in message
    assert "not a number" in message
    assert " to " in message


def test_an_unknown_kind_names_the_list(tmp_path):
    text = '[models.m]\nmodel = "m"\nkind = "moonshot"\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    message = str(caught.value)
    assert "moonshot" in message
    assert "openrouter" in message


@pytest.mark.parametrize("key,value", [("timeout_min", 30.9), ("retries", 1.5)])
def test_a_fraction_for_a_whole_number_key_is_an_error(tmp_path, key, value):
    """Measured: int(30.9) is 30, so the person's value would be replaced
    with no message."""
    text = f'[models.m]\nmodel = "m"\n\n[step]\n{key} = {value}\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    message = str(caught.value)
    assert key in message
    assert str(value) in message


@pytest.mark.parametrize("key,value", [("timeout_min", 30.0), ("retries", 2.0)])
def test_a_float_that_is_a_whole_number_is_accepted(tmp_path, key, value):
    text = f'[models.m]\nmodel = "m"\n\n[step]\n{key} = {value}\n'
    settings = load(write(tmp_path, text), env={})
    assert getattr(settings.step, key) == int(value)


# --- a Step built by hand gets the same ranges as a Step read from a file ---

def by_hand(**changes):
    values = dict(name="review", model="m")
    values.update(changes)
    return Step(**values)


@pytest.mark.parametrize(
    "key, value",
    [
        ("name", "Bad Name"),
        ("name", ""),
        ("model", ""),
        ("effort", "turbo"),
        ("timeout_min", 0),
        ("timeout_min", 241),
        ("retries", 3),
        ("retries", -1),
        ("max_usd", 0.0),
        ("max_usd", 1001.0),
        ("add_dirs", ["not-a-path"]),
        ("skills", ["not-a-skill"]),
        ("model_entry", "Bad Name"),
        ("model_entry", "a.b"),
    ],
)
def test_a_step_built_by_hand_is_checked_and_names_the_key(key, value):
    """run_step is the second reader of a Step. Measured through the public
    names: Step(timeout_min=0) killed the child at once, with exit -2."""
    with pytest.raises(ConfigError, match=key):
        by_hand(**{key: value})


def test_a_good_step_built_by_hand_is_accepted():
    step = by_hand(max_usd=1.0, add_dirs=[Path("a")], skills=[Skill(plugin=Path("p"))])
    assert step.timeout_min == 20


def test_a_step_built_by_hand_has_no_model_entry_unless_given():
    assert by_hand().model_entry is None
    assert by_hand(model_entry="flash").model_entry == "flash"


# --- named models: docs/superpowers/specs/2026-10-12-named-models-design.md ---

TWO = (
    'default = "good"\n\n'
    '[models.good]\nmodel = "m"\n\n'
    '[models.bad]\nmodel = "m"\n'
)


def raised(tmp_path, text, **kwargs):
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env=kwargs.pop("env", {}), **kwargs)
    return str(caught.value)


# Rule 1
def test_the_old_provider_table_is_an_unknown_table(tmp_path):
    message = raised(tmp_path, '[provider]\nmodel = "m"\n')
    assert "provider" in message
    assert "[models.<name>]" in message


def test_models_that_is_not_a_table_is_an_error(tmp_path):
    message = raised(tmp_path, 'models = "x"\n')
    assert "[models]" in message
    assert "table" in message


def test_an_entry_that_is_not_a_table_is_an_error(tmp_path):
    message = raised(tmp_path, '[models]\nflash = "x"\n')
    assert "models.flash" in message
    assert "table" in message


# Rule 2
def test_a_dot_in_an_entry_name_is_named_as_the_cause(tmp_path):
    message = raised(tmp_path, '[models.a.b]\nmodel = "m"\n')
    assert "[models.a.b]: an entry name has no dot" in message


@pytest.mark.parametrize("name", ["A", "a b", "a.b", "x" * 65])
def test_a_bad_entry_name_names_the_rule(tmp_path, name):
    message = raised(tmp_path, f'[models."{name}"]\nmodel = "m"\n')
    assert repr(name) in message
    assert "a-z, 0-9, '-', and '_'" in message


@pytest.mark.parametrize("name", ["flash", "a-b_c1", "x" * 64])
def test_a_good_entry_name_is_accepted(tmp_path, name):
    settings = load(write(tmp_path, f'[models.{name}]\nmodel = "m"\n'), env={})
    assert settings.step.model_entry == name


# Rule 3
def test_an_unknown_key_of_an_entry_names_the_entry(tmp_path):
    message = raised(tmp_path, '[models.m]\nmodel = "m"\nmodle = "x"\n')
    assert "modle" in message
    assert "[models.m]" in message


def test_an_entry_with_no_model_is_an_error(tmp_path):
    message = raised(tmp_path, '[models.m]\neffort = "high"\n')
    assert "models.m.model" in message


def test_an_entry_accepts_the_3_step_keys(tmp_path):
    text = (
        '[models.m]\nmodel = "m"\ntimeout_min = 40\nmax_usd = 0.5\nretries = 0\n'
    )
    step = load(write(tmp_path, text), env={}).step
    assert (step.timeout_min, step.max_usd, step.retries) == (40, 0.5, 0)


# Rule 4
@pytest.mark.parametrize(
    "key, value",
    [
        ("timeout_min", "0"),
        ("retries", "3"),
        ("max_usd", "0.0"),
        ("effort", '"ultra"'),
        ("kind", '"moonshot"'),
    ],
)
def test_a_bad_value_in_an_entry_that_is_not_selected_names_that_entry(
    tmp_path, key, value
):
    message = raised(tmp_path, TWO + f"{key} = {value}\n")
    assert f"models.bad.{key}" in message


def test_a_bad_value_of_the_step_table_names_the_step_table(tmp_path):
    message = raised(tmp_path, ONE + "\n[step]\ntimeout_min = 0\n")
    assert "step.timeout_min" in message


# Rule 5
def test_an_entry_that_is_not_selected_needs_no_key_in_the_environment(tmp_path):
    text = TWO + 'kind = "openrouter"\napi_key_env = "ABSENT_KEY"\n'
    settings = load(write(tmp_path, text), env={})
    assert settings.step.model_entry == "good"
    assert settings.provider.api_key is None


def test_a_key_and_a_key_variable_in_any_entry_is_an_error(tmp_path):
    text = TWO + 'kind = "openrouter"\napi_key = "literal"\napi_key_env = "K"\n'
    message = raised(tmp_path, text, env={"K": "k"})
    assert "models.bad" in message
    assert "api_key" in message


def test_a_paid_kind_with_no_key_source_in_any_entry_is_an_error(tmp_path):
    message = raised(tmp_path, TWO + 'kind = "anthropic-api"\n')
    assert "models.bad" in message
    assert "anthropic-api" in message


def test_resolve_key_false_does_not_read_the_environment(tmp_path):
    text = '[models.m]\nmodel = "m"\nkind = "openrouter"\napi_key_env = "ABSENT_KEY"\n'
    settings = load(write(tmp_path, text), env={}, resolve_key=False)
    assert settings.provider.kind == "openrouter"
    assert settings.provider.api_key is None


def test_resolve_key_false_still_checks_the_file(tmp_path):
    text = '[models.m]\nmodel = "m"\nkind = "openrouter"\n'
    with pytest.raises(ConfigError, match="needs a key"):
        load(write(tmp_path, text), env={}, resolve_key=False)


# Rule 6
def test_a_default_that_is_not_a_string_is_an_error(tmp_path):
    message = raised(tmp_path, "default = 1\n\n" + ONE)
    assert "default" in message
    assert "not a string" in message


def test_a_default_that_names_no_entry_names_the_entries(tmp_path):
    message = raised(tmp_path, 'default = "nope"\n\n' + ONE)
    assert "'nope'" in message
    assert "m" in message.split("entries are")[1]


# Rule 7
def test_a_model_override_that_names_no_entry_names_the_entries(tmp_path):
    message = raised(tmp_path, FULL, overrides={"model": "nope"}, env={"OR_KEY": "k"})
    assert "'nope'" in message
    assert "flash, opus" in message


# Rule 8
def test_no_file_is_no_model():
    with pytest.raises(ConfigError) as caught:
        load(None, env={})
    assert str(caught.value) == "no model: add a [models.<name>] table to renfield.toml"


@pytest.mark.parametrize("text", ["[step]\nretries = 1\n", "[models]\n"])
def test_a_file_with_no_entry_is_no_model(tmp_path, text):
    message = raised(tmp_path, text)
    assert message == "no model: add a [models.<name>] table to renfield.toml"


# Rule 9
@pytest.mark.parametrize(
    "key, value",
    [("effort", "low"), ("timeout_min", 50), ("max_usd", 2.0), ("retries", 0)],
)
def test_each_override_wins_over_the_selected_entry(tmp_path, key, value):
    settings = load(
        write(tmp_path, FULL),
        overrides={"model": "opus", key: value},
        env={"OR_KEY": "k"},
    )
    assert getattr(settings.step, key) == value


# Rule 10
def test_2_entries_with_no_default_and_no_override_is_an_error(tmp_path):
    text = '[models.flash]\nmodel = "a"\n\n[models.opus]\nmodel = "b"\n'
    message = raised(tmp_path, text)
    assert "default" in message
    assert "--model" in message
    assert "flash, opus" in message


# The selection
def test_the_only_entry_is_the_default(tmp_path):
    step = load(write(tmp_path, ONE), env={}).step
    assert (step.model_entry, step.model) == ("m", "m")


def test_the_default_key_selects_the_entry(tmp_path):
    settings = load(write(tmp_path, FULL), env={"OR_KEY": "k"})
    assert settings.step.model_entry == "flash"
    assert settings.step.model == "deepseek/deepseek-v4.1-flash"
    assert settings.provider.kind == "openrouter"
    assert settings.provider.api_key == "k"


def test_the_model_override_wins_over_the_default(tmp_path):
    settings = load(write(tmp_path, FULL), overrides={"model": "opus"}, env={})
    assert settings.step.model_entry == "opus"
    assert settings.step.model == "claude-opus-5-5"
    assert settings.provider.kind == "subscription"


# The precedence, section 3
def test_the_step_table_wins_over_the_built_in_default(tmp_path):
    step = load(write(tmp_path, ONE + "\n[step]\ntimeout_min = 30\n"), env={}).step
    assert step.timeout_min == 30


def test_the_entry_wins_over_the_step_table(tmp_path):
    step = load(write(tmp_path, FULL), overrides={"model": "opus"}, env={}).step
    assert step.timeout_min == 40, "the entry sets it"
    assert step.max_usd == 6.0, "the entry sets it"
    assert step.retries == 1, "the entry does not set it, so [step] stands"


def test_a_provider_key_in_the_step_table_is_an_unknown_key(tmp_path):
    message = raised(tmp_path, ONE + '\n[step]\neffort = "medium"\n')
    assert "'effort'" in message
    assert "[step]" in message


@pytest.mark.parametrize("value", ["5", "0", "true", "[1]", "2026-10-12"])
def test_a_model_that_is_not_a_string_is_an_error(tmp_path, value):
    """str() made model = 5 the model ID '5', and a paid child started with
    it."""
    message = raised(tmp_path, f"[models.m]\nmodel = {value}\n")
    assert "models.m.model" in message
    assert "not a non-empty string" in message


@pytest.mark.parametrize("value", [["m"], 5])
def test_a_model_override_that_is_not_a_string_is_a_config_error(tmp_path, value):
    message = raised(tmp_path, ONE, overrides={"model": value})
    assert "model" in message
    assert "names no entry" in message
