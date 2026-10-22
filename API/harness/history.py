"""Conversation history, persisted to disk as an append-only JSONL log.

Lines are never rewritten. Three record kinds:
  {"kind": "message", "message": {...}}      one API message (user or assistant)
  {"kind": "compaction", "summary": "..."}   everything before this line is replaced by the summary
  {"kind": "rollback", "to": n}              drop a dangling tail (e.g. a crash mid tool-loop)
Replaying the log rebuilds exactly the message list the model last saw.
"""
from __future__ import annotations

import json
from pathlib import Path

from API.harness import logger

log = logger(__file__)


def serialize_content(blocks: list) -> list[dict]:
    """SDK content blocks -> plain dicts. Thinking blocks keep their signature untouched."""
    out = []
    for b in blocks:
        out.append(b if isinstance(b, dict) else b.model_dump(mode="json", exclude_none=True))
    return out


class History:
    def __init__(self, path: Path, resume: bool = False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.messages: list[dict] = []
        self.summary: str | None = None
        if resume and self.path.exists():
            self._replay()
            log(f"resumed {self.path.name}: {len(self.messages)} messages, summary={'yes' if self.summary else 'no'}")
            self._repair_tail()
        else:
            self.path.write_text("", encoding="utf-8")
            log(f"new conversation log {self.path.name}")

    def _write(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _replay(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec["kind"] == "message":
                self.messages.append(rec["message"])
            elif rec["kind"] == "compaction":
                self.messages, self.summary = [], rec["summary"]
            elif rec["kind"] == "rollback":
                del self.messages[rec["to"]:]

    def _repair_tail(self) -> None:
        """A conversation must end with a finished assistant turn before a new user turn."""
        keep = len(self.messages)
        while keep and not _is_complete_assistant(self.messages[keep - 1]):
            keep -= 1
        if keep < len(self.messages):
            log(f"dropping {len(self.messages) - keep} dangling message(s) from an unfinished turn")
            del self.messages[keep:]
            self._write({"kind": "rollback", "to": keep})

    def append(self, message: dict) -> None:
        message = {"role": message["role"], "content": serialize_content(message["content"])
                   if isinstance(message["content"], list) else message["content"]}
        self.messages.append(message)
        self._write({"kind": "message", "message": message})
        log(f"append {message['role']} message #{len(self.messages)} ({_describe(message)})")

    def compact(self, summary: str) -> None:
        self._write({"kind": "compaction", "summary": summary})
        log(f"compaction record written; {len(self.messages)} messages replaced by a {len(summary)}-char summary")
        self.messages, self.summary = [], summary


def _is_complete_assistant(message: dict) -> bool:
    if message["role"] != "assistant":
        return False
    content = message["content"]
    return isinstance(content, str) or not any(b.get("type") == "tool_use" for b in content)


def _describe(message: dict) -> str:
    content = message["content"]
    if isinstance(content, str):
        return "text"
    kinds: dict[str, int] = {}
    for b in content:
        kinds[b.get("type", "?")] = kinds.get(b.get("type", "?"), 0) + 1
    return ", ".join(f"{k}x{v}" for k, v in kinds.items())
