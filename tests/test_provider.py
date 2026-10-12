import pytest

from renfield.provider import (
    ALLOWLIST,
    OPENROUTER_BASE_URL,
    Provider,
    ProviderError,
    build_env,
)

PARENT = {
    "PATH": "/usr/bin",
    "HOME": "/home/x",
    "ANTHROPIC_API_KEY": "the-key-of-the-parent",
    "CLAUDE_CODE_SSE_PORT": "1234",
    "AWS_SECRET_ACCESS_KEY": "shh",
}


def test_a_subscription_child_gets_no_key_and_no_secret_of_the_parent():
    env = build_env(Provider(kind="subscription"), PARENT)
    assert env == {"PATH": "/usr/bin", "HOME": "/home/x"}
    assert "ANTHROPIC_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "CLAUDE_CODE_SSE_PORT" not in env


def test_the_allowlist_holds_9_names_and_no_secret():
    assert len(ALLOWLIST) == 9
    assert not [name for name in ALLOWLIST if "KEY" in name or "TOKEN" in name]


def test_an_api_child_gets_the_key_of_the_config_and_not_of_the_parent():
    env = build_env(Provider(kind="anthropic-api", api_key="mine"), PARENT)
    assert env["ANTHROPIC_API_KEY"] == "mine"


def test_an_openrouter_child_gets_the_base_url_and_an_empty_api_key():
    env = build_env(Provider(kind="openrouter", api_key="or-key"), PARENT)
    assert env["ANTHROPIC_BASE_URL"] == OPENROUTER_BASE_URL
    assert env["ANTHROPIC_AUTH_TOKEN"] == "or-key"
    # An empty value, and not an absent name. An absent name lets the child
    # find a key elsewhere and bill the wrong account.
    assert env["ANTHROPIC_API_KEY"] == ""


def test_a_base_url_of_the_config_wins_over_the_default():
    env = build_env(
        Provider(kind="openrouter", api_key="k", base_url="https://proxy/api"), PARENT
    )
    assert env["ANTHROPIC_BASE_URL"] == "https://proxy/api"


def test_a_kind_that_needs_a_key_and_has_none_stops_the_run():
    with pytest.raises(ProviderError, match="no key"):
        build_env(Provider(kind="openrouter"), PARENT)


def test_an_unknown_kind_stops_the_run_and_names_the_kind():
    with pytest.raises(ProviderError, match="moonshot"):
        build_env(Provider(kind="moonshot"), PARENT)


def test_a_config_dir_keeps_the_user_configuration_out_of_the_child(tmp_path):
    env = build_env(Provider(kind="subscription"), PARENT, config_dir=tmp_path)
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path)
