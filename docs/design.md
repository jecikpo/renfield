# Renfield: design

Status: approved design, before implementation
Date: 2026-10-12
Language: ASD-STE100 (Simplified Technical English)
Source: extracted from `skarp/src/skarp/common/`, commit `c274c34`

---

## 1. Purpose

Renfield runs 1 AI agent as a child process, against a prompt template, and
reports what that agent did and what it wrote.

It is the servant, and never the master. The caller decides what the agent must
do. Renfield starts the agent, watches it, kills it when it runs too long,
checks what it wrote, and gives 1 record back.

### 1.1 The first user

A project holds a specification or an implementation plan. A custom agent of
that project asks for a review. The agent runs 1 Renfield command. Renfield
starts a second agent, on a different model, with the plan and the source code.
The second agent writes a report and a verdict file. The first agent reads the
verdict.

Renfield holds no part of that review. It holds no review prompt, no verdict
schema, and no idea of what a plan is. Those belong to the project that calls it.

### 1.2 What Renfield is not

| It is not | Because |
|---|---|
| A phase runner | It runs 1 step. The caller runs the next one. |
| A workflow engine | It has no state between calls. |
| A prompt library | A prompt belongs to the project that uses it. |
| A cost report | It records what the provider reported. It prices nothing. |
| A sandbox | The child agent runs with the rights of the caller. Section 12. |

---

## 2. Decisions

| ID | Decision | Reason |
|---|---|---|
| R1 | 1 package, 1 job: run 1 agent step. | A step runner that also chains steps becomes a workflow engine, and then it fits nobody. |
| R2 | The child is `claude -p` with `--output-format stream-json`. | Claude Code supplies the agent loop, the file tools, the subagents, and the cost data. |
| R3 | 3 provider kinds: `subscription`, `anthropic-api`, `openrouter`. | 1 code path serves a subscription and another vendor. OpenRouter serves the Anthropic message path. |
| R4 | The child environment starts from an allowlist. | The key of the parent, and each `CLAUDE_CODE_*` variable of a parent session, must not reach the child. |
| R5 | The failure class reads `is_error`, and not `subtype`. | Measured: a subscription rate limit reports `subtype: "success"` with `is_error: true`. |
| R6 | Only the class `transient` gets a retry. 2 waits: 30 s and 120 s. | A retry of a rate limit costs 2 waits and a second full call, and it fails again. |
| R7 | A timeout signals the process group: SIGINT, then SIGKILL after 15 s. | The child starts children of its own. Measured: SIGINT gives a cost, SIGKILL loses it. |
| R8 | `outputs_valid` is a field of its own, separate from `status`. | Measured: 1 call wrote a complete 42 KB file and then hit a limit. |
| R9 | 3 configuration layers: defaults, then the file, then the call. | A person keeps the stable values in 1 file and changes 1 value for 1 run. |
| R10 | Each of the 4 paths is configurable, and accepts `{step}` and `{stamp}`. | 2 runs of a changed prompt must not overwrite each other. |
| R11 | The CLI prints progress lines, and the record path on the last line. | A person watches a call of 10 minutes. The calling agent reads the record file. |
| R12 | Each numeric and each enumerated key has a range, checked where it is read. | Measured: `timeout_min = 0` passed a type check and killed the child at once. |
| R13 | The test suite runs against a fake `claude` program. | No network and no money. The helper ships with the package. |
| R14 | `cost_estimated` travels beside the cost. | Measured: Claude Code reported 0.3141 USD for a call that cost about 0.002 USD. |

---

## 3. The call

### 3.1 The command

```
claude -p
  --model <model>
  --effort <effort>
  --input-format text
  --output-format stream-json
  --verbose
  --no-session-persistence
  --setting-sources ""
  --strict-mcp-config
  --dangerously-skip-permissions
  [--max-budget-usd <max_usd>]
  [--add-dir <dir> ...]
  [--plugin-dir <dir> ...]
```

The prompt goes to the standard input of the child. The child writes 1 JSON
event for each line of its standard output.

**`--setting-sources ""` and `--strict-mcp-config` are not optional.** They stop
the child from reading the settings, the hooks, and the MCP servers of the
person who started it. A review that reads the reviewer's own instructions is
not an independent review.

**`--max-budget-usd` is a limit of the child, and not of Renfield.** Claude Code
checks it between turns. Section 9 states what the number means.

### 3.2 The environment

The child environment holds these names of the parent, and no others:

```
PATH  HOME  USER  LOGNAME  SHELL  TMPDIR  LANG  LC_ALL  TERM
```

Renfield then adds the names of the provider kind:

| Kind | Added |
|---|---|
| `subscription` | nothing |
| `anthropic-api` | `ANTHROPIC_API_KEY` |
| `openrouter` | `ANTHROPIC_BASE_URL=https://openrouter.ai/api`, `ANTHROPIC_AUTH_TOKEN`, and `ANTHROPIC_API_KEY=""` |

`ANTHROPIC_API_KEY=""` is an empty value, and not an absent name. An absent name
lets the child find a key elsewhere and bill the wrong account.

`CLAUDE_CONFIG_DIR` is optional. It points the child at a configuration folder
that the caller controls. It keeps the global `CLAUDE.md`, the user hooks, the
user agents, and the memory files of the operator out of the child.

**A `CLAUDE.md` of the working directory still reaches the child.** The
working directory is the material of the task. If the caller does not want
that file read, the caller gives a different working directory.

---

## 4. The API

### 4.1 `Provider`

```python
@dataclass
class Provider:
    kind: str                      # subscription | anthropic-api | openrouter
    api_key: str | None = None
    base_url: str | None = None    # openrouter has a default
```

### 4.2 `Step`

```python
@dataclass
class Step:
    name: str                      # 1 to 64 characters of a-z, 0-9, -, _, .
    model: str
    effort: str                    # low | medium | high | xhigh | max
    timeout_min: int               # 1 to 240
    max_usd: float | None = None   # 0.01 to 1000, or None for no limit
    retries: int = 2               # 0 to 2
    add_dirs: list[Path] = ()
    skills: list[Skill] = ()

@dataclass
class Skill:
    plugin: Path                   # becomes --plugin-dir
    invoke: str | None = None      # becomes 1 line of $invoke_skills
```

A `Skill` with `invoke = None` adds the plugin folder and no line to the
prompt. The child then has the skill, and the prompt does not call it.

The `name` reaches the file names of the run folder. A name with a dot keeps
its last part only: `review.deep` writes `prompts/deep.md`.

### 4.3 `run_step`

```python
def run_step(
    step: Step,
    provider: Provider,
    *,
    workdir: Path,                 # the working directory of the child
    template: Path,                # the prompt template
    values: Mapping[str, str],     # the placeholder values
    paths: Paths,                  # section 5.4
    outputs: Sequence[str] = (),   # files the agent must write
    schemas: Mapping[str, Path] = {},   # output name -> JSON schema
    executable: str = "claude",
    parent_env: Mapping[str, str] | None = None,
    config_dir: Path | None = None,
    on_line: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> StepRecord
```

`run_step` renders the 4 path templates of `paths`. It fills `{step}` from
`step.name` and `{stamp}` from the start time of the call, and then it makes
the folders. The caller passes templates, and not finished paths.

`sleep` is an argument so that a test of the retry policy does not wait 150
seconds.

### 4.4 `StepRecord`

| Field | Meaning |
|---|---|
| `name`, `status` | `ok` or `failed` |
| `error_class`, `error` | Section 8 |
| `provider`, `model`, `effort` | What ran |
| `attempts` | 1, 2, or 3 |
| `cost_usd`, `cost_known`, `cost_estimated`, `unknown_usd` | Section 9 |
| `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` | The 4 counts |
| `num_turns`, `duration_s` | The work |
| `tool_calls` | How many times the agent called each tool |
| `prompt`, `transcript` | Paths, relative to the run folder |
| `outputs`, `outputs_valid` | What the agent wrote, and whether it passed |

**`tool_calls` answers a question that no other field answers.** A document
that an agent wrote with 0 `Read` calls did not look at the code.

---

## 5. Configuration

### 5.1 The file

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
record     = "record.json"
```

`api_key_env` names an environment variable. `api_key` holds the key itself.
**If the file sets both, the config check fails.** A file that holds a key must
not go into git.

### 5.2 Precedence

```
built-in defaults  <  renfield.toml  <  CLI flag or function argument
```

Each layer overrides 1 key at a time. A `--model` flag does not drop the
`effort` of the file.

### 5.3 Ranges

| Key | Range | Default |
|---|---|---|
| `kind` | `subscription`, `anthropic-api`, `openrouter` | `subscription` |
| `effort` | `low`, `medium`, `high`, `xhigh`, `max` | `high` |
| `timeout_min` | 1 to 240 | 20 |
| `max_usd` | 0.01 to 1000, or absent | absent |
| `retries` | 0 to 2 | 2 |
| `name` | 1 to 64 characters of `a-z`, `0-9`, `-`, `_`, `.` | none |

A value outside its range is a config error. **The message names the key, the
range, and the value.** A type check is not a range check.

### 5.4 The paths

```python
@dataclass
class Paths:
    run_dir: Path
    prompt: Path         # relative to run_dir
    transcript: Path     # relative to run_dir
    artifacts: Path      # relative to run_dir
    record: Path         # relative to run_dir
```

Each value accepts 2 placeholders:

| Placeholder | Value |
|---|---|
| `{step}` | The last part of `step.name` |
| `{stamp}` | The start time of the call, as `2026-10-12T14-03-51` |

**An unknown placeholder is a config error, and not an empty string.** A path
of `runs/{stepp}` must fail at the check, and not write a folder named
`runs/{stepp}`.

`outputs` names are relative to `artifacts`. The default layout is:

```
runs/2026-10-12T14-03-51-review/
  prompts/review.md
  transcripts/review.jsonl
  artifacts/verdict.json
  record.json
```

---

## 6. The prompt template

The template is 1 text file. Renfield fills it with `string.Template`, which
reads `$name` and `${name}`.

**A missing value raises an error. It does not write an empty string.** A prompt
that lost a section is worse than a call that did not start.

Renfield adds 1 placeholder of its own: `$invoke_skills`. It holds 1 line for
each skill of the step, as `/<invoke>`.

**A `$` of the template that is not a placeholder must be written `$$`.** This
is a trap for a prompt that holds shell text.

**A value is text, and Renfield reads no file for it.** `--value plan=docs/plan.md`
puts the 14 characters `docs/plan.md` into the prompt. The agent then reads that
file with its own tools. This keeps a large input out of the prompt, and it lets
the agent read only the parts that it needs.

---

## 7. Outputs

`outputs` names each file that the agent must write, relative to `artifacts`.
`schemas` gives a JSON schema path for a name.

For each name, Renfield checks 3 things, in this order:

1. The file is there.
2. The file holds valid JSON, when a schema names it.
3. The data matches the schema.

A failure gives `outputs_valid = False` and a message that names the place in
the file:

```
verdict.json: findings.2.severity: 'blocker' is not one of ['high', 'medium', 'low']
```

**Renfield checks the outputs even when the step failed.** A rate limit can
arrive after the agent wrote a complete file, and `outputs_valid` is then true
beside a failed status. The caller decides whether to use that file.

---

## 8. Failures, retries, and exit codes

### 8.1 The classes

| Class | From | Retry? |
|---|---|---|
| `auth` | `api_error_status` 401 or 403, or the text holds `not logged in` or `/login` | no |
| `rate_limited` | status 429, or the text holds `session limit` or `usage limit` | no |
| `budget` | `subtype` is `error_max_budget_usd`, or `terminal_reason` is `budget_exhausted` | no |
| `transient` | status 500 or higher, or no other class matches | **yes** |
| `timeout` | The child passed `timeout_min` | no |
| `invalid_output` | Section 7 | no |

**The classifier reads `is_error` first.** A result event with `is_error: false`
has no class, whatever its subtype says. A result event with `is_error: true`
and `subtype: "success"` is a failure, and this is the measured case that a
`subtype` reader calls a success.

### 8.2 The retry

Only `transient` retries. The waits are 30 s and 120 s, so a step makes 3
attempts at most. `retries = 0` makes 1 attempt.

**The cost of each attempt adds up in 1 record.** A step that failed 3 times
reports the sum, and `attempts = 3`.

### 8.3 The timeout

At `timeout_min`, Renfield sends SIGINT to the **process group** of the child,
and SIGKILL 15 seconds later.

The group matters, because the child starts children of its own. A signal to
the child alone leaves `rustc`, `cargo`, or a subagent to run.

**SIGINT gives a cost and SIGKILL does not.** A child that gets SIGINT stops
after about 0.2 s and writes a result event with a real `total_cost_usd`. The
`usage` of that event holds zeros, so the token counts are lost.

### 8.4 The exit codes of the CLI

| Exit | Meaning |
|---|---|
| 0 | The step finished, and each named output passed its schema |
| 1 | Config error, or a value outside its range |
| 4 | The step failed: `auth`, `rate_limited`, `budget`, `transient`, or `timeout` |
| 5 | The step finished, and an output is missing or fails its schema |
| 130 | Ctrl-C |

**Exit 4 and exit 5 must stay apart.** A caller retries a 4. A caller must never
retry a 5, because a 5 says that the prompt is wrong, and the next call writes
the same bad file.

---

## 9. Cost: what the numbers mean

**Claude Code prices every call at Anthropic rates, whatever vendor served it.**

| Kind | `cost_estimated` | What `cost_usd` is |
|---|---|---|
| `anthropic-api` | false | The price |
| `subscription` | true | What the same work costs through the API |
| `openrouter` | true | An Anthropic price for another vendor's work |

Measured on 2026-09-16: a call on `meta-llama/llama-3.1-8b-instruct` reported
0.3141 USD. OpenRouter charges about 0.002 USD for it. A DeepSeek run reported
6.16 USD.

**2 consequences:**

1. With `openrouter`, `max_usd` is a turn governor in disguise. It is not a
   limit on money. Set it high, and set it on purpose.
2. A reader must never add a `cost_usd` with `cost_estimated: true` to an
   invoice.

`cost_known` is false when the call was killed and wrote no result event. The
cost is then 0.0, and nobody measured it. `unknown_usd` holds `max_usd` for that
case: the largest value that the call could have cost.

**A step with no `max_usd` has no such bound.** `unknown_usd` is then null, and
the record says that the cost is unknown and that no limit held it. A caller
that adds up a budget must read `cost_known` before it reads `cost_usd`.

---

## 10. The CLI

```sh
renfield run \
  --template prompts/review.md \
  --value plan=docs/plan.md \
  --value spec=docs/spec.md \
  --output verdict.json \
  --schema verdict.json=schemas/verdict.schema.json \
  --workdir . \
  --config renfield.toml \
  --name review \
  --model deepseek/deepseek-v4.1-flash
```

| Flag | Meaning |
|---|---|
| `--template PATH` | Required. The prompt template. |
| `--value k=v` | Repeatable. 1 placeholder value. |
| `--values PATH` | A JSON file of placeholder values. |
| `--output NAME` | Repeatable. A file the agent must write. |
| `--schema NAME=PATH` | Repeatable. A JSON schema for an output. |
| `--workdir PATH` | The working directory of the child. Default: the current folder. |
| `--config PATH` | The TOML file. Default: `renfield.toml`, when it is there. |
| `--name NAME` | The step name. Default: the stem of the template. |
| `--run-dir`, `--prompt`, `--transcript`, `--artifacts`, `--record` | Override 1 path of section 5.4. |
| `--model`, `--effort`, `--timeout-min`, `--max-usd`, `--retries` | Override 1 step key. |
| `--provider`, `--api-key-env` | Override the provider. |
| `--render-only` | Fill the template, write it, and stop. 0 USD. |

`renfield run --render-only` is the way to read the exact prompt before a call
costs money.

### 10.1 What goes to the console

Renfield writes 1 progress line for each event of interest: a tool call with its
first argument, a turn, and the result. The last line names the record:

```
review: deepseek/deepseek-v4.1-flash, effort high, limit 6.0 USD
  Read plan.md
  Read phase.py
  Bash grep -rn "run_step" src
  Write verdict.json
review: ok, 2 attempts, 41 turns, 318.2 s, 6.16 USD (estimated)
record: runs/2026-10-12T14-03-51-review/record.json
```

**The calling agent reads the record file, and not this output.** The last line
tells it where the file is.

---

## 11. Testing

Each test runs against a **fake `claude` program**, and the suite needs no
network and no money.

The helper ships as `renfield.testing.fake_claude`. It writes a small Python
program that:

- records its `argv`, its environment, its working directory, its pid, and its
  standard input to a JSON file;
- writes any files that the test names, as an agent writes its output;
- writes a `stream-json` text that the test gives;
- sleeps, so that a test can drive the timeout;
- traps SIGINT, so that a test can drive the escalation to SIGKILL.

A test of the package, and a test of a prompt in a project that uses the
package, both use this helper.

**A timeout test must assert the exit code, and not only a flag.** A test that
asserts `timed_out` alone cannot fail, because the timeout sets that flag before
the escalation to SIGKILL. The assertion is `exit_code == -9`.

---

## 12. Caution: the child runs with your rights

**Renfield starts an agent with `--dangerously-skip-permissions`.** The agent
can run shell commands. The working directory is the material of the task, and
a file of that directory can hold text that is written for an agent to read.

Use Renfield only on material that you trust. A container is a later change,
and the path layout does not change for it.

---

## 13. Repository layout

```
renfield/
  pyproject.toml
  README.md
  docs/design.md              this document
  src/renfield/
    __init__.py               run_step, Step, Provider, Paths, StepRecord
    step.py                   run_step, the retry, the timeout
    provider.py               the environment of the child
    stream.py                 the stream-json reader and the failure classes
    config.py                 the file, the precedence, the ranges
    paths.py                  the 4 paths and the placeholders
    outputs.py                the output checks
    record.py                 the record file
    cli.py                    renfield run
    testing.py                fake_claude
  tests/
```

---

## 14. What this takes from Skarp, and what it leaves

| Taken | Lines | Change |
|---|---|---|
| `common/llm.py` | 370 | `StepConfig` becomes `Step`. The run folder becomes `Paths`. |
| `common/stream.py` | 205 | No change of behaviour. |
| `common/provider.py` | 68 | `base_url` becomes a field. |
| `common/record.py` | 130 | The Skarp output shape goes. The step record and the log stay. |
| `common/outputs.py` | 47 | The 3 hard-coded phase schemas go. A schema per output name arrives. |
| `tests/test_llm.py` `fake_claude` | 30 | It becomes public. |

Left in Skarp: `fetch.py`, `build.py`, `workspace.py`, `runs.py`, each phase,
and every Skarp configuration key.

**Skarp does not have to adopt Renfield.** The 2 copies may differ. The day
Skarp adopts it, Skarp deletes 6 files and gains a dependency. That day is a
separate decision, and this document does not make it.

---

## 15. Open items

1. **The name on PyPI is not checked.** If Renfield gets published, check
   `renfield` first. An install from git needs no check.
2. **A turn limit is not designed.** `--max-budget-usd` is the only limit, and
   section 9 says what it measures with `openrouter`. If Claude Code accepts a
   turn limit, measure it, and then give it a range.
3. **POSIX only.** `os.killpg` and the process group rule of section 8.3 do not
   work on Windows.
4. **The caller holds the concurrency.** Renfield runs 1 child. 2 calls of
   `run_step` in 1 process are not tested.
