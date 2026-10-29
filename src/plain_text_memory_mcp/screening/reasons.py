"""Flag notes that state a fact without saying why.

- Memory is for what the code cannot show, and the reason behind a fact is
  the part a reader of the code never sees.
- The check looks for words that introduce a cause, purpose, or
  consequence; a fact with none of them is worth a second look, not wrong.
"""

from __future__ import annotations

import re

_REASON_PATTERN = re.compile(
    r"\b(because|since|so|thus|hence|therefore|otherwise|unless"
    r"|instead of|rather than|in order to|due to|avoids?"
    r"|to (avoid|keep|prevent|stop|spare|save|let)"
    r"|which (means|makes|lets|keeps))\b",
    re.IGNORECASE,
)


def look_reason(text: str) -> str | None:
    """Return the words in `text` that introduce a reason, or None."""
    match = _REASON_PATTERN.search(text)
    return match.group(0) if match else None
