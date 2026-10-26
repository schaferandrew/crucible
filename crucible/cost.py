"""What a run cost, in USD, and where that number came from.

Sources, best first (recorded as metrics.cost_source):

- "openrouter_billed": the OPENROUTER_API_KEY's billed usage, read before and
  after the run. Real money for any agent, but only clean when nothing else
  spends on that key during the run (give an LLM judge its own key). Set
  CRUCIBLE_BILLED_COST=0 when runs share a key in parallel, so each run falls
  back to its own estimate instead of absorbing the others' spend.
- "<agent>_estimate": the agent's own figure from its session record, priced
  from the agent's built-in price list (local models read $0).
"""
from __future__ import annotations

import os
import time
from typing import Callable

from crucible import providers

# OpenRouter's key usage can lag a request by a few seconds
SETTLE_ATTEMPTS = 5
SETTLE_DELAY_S = 2.0


class BilledCost:
    """Billed spend across a block: `with BilledCost(model) as bill: ...; bill.usd`.

    usd stays None for non-OpenRouter models, without a key, or when the
    usage endpoint is unreachable.
    """

    def __init__(self, model: str | None,
                 read_usage: Callable[[], float | None] = providers.fetch_openrouter_key_usage,
                 sleep: Callable[[float], None] = time.sleep):
        self._enabled = (bool(model and model.startswith("openrouter/"))
                         and os.environ.get("CRUCIBLE_BILLED_COST", "1") != "0")
        self._read_usage = read_usage
        self._sleep = sleep
        self._before: float | None = None
        self.usd: float | None = None

    def __enter__(self) -> "BilledCost":
        if self._enabled:
            self._before = self._read_usage()
        return self

    def __exit__(self, *exc) -> None:
        if self._before is None:
            return
        for attempt in range(SETTLE_ATTEMPTS):
            after = self._read_usage()
            if after is None:
                return
            self.usd = round(max(after - self._before, 0.0), 6)
            if self.usd > 0 or attempt == SETTLE_ATTEMPTS - 1:
                return
            self._sleep(SETTLE_DELAY_S)


def run_cost(agent_name: str, estimate_usd: float | None, billed_usd: float | None) -> dict:
    """{"cost_usd", "cost_source"} for meta.json metrics (both None when unknown)."""
    if billed_usd is not None:
        return {"cost_usd": billed_usd, "cost_source": "openrouter_billed"}
    if estimate_usd is not None:
        return {"cost_usd": round(estimate_usd, 6), "cost_source": f"{agent_name}_estimate"}
    return {"cost_usd": None, "cost_source": None}
