"""The input file, the precedence, and the range of each key.

The precedence is: built-in defaults, then the file, then the call.

Each numeric and each enumerated key has a range, checked here, with a
message that names the key, the range, and the value. A type check is not a
range check: `timeout_min = 0` passes a type check and kills the child at
once.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from renfield.paths import Paths
from renfield.provider import KINDS, Provider

EFFORTS = ("low", "medium", "high", "xhigh", "max")
TIMEOUT_RANGE = (1, 240)
MAX_USD_RANGE = (0.01, 1000.0)
RETRIES_RANGE = (0, 2)
NAME_PATTERN = re.compile(r"^[a-z0-9._-]{1,64}$")

PROVIDER_KEYS = ("kind", "model", "effort", "api_key", "api_key_env", "base_url")
STEP_KEYS = ("timeout_min", "max_usd", "retries")
PATH_KEYS = ("run_dir", "prompt", "transcript", "artifacts", "record")
TABLES = {"provider": PROVIDER_KEYS, "step": STEP_KEYS, "paths": PATH_KEYS}


class ConfigError(Exception):
    """The configuration is not usable."""


@dataclass
class Skill:
    plugin: Path
    invoke: str | None = None


@dataclass
class Step:
    name: str
    model: str
    effort: str = "high"
    timeout_min: int = 20
    max_usd: float | None = None
    retries: int = 2
    add_dirs: list[Path] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)


@dataclass
class Settings:
    provider: Provider
    step: Step
    paths: Paths


def load(
    path: Path | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Read the file, apply the overrides, check each range, and give the settings."""
    data = _read(path)
    given = {key: value for key, value in (overrides or {}).items() if value is not None}
    env = {} if env is None else env

    def pick(table: str, key: str, default: Any = None) -> Any:
        if key in given:
            return given[key]
        return data.get(table, {}).get(key, default)

    # The file cannot set the name: 1 file serves many steps. The CLI passes
    # it, and the default serves a direct call of the library.
    name = given.get("name", "step")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise ConfigError(
            f"name: the value {name!r} is not 1 to 64 characters of a-z, 0-9, "
            f"'-', '_', and '.'"
        )

    model = pick("provider", "model")
    if not model:
        raise ConfigError(
            "model: no value. Set [provider] model in the file, or pass --model."
        )

    kind = _one_of("kind", pick("provider", "kind", "subscription"), KINDS)
    effort = _one_of("effort", pick("provider", "effort", "high"), EFFORTS)
    timeout_min = _in_range(
        "timeout_min", pick("step", "timeout_min", 20), TIMEOUT_RANGE, int
    )
    retries = _in_range("retries", pick("step", "retries", 2), RETRIES_RANGE, int)
    max_usd = pick("step", "max_usd")
    if max_usd is not None:
        max_usd = _in_range("max_usd", max_usd, MAX_USD_RANGE, float)

    provider = Provider(
        kind=kind,
        api_key=_api_key(kind, pick, env),
        base_url=pick("provider", "base_url"),
    )
    step = Step(
        name=name,
        model=str(model),
        effort=effort,
        timeout_min=timeout_min,
        max_usd=max_usd,
        retries=retries,
        add_dirs=[Path(p) for p in given.get("add_dirs", [])],
        skills=list(given.get("skills", [])),
    )
    paths = replace(
        Paths(),
        **{key: str(pick("paths", key)) for key in PATH_KEYS if pick("paths", key)},
    )
    return Settings(provider=provider, step=step, paths=paths)


def _read(path: Path | None) -> dict:
    """Read the TOML file, and stop on an unknown table or an unknown key."""
    if path is None:
        return {}
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"the file {path} is not there")
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error

    for table, values in data.items():
        if table not in TABLES:
            raise ConfigError(
                f"unknown table [{table}]. The tables are "
                f"{', '.join('[%s]' % name for name in TABLES)}."
            )
        if not isinstance(values, dict):
            raise ConfigError(f"[{table}] must be a table")
        for key in values:
            if key not in TABLES[table]:
                raise ConfigError(
                    f"unknown key {key!r} in [{table}]. The keys are "
                    f"{', '.join(TABLES[table])}."
                )
    return data


def _api_key(kind: str, pick, env: Mapping[str, str]) -> str | None:
    literal = pick("provider", "api_key")
    variable = pick("provider", "api_key_env")
    if literal and variable:
        raise ConfigError(
            "api_key and api_key_env are both set. Use 1 of them."
        )
    if literal:
        return str(literal)
    if variable:
        value = env.get(str(variable))
        if not value:
            raise ConfigError(
                f"api_key_env names {variable!r}, and that variable is empty "
                f"or absent"
            )
        return value
    if kind != "subscription":
        raise ConfigError(
            f"the provider kind {kind!r} needs a key. Set api_key_env or api_key."
        )
    return None


def _one_of(key: str, value: Any, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ConfigError(
            f"{key}: the value {value!r} is not one of {', '.join(allowed)}"
        )
    return str(value)


def _in_range(key: str, value: Any, limits: tuple, kind) -> Any:
    low, high = limits
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"{key}: the value {value!r} is not a number. The range is {low} to {high}."
        )
    if not low <= value <= high:
        raise ConfigError(
            f"{key}: the range is {low} to {high}, and the value is {value}"
        )
    if kind is int and value != int(value):
        raise ConfigError(
            f"{key}: the value {value} is not a whole number"
        )
    return kind(value)
