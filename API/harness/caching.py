"""Prompt-caching breakpoints (cache_control) for every request.

Render order is tools -> system -> messages, and a cache hit is a byte-exact
prefix match. Two explicit breakpoints:
  1. the system block: caches tools + system, which never change in a session
  2. the last block of the last message: caches the whole conversation so far,
     so the next call (next tool-loop iteration or next turn) reads it back
The stored history is never mutated: only the copy sent on the wire is marked.
"""
from __future__ import annotations

import copy

from API.harness import logger

log = logger(__file__)

EPHEMERAL = {"type": "ephemeral"}   # 5-minute TTL; loop calls are seconds apart
UNCACHEABLE = {"thinking", "redacted_thinking"}


def system_blocks(system_prompt: str) -> list[dict]:
    return [{"type": "text", "text": system_prompt, "cache_control": EPHEMERAL}]


def mark_messages(messages: list[dict]) -> list[dict]:
    """Return a shallow copy of `messages` with a breakpoint on the last cacheable block."""
    if not messages:
        return messages
    out = list(messages)
    for idx in range(len(out) - 1, -1, -1):
        msg = out[idx]
        content = msg["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for j in range(len(content) - 1, -1, -1):
            if content[j].get("type") in UNCACHEABLE:
                continue
            new_msg = copy.deepcopy(msg)
            new_msg["content"] = copy.deepcopy(content)
            new_msg["content"][j]["cache_control"] = EPHEMERAL
            out[idx] = new_msg
            log(f"breakpoints: system(+tools) and messages[{idx}].content[{j}] ({content[j].get('type')})")
            return out
    return out
