"""Weigh memories by how recently and how often they were used.

- Uses ACT-R base-level activation (Anderson et al., Psychological Review,
  2004): B = ln(sum of t^-d) over the times a memory was presented, with
  decay d = 0.5. With one presentation, the time it was added, this is the
  power-law recency of Anderson & Schooler (Psychological Science, 1991).
- Ages are in days plus one, so a memory added just now has t = 1.
"""

from __future__ import annotations

import math
from datetime import datetime

from plain_text_memory_mcp import graph

DECAY = 0.5
_SECONDS_PER_DAY = 86_400


def calc_activation(times: list[str | None], now: datetime) -> float:
    """Return the base-level activation of a memory presented at `times`.

    - Unparseable and missing times are skipped; with none left, returns
      negative infinity.
    - A time after `now`, from clock skew, counts as now.
    """
    total = 0.0
    for value in times:
        moment = graph.parse_moment(value)
        if moment is None:
            continue
        age_days = max((now - moment).total_seconds(), 0) / _SECONDS_PER_DAY
        total += (1 + age_days) ** -DECAY
    return math.log(total) if total else -math.inf


def calc_prior(times: list[str | None], now: datetime) -> float:
    """Return a non-negative weight that grows with activation.

    - Softplus of the activation: ln(1 + sum of t^-d). An untagged memory
      weighs 0; one added just now weighs ln 2.
    """
    activation = calc_activation(times, now)
    return math.log1p(math.exp(activation)) if activation > -math.inf else 0.0
