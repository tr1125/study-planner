"""SDK version offline: options, CLAUDE.md memory, MCP tool wrappers, and a turn driven by a
fake ClaudeSDKClient that emits real claude_agent_sdk message objects."""
import asyncio
import json
import re

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from conftest import ROOT, TODAY, fake_fetch
from SDK.agent import StudyAgentSDK
from SDK.tools import _wrap, build_server
from shared.loc import PARTS, sdk_loc
from shared.tools import TOOLS_BY_NAME, Domain


class FakeSDKClient:
    instances: list["FakeSDKClient"] = []

    def __init__(self, options):
        self.options = options
        self.prompts: list[str] = []
        self.connected = False
        FakeSDKClient.instances.append(self)

    async def connect(self):
        self.connected = True

    async def query(self, prompt):
        self.prompts.append(prompt)

    async def receive_response(self):
        yield AssistantMessage(content=[ToolUseBlock("tu1", "mcp__study__recall", {"query": "friday"})],
                               model="claude-opus-5-5", message_id="msg_1")
        yield AssistantMessage(content=[TextBlock("You never study on Fridays.")],
                               model="claude-opus-5-5", message_id="msg_2")
        n = len(self.prompts)   # model_usage and total_cost_usd are cumulative over the session
        yield ResultMessage(
            subtype="success", duration_ms=1200, duration_api_ms=1000, is_error=False, num_turns=2,
            session_id="sess-123", total_cost_usd=0.0123 * n, result="You never study on Fridays.",
            usage={"input_tokens": 12, "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 400,
                   "output_tokens": 80},
            model_usage={
                "claude-opus-5-5": {"inputTokens": 12 * n, "cacheReadInputTokens": 3000 * n,
                                    "cacheCreationInputTokens": 400 * n, "outputTokens": 80 * n},
                "claude-haiku-5-5": {"inputTokens": 1000, "outputTokens": 10},   # one side call per session
            },
        )

    async def disconnect(self):
        self.connected = False


def make_agent(data_dir, **kw):
    return StudyAgentSDK(data_dir, TODAY, client_factory=FakeSDKClient, fetch=fake_fetch, **kw)


def test_options_are_restricted_and_use_our_prompt(data_dir):
    agent = make_agent(data_dir)
    o = agent.options
    assert o.strict_mcp_config is True
    assert o.tools == []                                       # no built-in tools at all
    assert sorted(o.allowed_tools) == sorted(f"mcp__study__{n}" for n in TOOLS_BY_NAME)
    assert o.system_prompt.startswith("You are Study Planner")
    assert o.setting_sources == ["project"] and o.permission_mode == "dontAsk"
    assert o.model == "claude-opus-5-5" and o.effort == "medium"
    agent.close()


def test_memory_is_rendered_into_claude_md_for_the_next_session(data_dir):
    Domain(data_dir, TODAY).memory.add("Never studies on Fridays", "preference")
    agent = make_agent(data_dir)
    md = (data_dir / "sdk_workspace" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "planner_date: 2026-11-22 (Sun)" in md and "- M1 [preference] Never studies on Fridays" in md
    assert agent.options.cwd == str(data_dir / "sdk_workspace")
    agent.close()


def test_turn_collects_tools_usage_cost_and_session_id(data_dir):
    agent = make_agent(data_dir, session="s1")
    stats = agent.run_turn("what do you remember?")
    assert stats["reply"] == "You never study on Fridays."
    assert stats["tools"] == ["recall"] and stats["model_calls"] == 2
    assert stats["tokens"] == {"input": 1012, "cache_read": 3000, "cache_write": 400, "output": 90}  # incl. Haiku
    assert stats["cost_usd"] == 0.0123
    second = agent.run_turn("and again?")
    assert second["tokens"] == {"input": 12, "cache_read": 3000, "cache_write": 400, "output": 80}   # delta only
    assert second["cost_usd"] == 0.0123 and list(second["sdk"]["tokens_by_model"]) == ["claude-opus-5-5"]
    agent.close()
    assert json.loads((data_dir / "sdk_sessions.json").read_text()) == {"s1": "sess-123"}
    resumed = make_agent(data_dir, session="s1", resume=True)
    assert resumed.options.resume == "sess-123"
    resumed.close()
    fresh = make_agent(data_dir, session="s2")
    assert fresh.options.resume is None
    fresh.close()


def test_mcp_tool_wrappers_run_shared_tools_and_flag_errors(data_dir):
    domain = Domain(data_dir, TODAY, fetch=fake_fetch)
    server, names = build_server(domain)
    assert server["type"] == "sdk" and len(names) == len(TOOLS_BY_NAME)
    sched = _wrap(TOOLS_BY_NAME["schedule_session"], domain)
    ok = asyncio.run(sched.handler({"course": "OS", "date": "2026-11-23", "start": "09:00", "hours": 2}))
    assert "is_error" not in ok and ok["content"][0]["text"].startswith("scheduled S1")
    bad = asyncio.run(sched.handler({"course": "OS", "date": "2026-11-23", "start": "10:00", "hours": 1}))
    assert bad["is_error"] is True and "overlaps S1" in bad["content"][0]["text"]


def test_every_harness_part_is_marked_in_sdk_code():
    text = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "SDK").glob("*.py"))
    tagged = {name.strip() for m in re.findall(r"# replaces: ([a-z ,]+)", text) for name in m.split(",")}
    assert set(PARTS) <= tagged, set(PARTS) - tagged
    loc = sdk_loc(ROOT / "SDK")
    assert loc["parts"]["loop"] > 0 and loc["parts"]["tools"] > 0
    assert loc["parts"]["compaction"] == 0 and loc["parts"]["caching"] == 0   # automatic in Claude Code
