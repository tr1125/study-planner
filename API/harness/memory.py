"""Long-term memory retrieval: which saved facts are relevant to this turn.

Storage: <data_dir>/memory.json (shared.memory_store.MemoryStore), written by
the `remember` tool and read here at the start of every turn. Retrieval is
selective; the model can always search the rest with the `recall` tool.
"""
from __future__ import annotations

from API.harness import logger
from shared.memory_store import MemoryStore, keywords

log = logger(__file__)

# Turns about planning or the student's habits make every preference/constraint relevant.
PLANNING_WORDS = {
    "plan", "schedule", "session", "study", "studying", "week", "book", "put", "move", "time",
    "morning", "evening", "friday", "saturday", "hour", "prefer", "remember", "like", "habit",
}
ALWAYS_FOR_PLANNING = {"preference", "constraint"}
MAX_FACTS = 6


class Memory:
    def __init__(self, store: MemoryStore):
        self.store = store

    def relevant(self, query: str, already_shown: set[str]) -> list[dict]:
        """Active facts relevant to `query` that the model has not already seen in this conversation."""
        active = self.store.active()
        q = keywords(query)
        planning = bool(q & PLANNING_WORDS)
        scored = []
        for i, fact in enumerate(active):
            score = len(q & keywords(fact["text"]))
            if planning and fact["category"] in ALWAYS_FOR_PLANNING:
                score += 1
            if score:
                scored.append((score, i, fact))
        scored.sort(key=lambda t: (-t[0], t[1]))
        picked = [f for _, _, f in scored[:MAX_FACTS]]
        fresh = [f for f in picked if f["id"] not in already_shown]
        log(f"{len(active)} active facts; {len(picked)} relevant to this turn; "
            f"{len(fresh)} new to the conversation ({', '.join(f['id'] for f in fresh) or '-'})")
        return fresh
