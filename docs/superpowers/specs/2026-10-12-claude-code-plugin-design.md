# The Renfield plugin for Claude Code: design

Date: 2026-10-12. Status: approved in conversation, waiting for review of this
file.

## 1. Purpose

The plugin lets Claude Code use Renfield as a second kind of subagent. The
first use on a kind of task is a comparison. The same task runs at the same
time on a native Claude Code subagent and on Renfield. The operator compares
the 2 results and decides whether to use Renfield for that kind of task.

Renfield usually runs a model that costs less than the native model. The
comparison is about the quality of the work. The operator judges the quality.
That judgment is outside the scope of Renfield and of the plugin.

### 1.1 Users

The operator of the plugin and other people. Each user installs the plugin
from the marketplace `jecikpo-marketplace`.

### 1.2 Rules from the operator

1. Claude decides from the skill description when Renfield applies.
2. **Claude always asks the operator before it starts Renfield.**
3. The first use on a kind of task is a comparison with a native subagent.
4. After the decision to switch, later tasks of that kind use Renfield only.
   Claude still asks before each run.
5. Each side shows only the values that it reports itself. The plugin adds no
   estimate of cost.
6. Claude gives a short list of the differences. Claude does not pick a
   winner.
7. Renfield does not change for this plugin. The plugin calls `renfield run`
   as it is.

## 2. Decisions

| Item | Decision | Rejected options |
|---|---|---|
| Package form | A plugin in `jecikpo-marketplace` | A skill in `~/.claude/skills` (cannot be shared); an MCP server (a run is longer than the timeout of a tool call) |
| Plugin content | 1 skill, instructions only | A slash command (drift from the skill); a helper script (it cannot start the native subagent) |
| Install of the CLI | `uv tool install git+https://github.com/jecikpo/renfield` | PyPI; a copy of the source in the plugin |
| Tasks in a comparison | All tasks. Each side runs in its own git worktree. | Read-only tasks only |
| Cost values | As each side reports them | A USD estimate for the native side; a dependency on `subagent-usage` |
| Decision record | `.claude/renfield.md` in the project, in git | The memory of Claude Code; no record |
| Target harness | Claude Code only | Codex |

## 3. The files

### 3.1 In `jecikpo-marketplace`

```
.claude-plugin/marketplace.json   1 new entry: renfield, version 0.1.0
plugins/renfield/
  .claude-plugin/plugin.json      name, version 0.1.0, description, author, license
  README.md                       the install steps and the 2 prerequisites
  skills/renfield/
    SKILL.md                      when to offer Renfield, and the procedure
    reference.md                  the flags, the exit codes, the record fields
  evals/                          the eval cases of section 8.2, and the fake agent
```

`SKILL.md` holds the procedure of section 5 and the failure rules of section 7.
`reference.md` holds the facts that Claude needs only when it starts a run.
Claude reads `reference.md` at that time.

### 3.2 In the Renfield repository

1. A GitHub remote, `github.com/jecikpo/renfield`. **The operator adds the
   remote and pushes, because this publishes the code.**
2. `README.md` gets the install command of section 2.

### 3.3 The setup of a user

1. Run `uv tool install git+https://github.com/jecikpo/renfield`.
2. Install the plugin from `jecikpo-marketplace` in Claude Code.
3. Write `renfield.toml` in the project. Use `api_key_env`. Do not use
   `api_key`.

## 4. Facts from the code that the skill must handle

1. `run_dir` is relative to the folder where `renfield` starts. It is not
   relative to `--workdir`. The skill passes `--run-dir` as an absolute path.
2. The agent does not get the `artifacts` path automatically. The skill
   passes it as `--value artifacts=<absolute path>`. The prompt tells the agent
   to write each output there. The native subagent gets the same prompt with
   its own folder.
3. Renfield adds `--add-dir <artifacts>` to the child only when that folder
   exists (`step.py:222`). The skill makes the folder before the run.
4. `outputs` names are relative to `artifacts` (`docs/design.md`, section 7).
5. A `$` in the template that is not a placeholder must be written `$$`
   (`docs/design.md`, section 6).
6. **Renfield starts the child with `--dangerously-skip-permissions`**
   (`docs/design.md`, section 12). Each question to the operator says this.

## 5. The procedure

### 5.1 When the skill applies

Claude plans to give a task to a subagent, and the `renfield` command is
installed. Claude then reads `.claude/renfield.md` and looks for the kind of
the task.

A kind is a short name of the form `[a-z0-9-]+`, for example `code-review`.
Claude proposes the name. The operator confirms it.

| Decision in the file | What Claude does |
|---|---|
| None | Ask: "compare", "native only", or "Renfield only". |
| `switch` | Ask: "run on Renfield?" On yes, do a direct run (section 5.3). |
| `stay` | Use a native subagent. Do not offer Renfield. |

Each question names the model, `max_usd`, `timeout_min`, and the warning of
section 4, item 6.

### 5.2 The comparison

1. Write the task prompt 1 time, as a template with a `$artifacts`
   placeholder. Write each other `$` as `$$`.
2. Run `renfield run --render-only`. This costs 0 USD and checks the template.
3. If the working tree has uncommitted changes, tell the operator that neither
   side sees them.
4. Make a worktree for Renfield from `HEAD`, on the branch
   `renfield/<stamp>-<kind>`.
5. Start the 2 sides at the same time:
   - The native subagent: the Agent tool, `isolation: "worktree"`, in the
     background.
   - Renfield: the Bash tool, `run_in_background`, with `--workdir`, an
     absolute `--run-dir`, and `--value artifacts=<path>`.
6. When both sides end, show 1 table with these rows for each side: the
   status, the exit code, `outputs_valid`, the turns, the time, the cost or the
   tokens as the side reports them, the `git diff --stat` of the worktree, and
   the paths of the outputs.
7. Give a short list of the differences.
8. Ask the operator 2 questions: which result to keep, and `switch` or `stay`
   for this kind.
9. Write the decision row to `.claude/renfield.md` (section 6).
10. Remove the worktree of the other side only after the operator confirms.

The Bash tool stops a foreground command after 10 minutes. The default
`timeout_min` is 20. For this reason, step 5 uses `run_in_background`.

### 5.3 A direct run

Do steps 1, 2, and 5 of section 5.2, for the Renfield side only. Then show the
values of `record.json`.

### 5.4 The run folders

The run folders go to `.renfield/runs/<stamp>-<kind>/` in the project. The
Renfield worktree goes to `.renfield/worktrees/<stamp>-<kind>/`. The skill
checks that `.gitignore` holds `.renfield/`. If it does not, the skill asks
before it adds the line.

## 6. The decision file

`.claude/renfield.md`:

```markdown
# Renfield decisions

| Kind | Decision | Date | Model | Comparison run |
|---|---|---|---|---|
| code-review | switch | 2026-10-12 | deepseek/deepseek-v4.1-flash | .renfield/runs/2026-10-12T14-03-51-code-review |
```

Rules:

1. The file has 1 row for each kind. A new decision for a kind replaces its
   row.
2. The file goes into git. The run folder does not. The link to the run is
   local to 1 machine. The model and the date are valid for the team.
3. If the model in `renfield.toml` is not the model of the row, the decision
   does not apply. Claude tells the operator and offers a new comparison.

## 7. Failures

### 7.1 The exit codes of Renfield

| Exit code | Meaning | What Claude does |
|---|---|---|
| 0 | ok | Continue. |
| 1 | config error | Show the message. Do not retry. Ask the operator to fix `renfield.toml`. |
| 4 | the step failed | Show the failure class. Offer 1 retry. Ask first, because a retry costs money. |
| 5 | an output is missing or bad | Show the message. **Never retry.** |
| 130 | stopped by Ctrl-C | Report it. Do not retry. |

### 7.2 Other failures

| Condition | What Claude does |
|---|---|
| `renfield` is not installed | Show the `uv tool install` command and stop. |
| The project is not a git repository | A comparison is not possible. Offer "native only" or "Renfield only". |
| 1 side of a comparison fails | Show the table. A failed side is a valid result for the decision. |

## 8. Tests

The plugin holds no code. The tests check the manifests and the behavior of
Claude.

### 8.1 The manifests

Run `claude plugin validate` on the plugin folder and on the marketplace.
Cost: 0 USD.

### 8.2 The behavior rules

Run `claude plugin eval` with 3 cases:

1. No decision in the file. Claude asks before any `renfield run`, and the
   question holds the permissions warning.
2. Decision `stay`. Claude does not offer Renfield.
3. Decision `switch`. Claude asks, and runs Renfield only after a yes.

Each case passes `--executable` with the fake agent, so the Renfield side
costs 0 USD. The Claude sessions of the eval use tokens of the account.

The fake agent is a small wrapper in `evals/`. It calls
`renfield.testing.fake_claude` with the stream of
`tests/fixtures/stream/success.jsonl` and writes 1 program to disk.

**Mutation check (AGENTS.md, rule 5).** Remove the "ask first" rule from
`SKILL.md`. Run case 1. Case 1 must fail.

### 8.3 1 comparison by hand

Run 1 full comparison in a scratch git repository, with the fake agent. This
checks the worktrees, the background runs, the table, and the decision file.
The Renfield side costs 0 USD. The native side uses tokens.

### 8.4 The first paid run

Run 1 small real task on a model with a low price, with `max_usd = 0.50`.
Write the measured values and the date into `docs/design.md`. This closes the
open item "Renfield has never run a real agent" of `AGENTS.md`.

## 9. Out of scope

- A slash command. It can come later as a separate change.
- Support for Codex.
- An estimate of cost for the native side.
- A judgment of quality by Claude.
