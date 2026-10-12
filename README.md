# Renfield

Renfield runs 1 AI agent as a child process, with a prompt template. It
reports what the agent did and what the agent wrote.

You decide what the agent must do. Renfield starts the agent and watches it.
Renfield kills the agent if it runs too long. Renfield checks the files that
the agent wrote, and gives you 1 record.

The design is in [`docs/design.md`](docs/design.md).

## Warning

**Renfield starts the agent with the permission checks off.** The agent can run
shell commands with your rights. The working directory is the material of the
task. A file in that directory can hold text that is written for an agent to
read.

Use Renfield only on material that you trust.

## Requirements

| Program | Version | Why |
|---|---|---|
| Python | 3.11 or later | Renfield |
| [Claude Code](https://claude.com/claude-code) | exercised with 2.1.285 | the agent is 1 `claude -p` child process |

You need 1 provider. The provider is a Claude subscription, an Anthropic API
key, or an OpenRouter key.

The tests of the stream reader use events that were recorded from Claude Code
2.1.273.

## Install

```sh
uv add --editable /path/to/renfield
```

Renfield has no published package. If you host this repository,
`uv add git+<the repository URL>` works too.

## Use it from the command line

```sh
renfield run \
  --template prompts/review.md \
  --value plan=docs/plan.md \
  --output verdict.json \
  --schema verdict.json=schemas/verdict.schema.json \
  --workdir . \
  --model opus \
  --config-dir /path/to/a/clean/config
```

A value is text. Renfield does not read a file for it. `--value plan=docs/plan.md`
puts those 12 characters into the prompt. The agent reads the file with its own
tools.

`--config-dir` sets `CLAUDE_CONFIG_DIR` for the agent. Use it for an independent
second opinion. It keeps your own `~/.claude` away from the agent.

**Read the prompt before you pay for it.** This command costs 0 USD:

```sh
renfield run --template prompts/review.md --value plan=docs/plan.md --render-only
```

## Use it from Python

```python
from pathlib import Path
from renfield import Paths, Provider, Step, run_step

record = run_step(
    Step(name="review", model="claude-opus-5", effort="high", timeout_min=20),
    Provider(kind="subscription"),
    workdir=Path("."),
    template=Path("prompts/review.md"),
    values={"plan": "docs/plan.md"},
    paths=Paths(),
    outputs=["verdict.json"],
    schemas={"verdict.json": Path("schemas/verdict.schema.json")},
)
print(record.status, record.cost_usd, record.outputs_valid)
```

## Configuration

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

The order of precedence is: built-in defaults, then `[step]`, then the selected
`[models.<name>]` entry, then the CLI flag. `--model NAME` selects the entry.

The agent reads your own `~/.claude` unless you set `--config-dir` (or
`config_dir` in Python). That folder holds your global `CLAUDE.md`, your user
hooks, your user agents, and your memory files. The flag `--setting-sources ""`,
which Renfield always passes, does not cover them.

`timeout_min` is the limit of 1 attempt, not of the whole step. With
`--timeout-min 20 --retries 2`, a step can run for 62.5 minutes: 3 attempts and
150 seconds of waits. Each attempt can take up to 15 more seconds to stop.
**Do not commit `renfield.toml`.** It can hold a key.

## What 1 run writes

```
runs/2026-10-12T14-03-51-review/
  prompts/review.md          the prompt, as sent
  transcripts/review.jsonl   every event of the agent
  artifacts/verdict.json     what the agent wrote
  record.json                status, cost, tokens, tool calls
```

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | The step finished, and each output passed its schema |
| 1 | Config error, or a value outside its range |
| 4 | The step failed: auth, rate limit, budget, transient, or timeout |
| 5 | The step finished, and an output is missing or fails its schema |
| 130 | Ctrl-C |

**Exit 4 and exit 5 are not the same.** Retry a 4. Never retry a 5: it says the
prompt is wrong, and the next call writes the same bad file.

## The cost is an estimate, except with an API key

Claude Code uses Anthropic prices for each vendor.
A measured call on `meta-llama/llama-3.1-8b-instruct` reported 0.3141 USD.
OpenRouter charges about 0.002 USD for it.

`record.json` has the key `cost_estimated`. **With `openrouter`, `max_usd` limits
the number of turns. It is not a spend limit.** Set it high, and set it on
purpose.

## Development

```sh
uv run pytest        # no network, no money
```

Each test runs against `renfield.testing.fake_claude`, a fake agent program.
Your project can use it to test your prompts for 0 USD.
