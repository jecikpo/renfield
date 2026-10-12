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
| [Claude Code](https://claude.com/claude-code) | measured with 2.1.285 | the agent is 1 `claude -p` child process |

You need 1 provider. The provider is a Claude subscription, an Anthropic API
key, or an OpenRouter key.

## Install

```sh
uv add git+https://github.com/<you>/renfield
```

## Use it from the command line

```sh
renfield run \
  --template prompts/review.md \
  --value plan=docs/plan.md \
  --output verdict.json \
  --schema verdict.json=schemas/verdict.schema.json \
  --workdir . \
  --model claude-opus-5
```

A value is text. Renfield does not read a file for it. `--value plan=docs/plan.md`
puts those 12 characters into the prompt. The agent reads the file with its own
tools.

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

The order of precedence is: built-in defaults, then this file, then the CLI flag.
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

Claude Code prices every call at Anthropic rates. This is true for each vendor.
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
