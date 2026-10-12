"""The `renfield run` command."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from renfield.config import ConfigError, Skill, load
from renfield.paths import PathError, make_dirs, render as render_paths
from renfield.provider import ProviderError
from renfield.record import summary_line
from renfield.step import PromptError, render_prompt, run_step

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_STEP = 4
EXIT_OUTPUT = 5
EXIT_INTERRUPT = 130

# A failure of the output is the caller's prompt, and not the provider. It
# gets its own code, because a caller must not retry it.
OUTPUT_CLASS = "invalid_output"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="renfield", description="Run 1 AI agent, and report what it did"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run 1 agent step")

    run.add_argument("--template", type=Path, required=True, help="the prompt template")
    run.add_argument("--value", action="append", default=[], metavar="KEY=VALUE",
                     help="1 placeholder value. Repeatable.")
    run.add_argument("--values", type=Path, help="a JSON file of placeholder values")
    run.add_argument("--output", action="append", default=[], metavar="NAME",
                     help="a file the agent must write. Repeatable.")
    run.add_argument("--schema", action="append", default=[], metavar="NAME=PATH",
                     help="a JSON schema for an output. Repeatable.")
    run.add_argument("--workdir", type=Path, default=Path("."),
                     help="the working directory of the child")
    run.add_argument("--config", type=Path, help="the TOML file")
    run.add_argument("--config-dir", type=Path,
                     help="a CLAUDE_CONFIG_DIR for the child")
    run.add_argument("--name", help="the step name. Default: the stem of the template.")
    run.add_argument("--executable", default="claude", help="the agent program")
    run.add_argument("--add-dir", action="append", default=[], type=Path)
    run.add_argument("--skill", action="append", default=[], metavar="PLUGIN[=INVOKE]")
    for key in ("run-dir", "prompt", "transcript", "artifacts", "record"):
        run.add_argument(f"--{key}", help=f"override the {key.replace('-', '_')} path")
    run.add_argument("--provider", dest="kind")
    run.add_argument("--api-key-env")
    run.add_argument("--model")
    run.add_argument("--effort")
    run.add_argument("--timeout-min", type=int)
    run.add_argument("--max-usd", type=float)
    run.add_argument("--retries", type=int)
    run.add_argument("--render-only", action="store_true",
                     help="write the prompt and stop. 0 USD.")
    run.set_defaults(handler=_run)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (ConfigError, PathError, PromptError, ProviderError) as error:
        print(f"renfield: {error}", file=sys.stderr)
        return EXIT_CONFIG
    except KeyboardInterrupt:
        print("\nCtrl-C: the step stopped.", file=sys.stderr)
        return EXIT_INTERRUPT


def _run(args) -> int:
    default_config = Path("renfield.toml")
    config_path = args.config
    if config_path is None and default_config.is_file():
        config_path = default_config

    overrides = {
        "name": args.name or args.template.stem,
        "kind": args.kind,
        "api_key_env": args.api_key_env,
        "model": args.model,
        "effort": args.effort,
        "timeout_min": args.timeout_min,
        "max_usd": args.max_usd,
        "retries": args.retries,
        "run_dir": args.run_dir,
        "prompt": args.prompt,
        "transcript": args.transcript,
        "artifacts": args.artifacts,
        "record": args.record,
        "add_dirs": args.add_dir or None,
        "skills": _skills(args.skill) or None,
    }
    settings = load(config_path, overrides=overrides, env=os.environ)
    values = _values(args.values, args.value)
    schemas = _schemas(args.schema)

    if args.render_only:
        run = render_paths(settings.paths, step=settings.step.name)
        make_dirs(run)
        text = render_prompt(
            args.template.read_text(encoding="utf-8"), values, settings.step.skills
        )
        run.prompt.write_text(text, encoding="utf-8")
        print(f"prompt: {run.prompt}")
        return EXIT_OK

    limit = (
        f"limit {settings.step.max_usd} USD"
        if settings.step.max_usd is not None
        else "no cost limit"
    )
    print(
        f"{settings.step.name}: {settings.step.model}, "
        f"effort {settings.step.effort}, {limit}"
    )
    record = run_step(
        settings.step,
        settings.provider,
        workdir=args.workdir,
        template=args.template,
        values=values,
        paths=settings.paths,
        outputs=args.output,
        schemas=schemas,
        executable=args.executable,
        config_dir=args.config_dir,
        on_line=lambda line: print(f"  {line}"),
    )
    print(summary_line(record))
    if record.error:
        print(f"renfield: {record.error}", file=sys.stderr)
    print(f"record: {Path(record.run_dir) / record.record}")

    if record.status == "ok":
        return EXIT_OK
    return EXIT_OUTPUT if record.error_class == OUTPUT_CLASS else EXIT_STEP


def _values(path: Path | None, pairs: Sequence[str]) -> dict[str, str]:
    """Read the values of the file, then the values of the flags."""
    values: dict[str, str] = {}
    if path is not None:
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict):
            raise ConfigError(f"{path} must hold a JSON object")
        values.update({str(key): str(value) for key, value in data.items()})
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ConfigError(
                f"--value {pair!r} has no '=' sign. Write --value key=value."
            )
        values[key] = value
    return values


def _schemas(pairs: Sequence[str]) -> dict[str, Path]:
    schemas: dict[str, Path] = {}
    for pair in pairs:
        name, sep, path = pair.partition("=")
        if not sep or not name or not path:
            raise ConfigError(
                f"--schema {pair!r} is not NAME=PATH. "
                f"Write --schema verdict.json=schemas/verdict.schema.json."
            )
        schemas[name] = Path(path)
    return schemas


def _skills(pairs: Sequence[str]) -> list[Skill]:
    skills = []
    for pair in pairs:
        plugin, _, invoke = pair.partition("=")
        skills.append(Skill(plugin=Path(plugin), invoke=invoke or None))
    return skills


if __name__ == "__main__":
    raise SystemExit(main())
