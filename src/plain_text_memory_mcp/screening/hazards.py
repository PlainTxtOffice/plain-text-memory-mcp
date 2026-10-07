"""Flag text that reads as instructions to an agent, or holds a secret.

- Memory is context for the next agent, so a saved instruction can steer
  it: a few poisoned entries can hijack an agent (AgentPoison, Chen et al.,
  NeurIPS 2024), and retrieved text carries indirect prompt injection
  (Greshake et al., AISec 2023).
- The patterns aim at text addressed to a model and at well-known secret
  formats; ordinary conventions such as "Never commit .env" pass.
"""

from __future__ import annotations

import re

_INSTRUCTION_PATTERNS = (
    re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.]{0,40}"
        r"\b(instructions?|rules|prompts?|guidelines|polic(y|ies))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(system prompt|developer message|new instructions|you are now"
        r"|from now on,? you)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(do not|don't|never)\s+(tell|inform|show|alert)\s+the\s+user\b",
        re.IGNORECASE,
    ),
    re.compile(r"</?\s*(system|instructions?|assistant)\s*>", re.IGNORECASE),
    re.compile(r"\b(curl|wget)\b[^|]*\|\s*(ba|z)?sh\b", re.IGNORECASE),
)

_SECRET_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("GitHub token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("API key", re.compile(r"\bsk-(ant-|proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    (
        "JSON web token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[\w-]+"),
    ),
    (
        "credential assignment",
        re.compile(
            r"\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*"
            r"['\"]?[^\s'\"]{8,}",
            re.IGNORECASE,
        ),
    ),
)


def look_instruction(text: str) -> str | None:
    """Return the part of `text` that reads as an instruction, or None."""
    for pattern in _INSTRUCTION_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def look_secret(text: str) -> str | None:
    """Return the kind of secret `text` appears to hold, or None.

    - Names the kind only, so a warning never repeats the secret.
    """
    for kind, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return kind
    return None
