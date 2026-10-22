"""The shared domain tools, exposed to Claude Code as an in-process MCP server."""
from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server, tool

from shared.store import DomainError
from shared.tools import TOOLS, Domain, ToolSpec

SERVER_NAME = "study"


def _wrap(spec: ToolSpec, domain: Domain):
    @tool(spec.name, spec.description, spec.schema)  # replaces: tools
    async def handler(args: dict) -> dict:
        print(f"[SDK/tools.py] {spec.name}({args})", flush=True)
        try:
            text = spec.fn(domain, args)  # replaces: tools
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"error: {exc}"}], "is_error": True}  # replaces: tools
        return {"content": [{"type": "text", "text": text}]}  # replaces: tools

    return handler


def build_server(domain: Domain):
    """Returns (MCP server config, fully-qualified tool names for allowed_tools)."""
    server = create_sdk_mcp_server(SERVER_NAME, tools=[_wrap(s, domain) for s in TOOLS])  # replaces: tools
    names = [f"mcp__{SERVER_NAME}__{s.name}" for s in TOOLS]  # replaces: tools
    return server, names
