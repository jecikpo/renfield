# Named Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `renfield.toml` holds several named `[models.<name>]` entries, and `renfield run --model NAME` selects 1 of them.

**Architecture:** `config.load()` reads the file, checks each entry and the `[step]` table with messages that name the table, selects 1 entry (flag, then `default`, then the only entry), and builds `Provider`, `Step`, and `Paths` as before. `Step` and `StepRecord` get a field `model_entry`. The CLI loses `--provider` and `--api-key-env`, and `--model` names an entry.

**Tech Stack:** Python 3.11, `tomllib`, `argparse`, `pytest`, `uv`.

**Spec:** `docs/superpowers/specs/2026-10-12-named-models-design.md` (revision 2, commit `808c659`).

## Global Constraints

- Run the tests with `uv run pytest`. The suite has 205 tests before this plan. Each test uses `renfield.testing.fake_claude`. No test calls a real model.
- Test first (`AGENTS.md`, method 1): write the test, run it, watch it fail for the right reason, then write the code.
- Mutation check (`AGENTS.md`, method 5): for each new test, change the line that it protects, watch it fail, then restore the line. The plan names the mutation in each task.
- 1 change for each commit. Each commit leaves the full suite green.
- Each commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- An entry name matches `^[a-z0-9_-]{1,64}$`. A step name keeps `^[a-z0-9._-]{1,64}$`.
- The message for rule 8 is exactly: `no model: add a [models.<name>] table to renfield.toml`.
- A message for a key of an entry names `models.<name>.<key>`. A message for a key of `[step]` names `step.<key>`. A message for a flag or an override names the bare key.
- Do not change `provider.py`, `stream.py`, `paths.py`, `outputs.py`, or `testing.py`.
- Do not commit `runs/` or `renfield.toml`.
- Documents use ASD-STE100 (`AGENTS.md`, style).

## Review Focus

1. **A file whose `default` names an entry, plus `--model` that names another entry.** The flag wins, and the `default` still gets its check. Task 2, `test_the_model_override_wins_over_the_default` and `test_a_default_that_names_no_entry_names_the_entries`.
2. **An entry with `api_key_env` set, a variable that is absent, and a render with `--render-only`.** The render succeeds and costs 0 USD. Task 3, `test_render_only_needs_no_key_in_the_environment`.
3. **A bad value in an entry that is not selected.** The run stops at once, and the message names that entry. Task 2, `test_a_bad_value_in_an_entry_that_is_not_selected_names_that_entry`.
4. **An old file with `[provider]`.** The message names `provider`, so the person knows that the table is the problem. Task 2, `test_the_old_provider_table_is_an_unknown_table`.
5. **A config file named `renfield.toml` written by a test, then overwritten by the CLI test helper.** The helper writes `cli.toml`, not `renfield.toml`, so `test_a_config_file_that_is_not_utf8_exits_1` still reads the bad file. Task 2, step 2.

---

### Task 1: `model_entry` in `Step` and in the record

**Files:**
- Modify: `src/renfield/config.py` (constants near line 26, `Step` at lines 44-79)
- Modify: `src/renfield/record.py:25-27`
- Modify: `src/renfield/step.py:101-107`
- Test: `tests/test_config.py`, `tests/test_step.py`

**Interfaces:**
- Produces: `renfield.config.ENTRY_PATTERN` (compiled regex `^[a-z0-9_-]{1,64}$`), `renfield.config.ENTRY_RULE` (str), `Step.model_entry: str | None = None`, `StepRecord.model_entry: str | None = None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_config.py`, add 2 rows to the parametrize list of `test_a_step_built_by_hand_is_checked_and_names_the_key` (after `("skills", ["not-a-skill"]),`):

```python
        ("model_entry", "Bad Name"),
        ("model_entry", "a.b"),
```

At the end of `tests/test_config.py`, add:

```python
def test_a_step_built_by_hand_has_no_model_entry_unless_given():
    assert by_hand().model_entry is None
    assert by_hand(model_entry="flash").model_entry == "flash"
```

In `tests/test_step.py`, after `test_the_child_runs_in_the_working_directory`, add:

```python
def test_the_record_names_the_model_entry(tmp_path):
    record = call(
        tmp_path, fake_claude(tmp_path, stream=SUCCESS),
        step=a_step(model_entry="flash"),
    )
    assert record.model_entry == "flash"
    data = json.loads((tmp_path / "out" / "record.json").read_text())
    assert data["model_entry"] == "flash"
    assert data["model"] == "m", "model keeps the raw ID"


def test_a_step_with_no_model_entry_records_none(tmp_path):
    record = call(tmp_path, fake_claude(tmp_path, stream=SUCCESS))
    assert record.model_entry is None
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_config.py tests/test_step.py -q`
Expected: FAIL. The messages say `unexpected keyword argument 'model_entry'`.

- [ ] **Step 3: Write the code**

In `src/renfield/config.py`, after `NAME_PATTERN = ...` (line 26), add:

```python
# An entry name has no dot: TOML reads [models.a.b] as the entry a with a
# nested table b.
ENTRY_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")
ENTRY_RULE = "1 to 64 characters of a-z, 0-9, '-', and '_'"
```

In `Step`, add a field after `skills`:

```python
    model_entry: str | None = None
```

In `Step.__post_init__`, after the loop over `self.skills`, add:

```python
        if self.model_entry is not None and not (
            isinstance(self.model_entry, str)
            and ENTRY_PATTERN.fullmatch(self.model_entry)
        ):
            raise ConfigError(
                f"model_entry: the value {self.model_entry!r} is not {ENTRY_RULE}"
            )
```

In `src/renfield/record.py`, after `effort: str | None = None`, add:

```python
    model_entry: str | None = None          # the [models.<name>] of the file
```

In `src/renfield/step.py`, in the `StepRecord(...)` call, after `effort=step.effort,`, add:

```python
        model_entry=step.model_entry,
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest -q`
Expected: PASS, 210 tests.

- [ ] **Step 5: Mutation check**

1. In `step.py`, replace `model_entry=step.model_entry,` with `model_entry=None,`. Run `uv run pytest tests/test_step.py -q -k model_entry`. Expected: `test_the_record_names_the_model_entry` fails. Restore the line.
2. In `Step.__post_init__`, replace `ENTRY_PATTERN` with `NAME_PATTERN`. Run `uv run pytest tests/test_config.py -q -k by_hand`. Expected: the case `("model_entry", "a.b")` fails. Restore the line.

- [ ] **Step 6: Commit**

```bash
git add src/renfield/config.py src/renfield/record.py src/renfield/step.py tests/test_config.py tests/test_step.py
git commit -m "feat: Step and the record hold the model entry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: the `[models.<name>]` file format

**Files:**
- Modify: `src/renfield/config.py` (constants at lines 28-31, `load` at lines 88-145, `_read` at lines 148-174, `_api_key` at lines 177-200)
- Modify: `tests/test_config.py` (migration and new tests)
- Modify: `tests/test_cli.py` (migration only, so that the suite stays green)

**Interfaces:**
- Consumes: `ENTRY_PATTERN`, `ENTRY_RULE`, `Step.model_entry` from Task 1.
- Produces: `load(path=None, *, overrides=None, env=None, resolve_key=True) -> Settings`. `overrides["model"]` is an entry name. `settings.step.model_entry` is the selected entry name. `renfield.config.NO_MODEL` (str).

- [ ] **Step 1: Migrate the existing config tests to the new format**

In `tests/test_config.py`:

1. Replace each `[provider]` in a test string with `[models.m]`. Each of these strings already holds `model = "m"`. Command: `sed -i '' 's/\[provider\]/[models.m]/g' tests/test_config.py`. Then fix the 3 items below by hand.
2. Replace `FULL` with:

```python
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
```

3. Replace `test_an_override_wins_over_the_file_and_changes_1_key_only` with:

```python
def test_an_override_wins_over_the_entry_and_changes_1_key_only(tmp_path):
    settings = load(
        write(tmp_path, FULL),
        overrides={"timeout_min": 50, "effort": None},
        env={"OR_KEY": "k"},
    )
    assert settings.step.timeout_min == 50
    # effort was None, so the entry value stands.
    assert settings.step.effort == "medium"
```

4. Delete `test_no_file_and_no_model_names_both_ways_to_set_it`. Rule 8 replaces it in step 3.
5. In `test_a_good_step_name_is_accepted` and `test_a_bad_step_name_is_an_error`, add the `tmp_path` argument and replace `load(None, overrides={"name": name, "model": "m"}, env={})` with `load(write(tmp_path, ONE), overrides={"name": name}, env={})`.

- [ ] **Step 2: Migrate the CLI tests to the new format**

In `tests/test_cli.py`:

1. After the `AUTH = ...` block, add:

```python
def config_of(tmp_path, text='[models.m]\nmodel = "m"\n', name="cli.toml"):
    """Write the config file of a test. The default name is cli.toml, and not
    renfield.toml: a test that writes its own renfield.toml must not lose it.
    A test that passes its own --config to argv() uses another name, because
    argv() writes cli.toml after the arguments of the call are built."""
    path = tmp_path / name
    path.write_text(text)
    return path
```

2. In `argv`, after `"--run-dir", str(tmp_path / "out"),`, add `"--config", str(config_of(tmp_path)),`.
3. In `test_a_value_keeps_each_equals_sign_after_the_first` and in `test_a_template_that_needs_a_value_nobody_gave_exits_1`, add `"--config", str(config_of(tmp_path)),` before `"--model", "m",`.
4. In `test_a_config_file_that_is_not_utf8_exits_1`, replace `b"[provider]\nmodel = \"caf\xe9\"\n"` with `b"[models.m]\nmodel = \"caf\xe9\"\n"`. The flag `--config bad` comes after the `--config` of `argv`, and argparse keeps the last one.
5. In `test_the_default_config_file_is_read_when_no_config_is_given`, replace `'[provider]\nmodel = "from-the-default-file"\n'` with `'[models.m]\nmodel = "from-the-default-file"\n'`.
6. Replace `test_the_cli_resolves_an_api_key_from_the_environment` with:

```python
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
```

- [ ] **Step 3: Write the failing tests of the rules**

At the end of `tests/test_config.py`, add:

```python
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
```

- [ ] **Step 4: Run the tests and watch them fail**

Run: `uv run pytest -q`
Expected: FAIL. Most failures say `unknown table [models]` or `unexpected keyword argument 'resolve_key'`. Read 3 of the failures and confirm that the cause is the missing code, and not an error in the test.

- [ ] **Step 5: Write the code**

In `src/renfield/config.py`, replace the 4 lines `PROVIDER_KEYS = ...` to `TABLES = ...` with:

```python
PROVIDER_KEYS = ("kind", "model", "effort", "api_key", "api_key_env", "base_url")
STEP_KEYS = ("timeout_min", "max_usd", "retries")
ENTRY_KEYS = PROVIDER_KEYS + STEP_KEYS
PATH_KEYS = ("run_dir", "prompt", "transcript", "artifacts", "record")
TABLES = {"step": STEP_KEYS, "paths": PATH_KEYS}
TOP_LEVEL = ("default", "models", "step", "paths")
LIMITS = {
    "timeout_min": (TIMEOUT_RANGE, int),
    "max_usd": (MAX_USD_RANGE, float),
    "retries": (RETRIES_RANGE, int),
}
NO_MODEL = "no model: add a [models.<name>] table to renfield.toml"
```

Replace the function `load` with:

```python
def load(
    path: Path | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    resolve_key: bool = True,
) -> Settings:
    """Read the file, select 1 entry, apply the overrides, check each range,
    and give the settings.

    `overrides["model"]` is the name of an entry, and not a model ID.
    `resolve_key=False` does not read the key from the environment: a render
    costs 0 USD and needs no key.
    """
    data = _read(path)
    given = {key: value for key, value in (overrides or {}).items() if value is not None}
    env = {} if env is None else env

    # The file cannot set the name: 1 file serves many steps. The CLI passes
    # it, and the default serves a direct call of the library.
    name = given.get("name", "step")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise ConfigError(
            f"name: the value {name!r} is not 1 to 64 characters of a-z, 0-9, "
            f"'-', '_', and '.'"
        )

    step_table = data.get("step", {})
    for key, value in step_table.items():
        _check_limit(f"step.{key}", key, value)
    entries = data.get("models", {})
    for entry_name, entry in entries.items():
        _check_entry(entry_name, entry)
    selected = _select(entries, data, given.get("model"))
    entry = entries[selected]

    def pick(key: str, default: Any = None) -> Any:
        if key in given:
            return given[key]
        if key in entry:
            return entry[key]
        return step_table.get(key, default)

    effort = _one_of("effort", pick("effort", "high"), EFFORTS)
    timeout_min = _in_range("timeout_min", pick("timeout_min", 20), TIMEOUT_RANGE, int)
    retries = _in_range("retries", pick("retries", 2), RETRIES_RANGE, int)
    max_usd = pick("max_usd")
    if max_usd is not None:
        max_usd = _in_range("max_usd", max_usd, MAX_USD_RANGE, float)

    provider = Provider(
        kind=entry.get("kind", "subscription"),
        api_key=_api_key(f"models.{selected}", entry, env) if resolve_key else None,
        base_url=entry.get("base_url"),
    )
    step = Step(
        name=name,
        model=str(entry["model"]),
        effort=effort,
        timeout_min=timeout_min,
        max_usd=max_usd,
        retries=retries,
        add_dirs=[Path(p) for p in given.get("add_dirs", [])],
        skills=list(given.get("skills", [])),
        model_entry=selected,
    )
    path_table = data.get("paths", {})

    def pick_path(key: str) -> Any:
        return given[key] if key in given else path_table.get(key)

    paths = replace(
        Paths(),
        **{key: str(pick_path(key)) for key in PATH_KEYS if pick_path(key)},
    )
    return Settings(provider=provider, step=step, paths=paths)
```

Replace the loop at the end of `_read` (from `for table, values in data.items():` to `return data`) with:

```python
    for key, values in data.items():
        if key not in TOP_LEVEL:
            raise ConfigError(
                f"unknown key or table {key!r}. The top level holds default, "
                f"[models.<name>], [step], and [paths]."
            )
        if key == "default":
            continue
        if not isinstance(values, dict):
            raise ConfigError(f"[{key}] must be a table")
        if key == "models":
            continue
        for name in values:
            if name not in TABLES[key]:
                raise ConfigError(
                    f"unknown key {name!r} in [{key}]. The keys are "
                    f"{', '.join(TABLES[key])}."
                )
    return data
```

Replace the function `_api_key` with these 5 functions:

```python
def _check_entry(name: str, entry: Any) -> None:
    """Check 1 [models.<name>] table: its name, its keys, and its ranges.

    Each entry is checked, and not only the selected one: a bad entry fails
    at once, and not on the day that a caller selects it.
    """
    if not isinstance(entry, dict):
        raise ConfigError(f"models.{name} must be a [models.{name}] table")
    for key, value in entry.items():
        if isinstance(value, dict):
            raise ConfigError(f"[models.{name}.{key}]: an entry name has no dot")
    if not ENTRY_PATTERN.fullmatch(name):
        raise ConfigError(f"models: the entry name {name!r} is not {ENTRY_RULE}")
    for key in entry:
        if key not in ENTRY_KEYS:
            raise ConfigError(
                f"unknown key {key!r} in [models.{name}]. The keys are "
                f"{', '.join(ENTRY_KEYS)}."
            )
    label = f"models.{name}"
    if not entry.get("model"):
        raise ConfigError(f"{label}.model: no value. Each entry names a model.")
    kind = _one_of(f"{label}.kind", entry.get("kind", "subscription"), KINDS)
    _one_of(f"{label}.effort", entry.get("effort", "high"), EFFORTS)
    for key in STEP_KEYS:
        if key in entry:
            _check_limit(f"{label}.{key}", key, entry[key])
    _check_key_source(label, kind, entry)


def _check_limit(label: str, key: str, value: Any) -> None:
    limits, kind = LIMITS[key]
    _in_range(label, value, limits, kind)


def _check_key_source(label: str, kind: str, entry: Mapping[str, Any]) -> None:
    """The 2 checks of the key that read the file, and not the environment."""
    if entry.get("api_key") and entry.get("api_key_env"):
        raise ConfigError(
            f"{label}: api_key and api_key_env are both set. Use 1 of them."
        )
    if kind != "subscription" and not (entry.get("api_key") or entry.get("api_key_env")):
        raise ConfigError(
            f"{label}: the provider kind {kind!r} needs a key. "
            f"Set api_key_env or api_key."
        )


def _api_key(label: str, entry: Mapping[str, Any], env: Mapping[str, str]) -> str | None:
    """Read the key of the selected entry. _check_key_source ran before."""
    literal = entry.get("api_key")
    variable = entry.get("api_key_env")
    if literal:
        return str(literal)
    if variable:
        value = env.get(str(variable))
        if not value:
            raise ConfigError(
                f"{label}.api_key_env names {variable!r}, and that variable is "
                f"empty or absent"
            )
        return value
    return None


def _select(entries: Mapping[str, Any], data: Mapping[str, Any], chosen: Any) -> str:
    """Give the name of the entry of this call: the override, then default,
    then the only entry."""
    if not entries:
        raise ConfigError(NO_MODEL)
    names = ", ".join(entries)
    default = data.get("default")
    if "default" in data:
        if not isinstance(default, str):
            raise ConfigError(
                f"default: the value {default!r} is not a string. It names 1 "
                f"entry. The entries are {names}."
            )
        if default not in entries:
            raise ConfigError(
                f"default: the value {default!r} names no entry. "
                f"The entries are {names}."
            )
    if chosen is not None:
        if chosen not in entries:
            raise ConfigError(
                f"model: the value {chosen!r} names no entry. "
                f"The entries are {names}."
            )
        return chosen
    if default is not None:
        return default
    if len(entries) == 1:
        return next(iter(entries))
    raise ConfigError(
        f"model: the file has {len(entries)} entries and no default. Set "
        f'default = "<name>" in the file, or pass --model. '
        f"The entries are {names}."
    )
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `uv run pytest -q`
Expected: PASS. Write down the count. It must be 210 plus the new tests of step 3, minus the 1 deleted test.

- [ ] **Step 7: Mutation check**

Do each mutation, run `uv run pytest tests/test_config.py -q`, confirm the named test fails, and restore the line.

1. Rule 4: in `load`, delete the loop `for entry_name, entry in entries.items(): _check_entry(entry_name, entry)`, and after the line `entry = entries[selected]` add `_check_entry(selected, entry)`. Now only the selected entry gets its check. Expected: `test_a_bad_value_in_an_entry_that_is_not_selected_names_that_entry` fails.
2. Rule 5: in `load`, replace `if resolve_key else None` with `if True else None`. Expected: `test_resolve_key_false_does_not_read_the_environment` fails.
3. Rule 5: in `_check_entry`, delete the call `_check_key_source(label, kind, entry)`. Expected: `test_a_key_and_a_key_variable_in_any_entry_is_an_error` and `test_resolve_key_false_still_checks_the_file` fail.
4. Rule 2: in `_check_entry`, delete the loop that looks for a nested table. Expected: `test_a_dot_in_an_entry_name_is_named_as_the_cause` fails.
5. Messages: in `_check_entry`, replace `_check_limit(f"{label}.{key}", key, entry[key])` with `_check_limit(key, key, entry[key])`. Expected: the `timeout_min`, `retries`, and `max_usd` cases of the rule 4 test fail.
6. Precedence: in `pick`, swap the 2 `if` blocks, so that the entry wins over the override. Expected: `test_each_override_wins_over_the_selected_entry` fails.
7. Rule 6: in `_select`, delete the `if default not in entries:` block. Expected: `test_a_default_that_names_no_entry_names_the_entries` fails.

- [ ] **Step 8: Commit**

```bash
git add src/renfield/config.py tests/test_config.py tests/test_cli.py
git commit -m "feat: renfield.toml holds named models

[models.<name>] replaces [provider]. Each entry holds a provider, a
model, an effort, and its own step limits. default, or the only entry,
or the override model selects 1 entry.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: the CLI flags and the first console line

**Files:**
- Modify: `src/renfield/cli.py:55-57` (the flags), `cli.py:89-106` (the overrides and the `load` call), `cli.py:120-128` (the first console line)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load(..., resolve_key=...)` and `settings.step.model_entry` from Task 2.
- Produces: nothing that a later task calls.

- [ ] **Step 1: Write the failing tests**

At the end of `tests/test_cli.py`, add:

```python
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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_cli.py -q -k "removed_provider or first_line or render_only_needs or paid_run_needs"`
Expected: 3 tests FAIL. `test_a_removed_provider_flag_exits_2` fails because argparse accepts the flags. `test_the_first_line_names_the_entry_and_the_model` fails because the line is `t: deepseek/deepseek-v4.1-flash, effort medium, no cost limit`. `test_render_only_needs_no_key_in_the_environment` fails with exit code 1. `test_a_paid_run_needs_the_key_in_the_environment` passes already: it guards the other side of the change.

- [ ] **Step 3: Write the code**

In `src/renfield/cli.py`, replace the 3 lines:

```python
    run.add_argument("--provider", dest="kind")
    run.add_argument("--api-key-env")
    run.add_argument("--model")
```

with:

```python
    run.add_argument("--model", metavar="NAME",
                     help="a [models.<name>] entry of the TOML file. "
                          "Default: the default key, or the only entry.")
```

In `_run`, delete the 2 lines `"kind": args.kind,` and `"api_key_env": args.api_key_env,` from `overrides`. Replace the `load` call with:

```python
    settings = load(
        config_path,
        overrides=overrides,
        env=os.environ,
        resolve_key=not args.render_only,
    )
```

Replace the `print(...)` of the first console line with:

```python
    model = settings.step.model
    if settings.step.model_entry:
        model = f"{settings.step.model_entry} ({model})"
    print(f"{settings.step.name}: {model}, effort {settings.step.effort}, {limit}")
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest -q`
Expected: PASS. The count is the count of Task 2 plus 5.

- [ ] **Step 5: Mutation check**

1. Replace `resolve_key=not args.render_only,` with `resolve_key=True,`. Run `uv run pytest tests/test_cli.py -q -k render_only_needs`. Expected: FAIL. Restore the line.
2. Replace `resolve_key=not args.render_only,` with `resolve_key=False,`. Run `uv run pytest tests/test_cli.py -q -k paid_run_needs`. Expected: FAIL, because the run starts with no key and the fake program exits 0. Restore the line.
3. Delete the 2 lines `if settings.step.model_entry:` and `model = f"..."`. Run `uv run pytest tests/test_cli.py -q -k first_line`. Expected: FAIL. Restore the lines.

- [ ] **Step 6: Commit**

```bash
git add src/renfield/cli.py tests/test_cli.py
git commit -m "feat: --model selects a named entry, and a render needs no key

--provider and --api-key-env are removed. The first console line names
the entry and the model.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: the documents of Renfield

**Files:**
- Modify: `docs/design.md` (sections 4.2, 4.4, 5.1, 5.2, 5.3, 10, 10.1)
- Modify: `README.md` (the CLI example near line 52, the configuration near line 88)
- Modify: `AGENTS.md:14`, `AGENTS.md:113`

**Interfaces:** none.

- [ ] **Step 1: `docs/design.md`, section 4.2**

In the `Step` code block, after `skills: list[Skill] = ()`, add:

```python
    model_entry: str | None = None # the [models.<name>] of the file, or None
```

After the paragraph that starts "The `name` reaches the file names", add:

```markdown
`load()` sets `model_entry` to the selected entry. A caller that builds a
`Step` itself can leave it empty.
```

- [ ] **Step 2: `docs/design.md`, section 4.4**

Replace the row `| \`provider\`, \`model\`, \`effort\` | What ran |` with:

```markdown
| `provider`, `model`, `effort` | What ran. `model` is the raw model ID. |
| `model_entry` | The `[models.<name>]` entry that the caller selected, or null |
```

- [ ] **Step 3: `docs/design.md`, section 5.1**

Replace the TOML block of section 5.1 with the TOML block of section 2 of the spec. Replace the paragraph after it with:

```markdown
Each `[models.<name>]` entry holds a provider, a model, an effort, and the 3
step limits. `[step]` holds the step limits that all entries share. `default`
names the entry of a call with no `--model`. With exactly 1 entry, `default` is
optional.

`api_key_env` names an environment variable. `api_key` holds the key itself.
**If an entry sets both, the config check fails.** A file that holds a key must
not go into git.

**Renfield checks each entry, and not only the selected entry.** It reads the
key from the environment for the selected entry only, and not for a render
with `--render-only`.
```

- [ ] **Step 4: `docs/design.md`, section 5.2**

Replace the code block and the paragraph of section 5.2 with section 3 of the spec, from "`[step]` accepts 3 keys only" to "A flag replaces only its own key.".

- [ ] **Step 5: `docs/design.md`, section 5.3**

After the row of `name`, add 2 rows:

```markdown
| entry name | 1 to 64 characters of `a-z`, `0-9`, `-`, `_`. No dot. | none |
| `default` | the name of 1 entry | the only entry, when the file has 1 |
```

After the paragraph "A value outside its range is a config error...", add:

```markdown
For a key of an entry, the message names `models.<name>.<key>`. For a key of
`[step]`, it names `step.<key>`.
```

- [ ] **Step 6: `docs/design.md`, sections 10 and 10.1**

In the example command of section 10, replace `--model deepseek/deepseek-v4.1-flash` with `--model flash`. In the flag table, replace the 2 rows of `--model, --effort, ...` and `--provider, --api-key-env` with:

```markdown
| `--model NAME` | Select the `[models.<name>]` entry. Default: `default`, or the only entry. |
| `--effort`, `--timeout-min`, `--max-usd`, `--retries` | Override 1 key of the selected entry. |
```

In section 10.1, replace the first line of the console example with:

```
review: flash (deepseek/deepseek-v4.1-flash), effort high, limit 6.0 USD
```

- [ ] **Step 7: `README.md`**

In the CLI example, replace `--model claude-opus-5 \` with `--model opus \`. Replace the TOML block of the section "Configuration" with the TOML block of section 2 of the spec. Replace the line "The order of precedence is: built-in defaults, then this file, then the CLI flag." with:

```markdown
The order of precedence is: built-in defaults, then `[step]`, then the selected
`[models.<name>]` entry, then the CLI flag. `--model NAME` selects the entry.
```

- [ ] **Step 8: `AGENTS.md`**

Run `uv run pytest -q | tail -1` and read the count. On line 14 and on line 113, replace `205` with that count.

- [ ] **Step 9: Check the documents**

Run: `grep -n "\[provider\]\|--api-key-env\|--provider" README.md docs/design.md AGENTS.md`
Expected: no line, except a line of `docs/build-plan.md` (that file is a record of the first build, and it does not change).

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add docs/design.md README.md AGENTS.md
git commit -m "docs: named models in the design, the README, and AGENTS.md

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: the plugin spec

**Files:**
- Modify: `docs/superpowers/specs/2026-10-12-claude-code-plugin-design.md` (section 5.1 table text, section 6)

**Interfaces:** none.

- [ ] **Step 1: Change section 6**

Replace the table of the decision file with:

```markdown
| Kind | Decision | Date | Model entry | Model ID | Comparison run |
|---|---|---|---|---|---|
| code-review | switch | 2026-10-12 | flash | deepseek/deepseek-v4.1-flash | .renfield/runs/2026-10-12T14-03-51-code-review |
```

Replace rule 3 of section 6 with:

```markdown
3. A row names the model entry and the raw model ID. If the entry in
   `renfield.toml` now holds a different model ID, the decision does not
   apply. Claude tells the operator and offers a new comparison.
```

- [ ] **Step 2: Change section 5.1**

Replace the sentence "Each question names the model, `max_usd`, `timeout_min`, and the warning of section 4, item 6." with:

```markdown
Each question names the model entry, its model ID, `max_usd`, `timeout_min`,
and the warning of section 4, item 6. If `renfield.toml` has 2 or more
entries, Claude asks which entry to use, and passes it with `--model NAME`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-10-12-claude-code-plugin-design.md
git commit -m "docs: the plugin spec uses named models

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
