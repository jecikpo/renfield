"""Build the environment of a child `claude` process.

The child starts from an allowlist, and not from the environment of the
parent. This keeps the key of the parent, the CLAUDE_CODE_* variables of a
parent session, and each other secret out of the child.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

ALLOWLIST = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "TERM",
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api"

KINDS = ("subscription", "anthropic-api", "openrouter")


class ProviderError(Exception):
    """The provider part of the configuration is not usable."""


@dataclass
class Provider:
    kind: str = "subscription"
    api_key: str | None = None
    base_url: str | None = None


def build_env(
    provider: Provider,
    parent: Mapping[str, str],
    config_dir: Path | None = None,
) -> dict[str, str]:
    """Give the environment for 1 child process."""
    env = {name: parent[name] for name in ALLOWLIST if name in parent}

    if provider.kind == "subscription":
        pass
    elif provider.kind == "anthropic-api":
        env["ANTHROPIC_API_KEY"] = _key(provider)
    elif provider.kind == "openrouter":
        env["ANTHROPIC_BASE_URL"] = provider.base_url or OPENROUTER_BASE_URL
        env["ANTHROPIC_AUTH_TOKEN"] = _key(provider)
        # An empty value, and not an absent name. An absent name lets the
        # child find a key elsewhere and bill the wrong account.
        env["ANTHROPIC_API_KEY"] = ""
    else:
        raise ProviderError(
            f"unknown provider kind: {provider.kind!r}. "
            f"The kinds are {', '.join(KINDS)}."
        )

    if config_dir is not None:
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)

    return env


def _key(provider: Provider) -> str:
    if not provider.api_key:
        raise ProviderError(f"provider kind {provider.kind!r} has no key")
    return provider.api_key
