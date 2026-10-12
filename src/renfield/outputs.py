"""The checks of the files that the agent had to write.

A step that failed can still have written a good file. A rate limit or a
timeout can arrive after the work. `run_step` calls this function in that
case too, so that finished work is visible in the record.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema
from jsonschema.exceptions import best_match


def check_outputs(
    artifacts: Path,
    outputs: Sequence[str],
    schemas: Mapping[str, Path],
) -> tuple[bool, str | None]:
    """Say whether each output is there and correct, and why not."""
    reason = _first_problem(Path(artifacts), outputs, schemas)
    return (reason is None, reason)


def _first_problem(
    artifacts: Path, outputs: Sequence[str], schemas: Mapping[str, Path]
) -> str | None:
    extra = [name for name in schemas if name not in outputs]
    if extra:
        return (
            f"the schema list names {extra[0]!r}, and that name is not an output"
        )

    for name in outputs:
        path = artifacts / name
        if not path.is_file():
            return f"the agent did not write {name}"
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as error:
            return f"{name} cannot be read: {error}"
        if not text:
            return f"{name} is empty"

        if path.suffix != ".json":
            continue
        try:
            data = json.loads(text)
        except (ValueError, RecursionError) as error:
            return f"{name} is not valid JSON: {error}"

        schema_path = schemas.get(name)
        if schema_path is None:
            continue
        try:
            schema = _schema(str(schema_path))
        except (OSError, ValueError, RecursionError) as error:
            # ValueError covers UnicodeDecodeError and JSONDecodeError, which
            # the earlier tuple named one at a time. Measured: a schema file
            # of "1"*5000 raises a plain ValueError over the 4300-digit
            # limit, and one of "["*100000 raises RecursionError.
            return f"the schema {schema_path} cannot be read: {error}"

        try:
            problem = _validate(data, schema)
        except Exception as error:
            # A malformed schema raises from inside jsonschema, and the type
            # varies: measured UnknownType, AttributeError and a referencing
            # error from 4 different bad schemas. This function must return a
            # reason, so the guard is wide and the message names the class.
            return (
                f"the schema {schema_path} is not usable: "
                f"{error.__class__.__name__}: {error}"
            )
        if problem is not None:
            return f"{name}: {problem}"
    return None


def _schema(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _validate(data: Any, schema: dict) -> str | None:
    """Give the reason the data does not match, with the place in the file."""
    validator = jsonschema.Draft202012Validator(schema)
    error = best_match(validator.iter_errors(data))
    if error is None:
        return None
    place = ".".join(str(part) for part in error.absolute_path)
    return f"{place}: {error.message}" if place else error.message
