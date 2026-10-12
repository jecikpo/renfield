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
    text = f'[provider]\nmodel = "m"\n\n[step]\n{key} = {value}\n'
    settings = load(write(tmp_path, text), env={})
    assert getattr(settings.step, key) == value


def test_an_override_outside_the_range_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="timeout_min"):
        load(
            write(tmp_path, '[provider]\nmodel = "m"\n'),
            overrides={"timeout_min": 0},
            env={},
        )


@pytest.mark.parametrize("value", ["true", '"30"'])
def test_a_value_that_is_not_a_number_names_the_range(tmp_path, value):
    """A bool is an int in Python, so the bool guard must come first."""
    text = f'[provider]\nmodel = "m"\n\n[step]\ntimeout_min = {value}\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    message = str(caught.value)
    assert "timeout_min" in message
    assert "not a number" in message
    assert " to " in message


def test_an_unknown_kind_names_the_list(tmp_path):
    text = '[provider]\nmodel = "m"\nkind = "moonshot"\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    message = str(caught.value)
    assert "moonshot" in message
    assert "openrouter" in message


@pytest.mark.parametrize("key,value", [("timeout_min", 30.9), ("retries", 1.5)])
def test_a_fraction_for_a_whole_number_key_is_an_error(tmp_path, key, value):
    """Measured: int(30.9) is 30, so the person's value would be replaced
    with no message."""
    text = f'[provider]\nmodel = "m"\n\n[step]\n{key} = {value}\n'
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, text), env={})
    message = str(caught.value)
    assert key in message
    assert str(value) in message


@pytest.mark.parametrize("key,value", [("timeout_min", 30.0), ("retries", 2.0)])
def test_a_float_that_is_a_whole_number_is_accepted(tmp_path, key, value):
    text = f'[provider]\nmodel = "m"\n\n[step]\n{key} = {value}\n'
    settings = load(write(tmp_path, text), env={})
    assert getattr(settings.step, key) == int(value)
