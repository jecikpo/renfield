# Named models in `renfield.toml`: design

Date: 2026-10-12. Status: approved in conversation. Revision 2 adds the 11
findings of a review on the Fable model, of the same date.

## 1. Purpose

`renfield.toml` holds 1 `[provider]` table with 1 model (`config.py:28`). A
caller cannot keep 2 models in 1 file and select 1 of them for a task.

This change replaces the 1 model with named entries. The CLI flag `--model NAME`
selects 1 entry. Each entry holds a provider, a model, an effort, and its own
step limits.

### 1.1 Decisions

| Item | Decision | Rejected options |
|---|---|---|
| Content of an entry | The 6 provider keys and the 3 step keys | Model and effort only, with 1 shared provider; the provider keys without the step keys |
| The old `[provider]` table | Removed. No user has the old format, because the code is not published. | Keep it as a fallback |
| The selection flag | `--model NAME`, with a new meaning | `--profile NAME`; `--use NAME` |
| The flags `--provider` and `--api-key-env` | Removed. A flag must not mix the keys of 2 entries. | Keep them |
| The flag `--effort` | Kept. The same model can do a task at a different effort. | Remove it |
| The run without `--model` | A `default` key names the entry. With exactly 1 entry, the key is optional. | `--model` always required; the first entry of the file |
| The entry name in the record | A new field `model_entry` | The raw model ID only |
| `[paths]` in an entry | No. The run folders do not depend on the model. | Paths for each entry |
| The characters of an entry name | `a-z`, `0-9`, `-`, `_`. No dot. | The dot of a step name, with quotes in TOML |
| `--render-only` and the API key | The render does not read the key. It costs 0 USD. | Read the key, as before |

## 2. The file

```toml
# renfield.toml
default = "flash"

[step]                 # shared values for all entries
timeout_min = 20
retries     = 2

[models.flash]
kind        = "openrouter"
api_key_env = "OPENROUTER_API_KEY"
model       = "deepseek/deepseek-v4.1-flash"
effort      = "high"
max_usd     = 0.50

[models.opus]
kind        = "subscription"
model       = "claude-opus-5-5"
effort      = "xhigh"
max_usd     = 6.0
timeout_min = 40

[paths]
run_dir    = "runs/{stamp}-{step}"
prompt     = "prompts/{step}.md"
transcript = "transcripts/{step}.jsonl"
artifacts  = "artifacts"
record     = "record.json"
```

## 3. The precedence

`[step]` accepts 3 keys only: `timeout_min`, `max_usd`, and `retries`. These 3
keys have 4 layers:

```
built-in default  <  [step]  <  [models.<name>]  <  CLI flag or function argument
```

The 6 provider keys (`kind`, `model`, `effort`, `api_key`, `api_key_env`,
`base_url`) have no `[step]` layer. They have 3 layers:

```
built-in default  <  [models.<name>]  <  CLI flag or function argument
```

Of the provider keys, only `effort` has a flag (`--effort`). An entry replaces
only the keys that it sets. A flag replaces only its own key.

## 4. The rules

Each rule is a config error, exit code 1. **The message names the key, the
range, and the value.** For a key of an entry, the message names the full key,
for example `models.opus.timeout_min`. For a key of `[step]`, the message
names `step.timeout_min`. This tells the person which table holds the bad
value.

1. The top level accepts only `default`, `models`, `step`, and `paths`. Each
   other key or table is an error, and `[provider]` is an unknown table.
   `models` must be a table. Each value of `models` must be a table.
2. An entry name is 1 to 64 characters of `a-z`, `0-9`, `-`, and `_`. A dot is
   not permitted, because TOML reads `[models.a.b]` as the entry `a` with a
   nested table `b`. If a value inside an entry is a table, the message is:
   `[models.a.b]: an entry name has no dot`.
3. An entry accepts 9 keys: `kind`, `model`, `effort`, `api_key`,
   `api_key_env`, `base_url`, `timeout_min`, `max_usd`, and `retries`. Each
   other key is an error. `model` is required.
4. Renfield checks the ranges of all keys of all entries, and not only of the
   selected entry. A bad entry fails at once, and not on the day that a caller
   selects it. The ranges are the ranges of `docs/design.md`, section 5.3.
5. **Renfield reads the API key from the environment for the selected entry
   only.** An entry that is not selected and that sets `api_key_env` does not
   need that variable to exist. 2 checks of the file apply to all entries:
   - `api_key` and `api_key_env` are both set.
   - The kind is not `subscription`, and the entry sets neither `api_key` nor
     `api_key_env`.
   **`--render-only` does not read the key from the environment.** A render
   costs 0 USD. The 2 file checks above still apply to a render.
6. `default` must be a string, and it must name an entry that exists.
7. `--model NAME` must name an entry that exists. The message lists the names
   of the file.
8. `load()` raises this rule, and not `cli.py`. If no file is given, or the
   file has no entries, the message is:
   `no model: add a [models.<name>] table to renfield.toml`.
   `load(None)` is no longer a valid call.
9. The flags `--effort`, `--timeout-min`, `--max-usd`, and `--retries` replace
   the value of the selected entry.
10. If the file has 2 or more entries and no `default` key, and the call has no
    `--model`, the run stops. The message lists the names of the file.

**A change in behavior.** The CLI cannot run without a file. Before this
change, `--model X` was enough. A library caller that builds `Provider` and
`Step` itself does not change. A library caller of `load()` must give a file.

## 5. The code

| Module | Change |
|---|---|
| `config.py` | The file format, rules 1 to 10, and the precedence of section 3. A new pattern `ENTRY_PATTERN = ^[a-z0-9_-]{1,64}$`. In `load()`, the override `model` is an entry name. The overrides `kind` and `api_key_env` are removed. `load()` gets a keyword argument `resolve_key: bool = True`; `cli.py` passes `False` for `--render-only`. `_in_range` and `_one_of` get the full key name from their caller. |
| `config.py`, `Step` | A new field `model_entry: str \| None = None`. If it has a value, `__post_init__` checks it against `ENTRY_PATTERN`. |
| `record.py` | A new field `model_entry: str \| None` in `StepRecord`, after `effort`. |
| `step.py` | The record gets `model_entry` from `step.model_entry` (`step.py:104`). The command of the child does not change: it gets `step.model`, the raw ID (`step.py:200`). |
| `cli.py` | `--model` selects an entry, with new help text. `--provider` and `--api-key-env` are removed. The first console line (`cli.py:125`) shows `flash (deepseek/deepseek-v4.1-flash)`. If no entry is set, it shows the raw ID, as before. |

`provider.py`, `stream.py`, `paths.py`, `outputs.py`, and `testing.py` do not
change. The change does not touch the 5 facts of `AGENTS.md`.

## 6. The documents

- `docs/design.md`:
  - section 4.2 (`Step`), section 4.4 (the record);
  - sections 5.1, 5.2, and 5.3. The range table of 5.3 gets 2 new rows: the
    entry name and `default`;
  - section 10 (the CLI) and the console example of section 10.1.
- `README.md`: the configuration example and the CLI example.
- `AGENTS.md`: the test count, on 2 lines.
- `docs/superpowers/specs/2026-10-12-claude-code-plugin-design.md`: the
  "Model" column of the decision file holds the entry name and the raw ID. A
  decision does not apply when the raw ID of its entry changed.

## 7. The tests

Write each test before its code (`AGENTS.md`, method 1).

1. 1 test for each of the 10 rules. Each test asserts the text of the message.
   Rules 1, 2, and 6 get 1 test for each clause: `models` not a table, an entry
   not a table, a dot in an entry name, `default` not a string, and `default`
   that names no entry.
2. The test of rule 4 puts the bad value in an entry that is not selected. A
   bad value in the selected entry passes when the code checks the selected
   entry only. The test asserts the full key, `models.<name>.<key>`.
3. The test of rule 5 has 1 entry that is not selected, with an
   `api_key_env` that the environment does not hold. 1 more test: a render
   with `--render-only` succeeds when the variable of the selected entry is
   absent.
4. The test of rule 9 is parametrized over the 4 flags.
5. 1 test of the precedence for each layer of section 3.
6. 1 test that `model_entry` reaches `record.json` and the first console line.
7. 1 case `("model_entry", "Bad Name")` in the test of a `Step` built by hand
   (`tests/test_config.py:243`).
8. 1 CLI test that `--provider` and `--api-key-env` exit with code 2. argparse
   raises `SystemExit`, and `main()` does not catch it. The test catches
   `SystemExit`.
9. The move of the existing tests:
   - The `argv` helper of `tests/test_cli.py` writes a config file with 1 entry
     `m`, and passes `--config`. About 25 CLI tests use this helper.
   - `tests/test_cli.py:213` is rewritten. It asserted that a raw model ID of
     the flag beats the file. It now asserts that `--model` selects 1 of 2
     entries, and that the effort of that entry reaches the child.
   - `tests/test_config.py:68` and the 2 step-name tests (`:158`, `:164`) call
     `load(None)`. They change to give a file.
   - Each test that writes `[provider]` changes to `[models.m]`.

**Mutation check (`AGENTS.md`, method 5).** For each new test, change the line
that the test protects, and watch the test fail. The most important case is
rule 5. If Renfield reads the key of each entry, the test with an unused entry
must fail.

## 8. The commits

1. `Step.model_entry` and the record field.
2. The file format in `config.py`.
3. The CLI flags.
4. The documents of Renfield.
5. The plugin spec.
