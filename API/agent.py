"""Study Planner on the raw Messages API: wires the hand-written harness together."""
from __future__ import annotations

from pathlib import Path

from API.harness import caching, compaction, logger, loop
from API.harness.context import ContextBuilder
from API.harness.history import History
from API.harness.memory import Memory
from API.harness.tokens import TokenMeter
from API.harness.tools import ToolRegistry
from shared.prompts import EFFORT, MODEL, system_prompt
from shared.tools import Domain

log = logger(__file__)

MAX_TOKENS = 16000


class StudyAgentAPI:
    def __init__(self, data_dir: Path, today: str, session: str = "s1", resume: bool = False,
                 client=None, fetch=None, compact_threshold: int = compaction.DEFAULT_THRESHOLD,
                 run_tag: str | None = None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from the environment
        self.client = client
        self.domain = Domain(data_dir, today, fetch=fetch)
        self.tools = ToolRegistry(self.domain)
        self.history = History(Path(data_dir) / "history" / f"{session}.jsonl", resume=resume)
        self.context = ContextBuilder(self.domain, Memory(self.domain.memory))
        self.context.restore_from(self.history.messages)
        self.meter = TokenMeter(MODEL)
        self.compactor = compaction.Compactor(compact_threshold)
        # Identical on every request of the session -> cacheable prefix.
        self.request_base = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": caching.system_blocks(system_prompt(run_tag)),
            "tools": self.tools.definitions(),
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": EFFORT},
        }
        log(f"agent ready: session={session} resume={resume} model={MODEL} effort={EFFORT} "
            f"tools={len(self.request_base['tools'])}")

    def run_turn(self, text: str) -> dict:
        self.meter.start_turn()
        if self.compactor.needed(self.meter):
            self.compactor.compact(self.client, self.request_base, self.history, self.meter)
            self.context.reset()
        summary = self.history.summary if not self.history.messages else None
        self.history.append(self.context.build_user_message(text, summary))
        reply, called = loop.run(self.client, self.request_base, self.history, self.tools, self.meter)
        t = self.meter.end_turn()
        return {
            "reply": reply,
            "tokens": {k: t[k] for k in ("input", "cache_read", "cache_write", "output")},
            "model_calls": t["calls"],
            "tools": called,
            "cost_usd": round(t["cost_usd"], 6),
        }

    def close(self) -> None:
        log("session closed (history and memory are already on disk)")
