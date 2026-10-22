"""Context-window management: summarize the whole conversation past a threshold.

Checked at the start of each user turn (never mid tool-loop, so no tool_use is
left without its tool_result). The summary request reuses the exact tools +
system + history prefix of the real conversation, so it is mostly a cache read,
and only appends one instruction at the end. The summary is written to the
history log as a compaction record and injected by context.py into the next
user turn.
"""
from __future__ import annotations

from API.harness import caching, logger
from API.harness.history import History
from API.harness.tokens import TokenMeter

log = logger(__file__)

DEFAULT_THRESHOLD = 60_000   # prompt tokens; far below the 1M window, keeps every turn cheap

SUMMARY_INSTRUCTION = (
    "Compaction: the conversation so far will be replaced by your summary. Do not call tools. "
    "Write a compact summary (max 200 words) with: what the student asked for, what was done "
    "(ids of deadlines/sessions/memory facts created or changed), open questions or pending "
    "confirmations, and anything the student said that is not saved in memory yet."
)


class Compactor:
    def __init__(self, threshold: int = DEFAULT_THRESHOLD):
        self.threshold = threshold

    def needed(self, meter: TokenMeter) -> bool:
        return meter.last_prompt_tokens > self.threshold

    def compact(self, client, request_base: dict, history: History, meter: TokenMeter) -> str:
        log(f"prompt was {meter.last_prompt_tokens} tokens > threshold {self.threshold}; summarizing "
            f"{len(history.messages)} messages")
        messages = history.messages + [{"role": "user", "content": [{"type": "text", "text": SUMMARY_INSTRUCTION}]}]
        response = client.messages.create(**request_base, messages=caching.mark_messages(messages))
        meter.record(response.usage, label="compaction call")
        # A previous summary sits in the first user turn, so the new summary already covers it.
        summary = "\n".join(b.text for b in response.content if b.type == "text").strip() or "(empty summary)"
        history.compact(summary)
        meter.last_prompt_tokens = 0
        return summary
