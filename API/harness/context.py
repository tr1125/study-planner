"""What goes into each turn, besides the frozen system prompt and the history.

Each user turn is prefixed with a small <context> block holding only what is
relevant and new to this conversation:
  - planner_date (only on the first turn, or after compaction)
  - the conversation summary, if the history was just compacted
  - memory facts relevant to this request that the model hasn't seen yet
  - a digest of upcoming deadlines, only when it changed since last shown
Everything else (all sessions, all deadlines, older memory) the model pulls
with tools. The block lives in the user message, not in `system`, so the
cached prefix (tools + system) never changes.
"""
from __future__ import annotations

import re

from API.harness import logger
from API.harness.memory import Memory
from shared.store import weekday
from shared.tools import Domain

log = logger(__file__)

DIGEST_DEADLINES = 4
_FACT_ID = re.compile(r"^- (M\d+) \[", re.MULTILINE)


class ContextBuilder:
    def __init__(self, domain: Domain, memory: Memory):
        self.domain = domain
        self.memory = memory
        self.shown_facts: set[str] = set()
        self.last_digest: str | None = None
        self.date_shown = False

    def reset(self) -> None:
        """After compaction the old context blocks are gone, so everything is re-sent."""
        self.shown_facts.clear()
        self.last_digest = None
        self.date_shown = False

    def restore_from(self, messages: list[dict]) -> None:
        """On resume, recover what was already shown by scanning earlier context blocks."""
        for m in messages:
            if m["role"] != "user" or isinstance(m["content"], str):
                continue
            for b in m["content"]:
                if b.get("type") == "text" and b["text"].startswith("<context>"):
                    self.shown_facts.update(_FACT_ID.findall(b["text"]))
                    self.date_shown = True
                    if "upcoming deadlines:" in b["text"]:
                        self.last_digest = b["text"].split("upcoming deadlines:\n", 1)[1].split("\n</context>")[0]

    def _digest(self) -> str:
        items = self.domain.store.list_deadlines()
        upcoming = [d for d in items if self.domain.store.days_until(d["due"]) >= 0][:DIGEST_DEADLINES]
        lines = [f"{d['id']} {d['course']} {d['kind']} due {d['due']} (in {self.domain.store.days_until(d['due'])}d)"
                 for d in upcoming]
        more = len(items) - len(upcoming)
        if more > 0:
            lines.append(f"(+{more} more via list_deadlines)")
        return "\n".join(lines)

    def build_user_message(self, text: str, summary: str | None) -> dict:
        parts, sections = [], []
        if not self.date_shown:
            parts.append(f"planner_date: {self.domain.today} ({weekday(self.domain.today)})")
            sections.append("date")
            self.date_shown = True
        if summary:
            parts.append(f"summary of the earlier conversation:\n{summary}")
            sections.append("summary")
        facts = self.memory.relevant(text, self.shown_facts)
        if facts:
            parts.append("saved memory relevant to this request (more via recall):\n"
                         + "\n".join(f"- {f['id']} [{f['category']}] {f['text']}" for f in facts))
            self.shown_facts.update(f["id"] for f in facts)
            sections.append(f"memory x{len(facts)}")
        digest = self._digest()
        if digest and digest != self.last_digest:
            parts.append("upcoming deadlines:\n" + digest)
            self.last_digest = digest
            sections.append("deadlines")
        content = []
        if parts:
            content.append({"type": "text", "text": "<context>\n" + "\n\n".join(parts) + "\n</context>"})
        content.append({"type": "text", "text": text})
        size = sum(len(c["text"]) for c in content[:-1])
        log(f"turn context: {', '.join(sections) or 'nothing new'} ({size} chars injected)")
        return {"role": "user", "content": content}
