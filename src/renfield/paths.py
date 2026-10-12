"""The 4 paths of 1 run, and the 2 placeholders of a path.

`Paths` holds what a person wrote, with the placeholders still in it.
`RunPaths` holds finished paths. A function that takes `RunPaths` cannot
receive a template by mistake.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from string import Formatter

STAMP_FORMAT = "%Y-%m-%dT%H-%M-%S"
PLACEHOLDERS = ("step", "stamp")

# Each key below `run_dir` is relative to it.
RELATIVE = ("prompt", "transcript", "artifacts", "record")


class PathError(Exception):
    """A path of the configuration is not usable."""


@dataclass
class Paths:
    """The path templates. Each value accepts {step} and {stamp}."""

    run_dir: str = "runs/{stamp}-{step}"
    prompt: str = "prompts/{step}.md"
    transcript: str = "transcripts/{step}.jsonl"
    artifacts: str = "artifacts"
    record: str = "record.json"


@dataclass
class RunPaths:
    """The finished paths of 1 run."""

    run_dir: Path
    prompt: Path
    transcript: Path
    artifacts: Path
    record: Path


def render(paths: Paths, *, step: str, stamp: str | None = None) -> RunPaths:
    """Fill the placeholders of each path, and give the finished paths.

    `step` keeps its last part only, so `review.deep` gives `deep`.
    """
    short = step.rsplit(".", 1)[-1]
    values = {
        "step": short,
        "stamp": stamp if stamp is not None else datetime.now().strftime(STAMP_FORMAT),
    }

    filled = {}
    for key in ("run_dir", *RELATIVE):
        template = getattr(paths, key)
        _check(key, template)
        try:
            filled[key] = template.format(**values)
        except (ValueError, KeyError, IndexError) as error:
            # `_check` passes a template whose placeholder names are known,
            # and `.format` can still fail on a conversion or a format spec.
            # Measured: "{step!x}" and "{step:d}" both raise ValueError.
            # Task 9's CLI catches PathError only.
            raise PathError(
                f"{key}: the value {template!r} is not a usable path: {error}"
            ) from error

    for key in RELATIVE:
        if Path(filled[key]).is_absolute():
            raise PathError(
                f"{key}: the value {filled[key]!r} is an absolute path, and "
                f"{key} is relative to run_dir"
            )

    run_dir = Path(filled["run_dir"])
    return RunPaths(
        run_dir=run_dir,
        prompt=run_dir / filled["prompt"],
        transcript=run_dir / filled["transcript"],
        artifacts=run_dir / filled["artifacts"],
        record=run_dir / filled["record"],
    )


def _check(key: str, template: str) -> None:
    """Stop a template that names a placeholder that does not exist."""
    try:
        names = [
            name for _, name, _, _ in Formatter().parse(template) if name is not None
        ]
    except ValueError as error:
        # `Formatter().parse` raises ValueError for an unbalanced brace. The
        # CLI of task 9 catches PathError, so a bare ValueError would reach a
        # person as a traceback.
        raise PathError(
            f"{key}: the value {template!r} is not a usable path: {error}"
        ) from error
    unknown = [name for name in names if name not in PLACEHOLDERS]
    if unknown:
        raise PathError(
            f"{key}: the placeholder {unknown[0]!r} does not exist. "
            f"The placeholders are {', '.join('{%s}' % p for p in PLACEHOLDERS)}."
        )


def make_dirs(run: RunPaths) -> None:
    """Build the folder of each path. Write no file."""
    run.artifacts.mkdir(parents=True, exist_ok=True)
    for path in (run.prompt, run.transcript, run.record):
        path.parent.mkdir(parents=True, exist_ok=True)
