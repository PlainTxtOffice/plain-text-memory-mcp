"""Tests for agent name resolution."""

import pytest

from plain_text_memory_mcp import agent


@pytest.mark.parametrize(
    ("client_name", "expected"),
    [
        ("claude-code", "claude-code"),
        ("Claude Code", "claude-code"),
        ("codex-mcp-client", "codex"),
        ("Codex", "codex"),
        ("Visual Studio Code", "Visual Studio Code"),
        (None, "unknown"),
        ("", "unknown"),
        ("   ", "unknown"),
    ],
)
def test_calc_agent_name_maps_client_names(
    client_name: str | None, expected: str
) -> None:
    assert agent.calc_agent_name(client_name, None) == expected


def test_calc_agent_name_override_wins() -> None:
    assert agent.calc_agent_name("claude-code", "tester") == "tester"


def test_calc_agent_name_blank_override_ignored() -> None:
    assert agent.calc_agent_name("codex-mcp-client", "  ") == "codex"
