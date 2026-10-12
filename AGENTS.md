# Renfield: working rules

Renfield runs 1 AI agent as a child `claude -p` process. It renders a prompt
template, starts the agent, watches it, checks the files that the agent wrote,
and writes 1 record. The design is in `docs/design.md`. Read the section of a
module before you change that module.

Renfield holds no knowledge of a task. A caller gives the prompt, the working
directory, and the list of outputs.

## Commands

```sh
uv run pytest                          # 205 tests. No LLM, no network, no money.
uv run renfield run --help
uv run renfield run --template T --value k=v --render-only   # 0 USD. It writes the prompt and stops.
```

Each test runs against `renfield.testing.fake_claude`, a fake agent program.
The fake records the exact command and the exact environment that `step.py`
built. Use it for a new test of the child process.

## Documents

- `docs/design.md`: the design. Section 4 is the API, section 8 is the failure
  classes and the exit codes, section 9 is the cost, section 15 is the open
  items.
- `docs/build-plan.md`: the plan of the first build, with the 41 defects that
  the reviews found. Read "What the 41 rows say about this plan" before you
  write a new plan for this package.
- `README.md`: for a person who uses the package.

## Method

1. **Test first.** Write the test, watch it fail for the right reason, then
   write the code.
2. **Measure, do not assume.** A claim about Claude Code or about a cost needs
   a recorded run or a fixture. Write the measured value and its date.
3. **1 change for each commit.**
4. **Each parameter gets a range.** Check the range where the program reads the
   parameter. Give a message that names the key, the range, and the value. A
   type check is not a range check. An example: `timeout_min = 0` passes a type
   check, and it kills the child at once.
5. **Mutate your own test.** Change the line of the source that the test exists
   to protect, and watch the test fail. A test that passes under that mutation
   protects nothing. 4 of the 41 defects of the first build are this.

## 5 facts that you must not break

Each one comes from a measured run. A change that breaks one costs money or
loses the record of money that was already spent.

1. **The child environment starts from an allowlist of 9 names**, and not from
   the environment of the parent (`provider.py`). This keeps the key of the
   parent and each `CLAUDE_CODE_*` variable of a parent session out of the
   child. `env=os.environ` is a defect, and `tests/test_provider.py` holds the
   test.
2. **The failure classifier reads `is_error`.** It never reads `subtype` alone.
   A measured rate limit reports `subtype: "success"` with `is_error: true`.
   See `tests/fixtures/stream/`.
3. **A timeout sends SIGINT to the process group, then SIGKILL after a grace
   period.** SIGINT gives a real `total_cost_usd`. SIGKILL loses it. The child
   starts children of its own, so `os.kill` in place of `os.killpg` leaves a
   paid grandchild alive.
4. **`outputs_valid` is a field of its own, and not a part of `status`.** A step
   that failed can still have written a good file.
5. **Every path out of `run_step` writes the record, including an exception.**
   The caller paid for the attempt. A function that raises where it promised to
   return a value is the defect class of this package: 16 of the 41 defects of
   the first build are this 1 class. Read the `except BaseException` block of
   `step.py` before you change the money path.

**The exit codes are a contract.** 0 ok, 1 config, 4 the step failed, 5 an
output is missing or bad, 2 argparse, 130 Ctrl-C. A caller retries a 4. A
caller must never retry a 5.

## The modules

| Module | What it holds |
|---|---|
| `step.py` | `run_step`, the retry, the timeout. The only module that starts a child process. |
| `provider.py` | the environment of the child, and `base_url` |
| `stream.py` | the stream-json reader and the failure classes |
| `config.py` | the input file, the precedence, and the range of each key |
| `paths.py` | the 4 paths of 1 run, and the 2 placeholders |
| `outputs.py` | the checks of the files that the agent had to write |
| `record.py` | the record file and the console lines |
| `cli.py` | `renfield run` |
| `testing.py` | `fake_claude`, the fake agent program |
| `version.py` | the version. Its own module, so that no import is a cycle. |

## Style

- Documents and console messages: ASD-STE100 (Simplified Technical English).
- Prompt text belongs to the caller. Renfield holds placeholder names only.
- **Do not commit `runs/` or `renfield.toml`.** A run folder holds the material
  of a task, and the input file can hold a key.

## Open work

**2 measured defects wait for a fix.** Each one needs 1 line and 1 test.
`docs/build-plan.md` holds the full row of each one.

1. Defect 40, `step.py:260`. The guard of `Popen` catches
   `FileNotFoundError` and `PermissionError`. Each other start failure is an
   `OSError`, and it reaches the escape handler, which reports `max_usd` as
   unknown spend for a child that never started. The fix is
   `except OSError as error`.
2. Defect 41, `cli.py:156`. `--values` reads the file in the encoding of the
   locale. A UTF-8 file becomes double-encoded text inside a paid prompt, and
   the status still reports `ok`. The fix is `encoding="utf-8"`.

**Renfield has never run a real agent.** Each of the 205 tests uses
`fake_claude`. The first paid call is not yet measured. Write what it reports
into `docs/design.md`, with the date.

`docs/design.md`, section 15, holds the other open items.
