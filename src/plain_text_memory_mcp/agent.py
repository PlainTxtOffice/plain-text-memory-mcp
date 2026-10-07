"""Name the agent that is calling the memory server."""

UNKNOWN_AGENT = "unknown"

KNOWN_AGENTS = (("claude", "claude-code"), ("codex", "codex"))


def calc_agent_name(client_name: str | None, override: str | None) -> str:
    """Return the agent name recorded in memory tags.

    - A non-blank override, from `MEMORY_AGENT`, always wins.
    - Client names containing "claude" or "codex" map to `claude-code` and
      `codex`; any other name is recorded as sent.
    - A missing or blank client name records `unknown`.
    """
    if override and override.strip():
        return override.strip()
    if not client_name or not client_name.strip():
        return UNKNOWN_AGENT
    lowered = client_name.lower()
    for marker, agent_name in KNOWN_AGENTS:
        if marker in lowered:
            return agent_name
    return client_name.strip()
