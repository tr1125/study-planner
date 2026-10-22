"""Token usage and cost, per model call and per user turn.

Prices are USD per million tokens. Cache writes use the 5-minute TTL rate
(1.25x input); cache reads are billed at the model's cache-read rate.
"""
from __future__ import annotations

from API.harness import logger

log = logger(__file__)

PRICES = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
}


class TokenMeter:
    def __init__(self, model: str):
        if model not in PRICES:
            raise ValueError(f"no price table for {model}")
        self.price = PRICES[model]
        self.turn = self._empty()
        self.last_prompt_tokens = 0     # size of the most recent request; used by compaction

    @staticmethod
    def _empty() -> dict:
        return {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0, "calls": 0, "cost_usd": 0.0}

    def cost(self, u: dict) -> float:
        p = self.price
        return (u["input"] * p["input"] + u["cache_read"] * p["cache_read"]
                + u["cache_write"] * p["cache_write"] + u["output"] * p["output"]) / 1_000_000

    def record(self, usage, label: str = "call") -> dict:
        u = {
            "input": usage.input_tokens or 0,
            "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            "output": usage.output_tokens or 0,
        }
        c = self.cost(u)
        for k, v in u.items():
            self.turn[k] += v
        self.turn["calls"] += 1
        self.turn["cost_usd"] += c
        self.last_prompt_tokens = u["input"] + u["cache_read"] + u["cache_write"]
        log(f"{label} #{self.turn['calls']}: in={u['input']} cache_read={u['cache_read']} "
            f"cache_write={u['cache_write']} out={u['output']} -> ${c:.5f}")
        return u

    def start_turn(self) -> None:
        self.turn = self._empty()

    def end_turn(self) -> dict:
        t = self.turn
        prompt = t["input"] + t["cache_read"] + t["cache_write"]
        hit = 100 * t["cache_read"] / prompt if prompt else 0.0
        log(f"turn total: {t['calls']} calls, prompt={prompt} (cache hit {hit:.0f}%), out={t['output']}, "
            f"${t['cost_usd']:.5f}")
        return dict(t)
