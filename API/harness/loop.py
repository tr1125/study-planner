"""The agent loop: call the model; while stop_reason == "tool_use", run the tools
and send ALL their results back in ONE user message; stop on anything else.
"""
from __future__ import annotations

from API.harness import caching, logger
from API.harness.history import History
from API.harness.tokens import TokenMeter
from API.harness.tools import ToolRegistry

log = logger(__file__)

MAX_ITERATIONS = 15


def _text(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


def run(client, request_base: dict, history: History, tools: ToolRegistry, meter: TokenMeter) -> tuple[str, list[str]]:
    """Run one user turn to completion. Returns (final text, names of tools called)."""
    called: list[str] = []

    def call_model():
        log(f"call #{meter.turn['calls'] + 1}: messages.create with {len(history.messages)} messages")
        response = client.messages.create(**request_base, messages=caching.mark_messages(history.messages))
        meter.record(response.usage)
        history.append({"role": "assistant", "content": response.content})
        log(f"stop_reason={response.stop_reason}")
        return response

    response = call_model()
    iterations = 1
    while response.stop_reason == "tool_use":
        uses = [b for b in response.content if b.type == "tool_use"]
        if iterations >= MAX_ITERATIONS:
            # Answer the open tool_use blocks so the history stays valid for the next turn
            # (the next user message simply follows this tool_result message).
            history.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b.id, "content": "aborted: tool-loop limit", "is_error": True}
                for b in uses]})
            log(f"stopped after {MAX_ITERATIONS} model calls")
            return "(stopped: too many tool calls in one turn)", called
        called += [b.name for b in uses]
        log(f"model requested {len(uses)} tool call(s): {', '.join(b.name for b in uses)}")
        results = tools.execute_all(uses)
        history.append({"role": "user", "content": results})   # all results in one message
        response = call_model()
        iterations += 1

    if response.stop_reason == "max_tokens":
        log("warning: reply truncated at max_tokens")
    elif response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        log(f"model declined (category={getattr(details, 'category', None)})")
        return "(the model declined this request)", called
    return _text(response), called
