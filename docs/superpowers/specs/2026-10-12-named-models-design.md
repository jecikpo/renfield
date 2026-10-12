# Named models in `renfield.toml`: design

Date: 2026-10-12. Status: approved in conversation, waiting for review of this
file.

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

For each key:

```
built-in default  <  [step]  <  [models.<name>]  <  CLI flag or function argument
```

`[step]` holds the values that all entries share. An entry replaces only the
keys that it sets. A flag replaces only its own key.

## 4. The rules

Each rule is a config error, exit code 1. **The message names the key, the
range, and the value.**

1. The top level accepts only `default`, `[models.*]`, `[step]`, and
   `[paths]`. Each other key or table is an error, and `[provider]` is an
   unknown table.
2. An entry name is 1 to 64 characters of `a-z`, `0-9`, `-`, `_`, and `.`. This
   is the range of a step name (`NAME_PATTERN`).
3. An entry accepts 9 keys: `kind`, `model`, `effort`, `api_key`,
   `api_key_env`, `base_url`, `timeout_min`, `max_usd`, and `retries`. Each
   other key is an error. `model` is required.
4. Renfield checks the ranges of all keys of all entries. A bad entry fails at
   once, and not on the day that a caller selects it. The ranges are the ranges
   of `docs/design.md`, section 5.3.
5. **Renfield reads the API key for the selected entry only.** An entry that
   is not selected and that sets `api_key_env` does not need that variable to
   exist. The rule "`api_key` and `api_key_env` are both set" applies to all
   entries, because it is a check of the file and not of the environment.
6. `default` must name an entry that exists.
7. `--model NAME` must name an entry that exists. The message lists the names
   of the file.
8. If no file is present, or the file has no entries, the CLI stops with this
   message: `no model: add a [models.<name>] table to renfield.toml`.
9. The flags `--effort`, `--timeout-min`, `--max-usd`, and `--retries` replace
   the value of the selected entry.
10. If the file has 2 or more entries and no `default` key, and the call has no
    `--model`, the run stops. The message lists the names of the file.

**A change in behavior.** The CLI cannot run without a file. Before this
change, `--model X` was enough. A library caller that builds `Provider` and
`Step` itself does not change.

## 5. The code

| Module | Change |
|---|---|
| `config.py` | The file format, rules 1 to 10, and the precedence of section 3. In `load()`, the override `model` is an entry name. The overrides `kind` and `api_key_env` are removed. |
| `config.py`, `Step` | A new field `model_entry: str \| None = None`. If it has a value, `__post_init__` checks it against `NAME_PATTERN`. |
| `record.py` | A new field `model_entry: str \| None` in `StepRecord`. |
| `step.py` | The record gets `model_entry` from `step.model_entry` (`step.py:104`). |
| `cli.py` | `--model` selects an entry, with new help text. `--provider` and `--api-key-env` are removed. The first console line (`cli.py:125`) shows `flash (deepseek/deepseek-v4.1-flash)`. If no entry is set, it shows the raw ID, as before. |

`provider.py`, `stream.py`, `paths.py`, `outputs.py`, and `testing.py` do not
change. The change does not touch the 5 facts of `AGENTS.md`.

## 6. The documents

- `docs/design.md`: sections 4.2, 4.4, 5.1, 5.2, 5.3, and 10.
- `README.md`: the configuration example and the CLI example.
- `AGENTS.md`: the test count.
- `docs/superpowers/specs/2026-10-12-claude-code-plugin-design.md`: the
  "Model" column of the decision file holds the entry name and the raw ID. A
  decision does not apply when the raw ID of its entry changed.

## 7. The tests

Write each test before its code (`AGENTS.md`, method 1).

1. 1 test for each of the 10 rules. Each test asserts the text of the message.
2. 1 test of the precedence for each of the 4 layers of section 3.
3. 1 test that `model_entry` reaches `record.json` and the first console line.
4. 1 CLI test that `--provider` and `--api-key-env` exit with code 2.
5. The existing tests that use `[provider]` or the old `--model` move to the
   new format.

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
