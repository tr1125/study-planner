"""Tool schemas for the Messages API, input validation, dispatch, and errors.

Errors never crash the loop: a bad input, a domain error, or an unexpected
exception all become a tool_result with is_error=True that the model can read.
"""
from __future__ import annotations

from API.harness import logger
from shared.store import DomainError
from shared.tools import TOOLS, Domain, ToolSpec, run_tool

log = logger(__file__)

_JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
MAX_RESULT_CHARS = 4000


def validate(schema: dict, args: object) -> str | None:
    """Minimal JSON-schema check of the model's input. Returns an error message or None."""
    if not isinstance(args, dict):
        return "input must be a JSON object"
    props = schema.get("properties", {})
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        return f"missing required field(s): {', '.join(missing)}"
    if schema.get("additionalProperties") is False:
        extra = [k for k in args if k not in props]
        if extra:
            return f"unknown field(s): {', '.join(extra)}; allowed: {', '.join(props)}"
    for key, value in args.items():
        rule = props.get(key, {})
        expected = _JSON_TYPES.get(rule.get("type"))
        # bool is a subclass of int in Python; reject it for numeric fields
        if expected and (not isinstance(value, expected) or (isinstance(value, bool) and rule["type"] != "boolean")):
            return f"{key} must be of type {rule['type']}"
        if "enum" in rule and value not in rule["enum"]:
            return f"{key} must be one of {rule['enum']}"
        if ("minimum" in rule and value < rule["minimum"]) or ("maximum" in rule and value > rule["maximum"]):
            return f"{key} out of range [{rule.get('minimum')}, {rule.get('maximum')}]"
    return None


class ToolRegistry:
    def __init__(self, domain: Domain, specs: list[ToolSpec] = TOOLS):
        self.domain = domain
        # Sorted by name: the tool list renders first in the prompt, so it must be byte-stable for caching.
        self.specs = {s.name: s for s in sorted(specs, key=lambda s: s.name)}

    def definitions(self) -> list[dict]:
        return [
            {"name": s.name, "description": s.description, "input_schema": s.schema}
            for s in self.specs.values()
        ]

    def execute(self, name: str, tool_input: object) -> tuple[str, bool]:
        spec = self.specs.get(name)
        if spec is None:
            return f"unknown tool {name!r}; available: {', '.join(self.specs)}", True
        problem = validate(spec.schema, tool_input)
        if problem:
            return f"invalid input: {problem}", True
        try:
            text = run_tool(self.domain, name, tool_input)
        except DomainError as exc:
            return f"error: {exc}", True
        except Exception as exc:  # unexpected bug in a tool: report, don't crash the agent
            return f"internal tool error: {exc.__class__.__name__}: {exc}", True
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + f"\n...[truncated {len(text) - MAX_RESULT_CHARS} chars; narrow the query]"
        return text, False

    def execute_all(self, tool_uses: list) -> list[dict]:
        """Run every tool_use block of one assistant message -> tool_result blocks for ONE user message."""
        results = []
        for block in tool_uses:
            text, is_error = self.execute(block.name, block.input)
            status = "ERROR" if is_error else "ok"
            log(f"dispatch {block.name}({_short(block.input)}) -> {status}: {_short(text)}")
            result = {"type": "tool_result", "tool_use_id": block.id, "content": text}
            if is_error:
                result["is_error"] = True
            results.append(result)
        return results


def _short(value: object, limit: int = 90) -> str:
    s = str(value).replace("\n", " | ")
    return s if len(s) <= limit else s[: limit - 3] + "..."
