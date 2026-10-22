"""Long-term memory: short facts about the student that survive across sessions.

Facts are never deleted. Changing a preference supersedes the old fact
(status -> "superseded", superseded_by -> new id), so the history of decisions
stays auditable and the scenario checks can verify the change on disk.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from shared.store import DomainError, write_json_atomic

CATEGORIES = ("preference", "constraint", "decision", "history")

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "are", "was", "you", "your", "about",
    "what", "how", "have", "has", "but", "not", "can", "will", "from", "they", "their",
    "them", "she", "her", "his", "him", "its", "into", "than", "then", "when", "who",
    "any", "all", "out", "our", "too", "very", "just", "also", "like", "does", "did",
}


def keywords(text: str) -> set[str]:
    """Lower-cased content words with a naive plural strip ('sessions' -> 'session')."""
    words = re.findall(r"[a-z0-9א-ת]+", text.lower())
    out = set()
    for w in words:
        if len(w) < 3 or w in _STOPWORDS:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


class MemoryStore:
    def __init__(self, data_dir: Path, today: str):
        self.path = Path(data_dir) / "memory.json"
        self.today = today
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"next_id": 1, "facts": []}

    def _save(self) -> None:
        write_json_atomic(self.path, self.data)

    def get(self, fact_id: str) -> dict:
        for f in self.data["facts"]:
            if f["id"] == fact_id:
                return f
        raise DomainError(f"no memory fact with id {fact_id!r}")

    def add(self, text: str, category: str, replaces: str | None = None) -> dict:
        text = " ".join(text.split())
        if not text:
            raise DomainError("fact must not be empty")
        if len(text) > 200:
            raise DomainError("fact too long (max 200 chars); store one short fact per call")
        if category not in CATEGORIES:
            raise DomainError(f"category must be one of {', '.join(CATEGORIES)}")
        old = None
        if replaces:
            old = self.get(replaces)
            if old["status"] != "active":
                raise DomainError(f"{replaces} is already superseded by {old['superseded_by']}")
        for f in self.active():
            if f["text"].lower() == text.lower():
                raise DomainError(f"already remembered as {f['id']}")
        fact = {
            "id": f"M{self.data['next_id']}",
            "text": text,
            "category": category,
            "status": "active",
            "created": self.today,
            "replaces": replaces,
            "superseded_by": None,
        }
        self.data["next_id"] += 1
        if old is not None:
            old["status"] = "superseded"
            old["superseded_by"] = fact["id"]
        self.data["facts"].append(fact)
        self._save()
        return fact

    def active(self) -> list[dict]:
        return [f for f in self.data["facts"] if f["status"] == "active"]

    def search(self, query: str, limit: int = 5, include_superseded: bool = False) -> list[dict]:
        """Rank facts by keyword overlap with the query; empty query = newest facts."""
        pool = self.data["facts"] if include_superseded else self.active()
        q = keywords(query)
        if not q:
            return list(reversed(pool))[:limit]
        scored = []
        for i, f in enumerate(pool):
            score = len(q & keywords(f["text"] + " " + f["category"]))
            if score:
                scored.append((score, i, f))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        return [f for _, _, f in scored[:limit]]

    def to_markdown(self) -> str:
        lines = [f"- {f['id']} [{f['category']}] {f['text']}" for f in self.active()]
        return "\n".join(lines) if lines else "- (nothing saved yet)"
