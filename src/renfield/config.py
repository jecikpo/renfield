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
# An entry name has no dot: TOML reads [models.a.b] as the entry a with a
# nested table b.
ENTRY_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")
ENTRY_RULE = "1 to 64 characters of a-z, 0-9, '-', and '_'"

PROVIDER_KEYS = ("kind", "model", "effort", "api_key", "api_key_env", "base_url")
STEP_KEYS = ("timeout_min", "max_usd", "retries")
ENTRY_KEYS = PROVIDER_KEYS + STEP_KEYS
PATH_KEYS = ("run_dir", "prompt", "transcript", "artifacts", "record")
TABLES = {"step": STEP_KEYS, "paths": PATH_KEYS}
TOP_LEVEL = ("default", "models", "step", "paths")
LIMITS = {
    "timeout_min": (TIMEOUT_RANGE, int),
    "max_usd": (MAX_USD_RANGE, float),
    "retries": (RETRIES_RANGE, int),
}
NO_MODEL = "no model: add a [models.<name>] table to renfield.toml"


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
    model_entry: str | None = None

    def __post_init__(self) -> None:
        """Check every key here, so a caller that builds a Step by hand gets
        the same ranges as a caller that reads the file. docs/design.md
        section 5.3 holds the table."""
        if not NAME_PATTERN.fullmatch(str(self.name)):
            raise ConfigError(
                f"name: the value {self.name!r} is not 1 to 64 characters of "
                f"a-z, 0-9, '-', '_', and '.'"
            )
        if not self.model:
            raise ConfigError("model: no value")
        _one_of("effort", self.effort, EFFORTS)
        _in_range("timeout_min", self.timeout_min, TIMEOUT_RANGE, int)
        _in_range("retries", self.retries, RETRIES_RANGE, int)
        if self.max_usd is not None:
            _in_range("max_usd", self.max_usd, MAX_USD_RANGE, float)
        for folder in self.add_dirs:
            if not isinstance(folder, Path):
                raise ConfigError(f"add_dirs: {folder!r} is not a Path")
        for skill in self.skills:
            if not isinstance(skill, Skill):
                raise ConfigError(f"skills: {skill!r} is not a Skill")
        if self.model_entry is not None and not (
            isinstance(self.model_entry, str)
            and ENTRY_PATTERN.fullmatch(self.model_entry)
        ):
            raise ConfigError(
                f"model_entry: the value {self.model_entry!r} is not {ENTRY_RULE}"
            )


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
    resolve_key: bool = True,
) -> Settings:
    """Read the file, select 1 entry, apply the overrides, check each range,
    and give the settings.

    `overrides["model"]` is the name of an entry, and not a model ID.
    `resolve_key=False` does not read the key from the environment: a render
    costs 0 USD and needs no key.
    """
    data = _read(path)
    given = {key: value for key, value in (overrides or {}).items() if value is not None}
    env = {} if env is None else env

    # The file cannot set the name: 1 file serves many steps. The CLI passes
    # it, and the default serves a direct call of the library.
    name = given.get("name", "step")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise ConfigError(
            f"name: the value {name!r} is not 1 to 64 characters of a-z, 0-9, "
            f"'-', '_', and '.'"
        )

    step_table = data.get("step", {})
    for key, value in step_table.items():
        _check_limit(f"step.{key}", key, value)
    entries = data.get("models", {})
    for entry_name, entry in entries.items():
        _check_entry(entry_name, entry)
    selected = _select(entries, data, given.get("model"))
    entry = entries[selected]

    def pick(key: str, default: Any = None) -> Any:
        if key in given:
            return given[key]
        if key in entry:
            return entry[key]
        return step_table.get(key, default)

    effort = _one_of("effort", pick("effort", "high"), EFFORTS)
    timeout_min = _in_range("timeout_min", pick("timeout_min", 20), TIMEOUT_RANGE, int)
    retries = _in_range("retries", pick("retries", 2), RETRIES_RANGE, int)
    max_usd = pick("max_usd")
    if max_usd is not None:
        max_usd = _in_range("max_usd", max_usd, MAX_USD_RANGE, float)

    provider = Provider(
        kind=entry.get("kind", "subscription"),
        api_key=_api_key(f"models.{selected}", entry, env) if resolve_key else None,
        base_url=entry.get("base_url"),
    )
    step = Step(
        name=name,
        model=str(entry["model"]),
        effort=effort,
        timeout_min=timeout_min,
        max_usd=max_usd,
        retries=retries,
        add_dirs=[Path(p) for p in given.get("add_dirs", [])],
        skills=list(given.get("skills", [])),
        model_entry=selected,
    )
    path_table = data.get("paths", {})

    def pick_path(key: str) -> Any:
        return given[key] if key in given else path_table.get(key)

    paths = replace(
        Paths(),
        **{key: str(pick_path(key)) for key in PATH_KEYS if pick_path(key)},
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

    for key, values in data.items():
        if key not in TOP_LEVEL:
            raise ConfigError(
                f"unknown key or table {key!r}. The top level holds default, "
                f"[models.<name>], [step], and [paths]."
            )
        if key == "default":
            continue
        if not isinstance(values, dict):
            raise ConfigError(f"[{key}] must be a table")
        if key == "models":
            continue
        for name in values:
            if name not in TABLES[key]:
                raise ConfigError(
                    f"unknown key {name!r} in [{key}]. The keys are "
                    f"{', '.join(TABLES[key])}."
                )
    return data


def _check_entry(name: str, entry: Any) -> None:
    """Check 1 [models.<name>] table: its name, its keys, and its ranges.

    Each entry is checked, and not only the selected one: a bad entry fails
    at once, and not on the day that a caller selects it.
    """
    if not isinstance(entry, dict):
        raise ConfigError(f"models.{name} must be a [models.{name}] table")
    for key, value in entry.items():
        if isinstance(value, dict):
            raise ConfigError(f"[models.{name}.{key}]: an entry name has no dot")
    if not ENTRY_PATTERN.fullmatch(name):
        raise ConfigError(f"models: the entry name {name!r} is not {ENTRY_RULE}")
    for key in entry:
        if key not in ENTRY_KEYS:
            raise ConfigError(
                f"unknown key {key!r} in [models.{name}]. The keys are "
                f"{', '.join(ENTRY_KEYS)}."
            )
    label = f"models.{name}"
    if not entry.get("model"):
        raise ConfigError(f"{label}.model: no value. Each entry names a model.")
    kind = _one_of(f"{label}.kind", entry.get("kind", "subscription"), KINDS)
    _one_of(f"{label}.effort", entry.get("effort", "high"), EFFORTS)
    for key in STEP_KEYS:
        if key in entry:
            _check_limit(f"{label}.{key}", key, entry[key])
    _check_key_source(label, kind, entry)


def _check_limit(label: str, key: str, value: Any) -> None:
    limits, kind = LIMITS[key]
    _in_range(label, value, limits, kind)


def _check_key_source(label: str, kind: str, entry: Mapping[str, Any]) -> None:
    """The 2 checks of the key that read the file, and not the environment."""
    if entry.get("api_key") and entry.get("api_key_env"):
        raise ConfigError(
            f"{label}: api_key and api_key_env are both set. Use 1 of them."
        )
    if kind != "subscription" and not (entry.get("api_key") or entry.get("api_key_env")):
        raise ConfigError(
            f"{label}: the provider kind {kind!r} needs a key. "
            f"Set api_key_env or api_key."
        )


def _api_key(label: str, entry: Mapping[str, Any], env: Mapping[str, str]) -> str | None:
    """Read the key of the selected entry. _check_key_source ran before."""
    literal = entry.get("api_key")
    variable = entry.get("api_key_env")
    if literal:
        return str(literal)
    if variable:
        value = env.get(str(variable))
        if not value:
            raise ConfigError(
                f"{label}.api_key_env names {variable!r}, and that variable is "
                f"empty or absent"
            )
        return value
    return None


def _select(entries: Mapping[str, Any], data: Mapping[str, Any], chosen: Any) -> str:
    """Give the name of the entry of this call: the override, then default,
    then the only entry."""
    if not entries:
        raise ConfigError(NO_MODEL)
    names = ", ".join(entries)
    default = data.get("default")
    if "default" in data:
        if not isinstance(default, str):
            raise ConfigError(
                f"default: the value {default!r} is not a string. It names 1 "
                f"entry. The entries are {names}."
            )
        if default not in entries:
            raise ConfigError(
                f"default: the value {default!r} names no entry. "
                f"The entries are {names}."
            )
    if chosen is not None:
        if chosen not in entries:
            raise ConfigError(
                f"model: the value {chosen!r} names no entry. "
                f"The entries are {names}."
            )
        return chosen
    if default is not None:
        return default
    if len(entries) == 1:
        return next(iter(entries))
    raise ConfigError(
        f"model: the file has {len(entries)} entries and no default. Set "
        f'default = "<name>" in the file, or pass --model. '
        f"The entries are {names}."
    )


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
