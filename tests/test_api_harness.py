"""API harness end to end against a scripted fake client: loop, tools, history, memory,
context, compaction, caching, tokens."""
import json

from conftest import TODAY, FakeClient, fake_fetch, reply, text, thinking, tool_use
from API.agent import StudyAgentAPI
from API.harness.caching import mark_messages
from API.harness.history import History
from API.harness.tokens import TokenMeter
from shared.tools import Domain


def make_agent(data_dir, script, **kw):
    client = FakeClient(script)
    return StudyAgentAPI(data_dir, TODAY, client=client, fetch=fake_fetch, **kw), client


def test_loop_runs_parallel_tools_and_returns_all_results_in_one_message(data_dir):
    agent, client = make_agent(data_dir, [
        reply([thinking(), tool_use("t1", "add_deadline", {"course": "OS", "title": "A3", "due_date": "2026-12-03",
                                                           "kind": "assignment", "est_hours": 6}),
               tool_use("t2", "check_calendar", {"from_date": "2026-12-01", "to_date": "2026-12-20"})], "tool_use"),
        reply([text("Added D1. Chanukah is 12-04..12-06.")]),
    ])
    stats = agent.run_turn("add OS and check holidays")
    assert stats["reply"] == "Added D1. Chanukah is 12-04..12-06."
    assert stats["tools"] == ["add_deadline", "check_calendar"]
    assert stats["model_calls"] == 2
    second = client.requests[1]["messages"]
    results = second[-1]["content"]
    assert second[-1]["role"] == "user" and [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert not any(r.get("is_error") for r in results)
    # the thinking block is passed back unchanged (signature intact)
    assert second[-2]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig"}


def test_tool_errors_go_back_to_the_model_as_is_error(data_dir):
    agent, client = make_agent(data_dir, [
        reply([tool_use("t1", "schedule_session", {"course": "OS", "date": "tomorrow", "start": "9", "hours": 2}),
               tool_use("t2", "schedule_session", {"course": "OS"}),
               tool_use("t3", "no_such_tool", {})], "tool_use"),
        reply([text("Sorry, fixing.")]),
    ])
    agent.run_turn("schedule")
    results = client.requests[1]["messages"][-1]["content"]
    assert all(r["is_error"] for r in results)
    assert "date must be YYYY-MM-DD" in results[0]["content"]
    assert "missing required field(s): date, start, hours" in results[1]["content"]
    assert "unknown tool" in results[2]["content"]


def test_request_shape_model_effort_and_cache_breakpoints(data_dir):
    agent, client = make_agent(data_dir, [reply([text("hi")]), reply([text("again")])])
    agent.run_turn("hello")
    agent.run_turn("hello again")
    first, second = client.requests
    assert first["model"] == "claude-opus-5-5" and first["output_config"] == {"effort": "medium"}
    assert first["thinking"] == {"type": "adaptive"}
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in first["tools"]] == sorted(t["name"] for t in first["tools"])
    assert first["tools"] == second["tools"] and first["system"] == second["system"]   # stable prefix
    assert second["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    marked = [b for m in second["messages"] for b in m["content"] if "cache_control" in b]
    assert len(marked) == 1
    # the stored history itself is never mutated by caching
    assert not any("cache_control" in b for m in agent.history.messages for b in m["content"])


def test_mark_messages_skips_thinking_blocks():
    msgs = [{"role": "assistant", "content": [{"type": "text", "text": "a"}, thinking()]}]
    out = mark_messages(msgs)
    assert out[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in msgs[0]["content"][0]


def test_history_is_append_only_and_resumable(data_dir):
    agent, _ = make_agent(data_dir, [reply([text("one")]), reply([text("two")])], session="s1")
    agent.run_turn("first")
    log_path = data_dir / "history" / "s1.jsonl"
    before = log_path.read_text(encoding="utf-8")
    agent.run_turn("second")
    after = log_path.read_text(encoding="utf-8")
    assert after.startswith(before) and len(after) > len(before)
    resumed, client = make_agent(data_dir, [reply([text("three")])], session="s1", resume=True)
    assert len(resumed.history.messages) == 4
    resumed.run_turn("third")
    sent = client.requests[0]["messages"]
    assert len(sent) == 5 and sent[0]["content"][-1]["text"] == "first"
    # date was already shown in this conversation, so the resumed context does not repeat it
    assert "planner_date" not in json.dumps(sent[-1])


def test_resume_drops_unfinished_tool_turn(data_dir):
    path = data_dir / "h.jsonl"
    h = History(path)
    h.append({"role": "user", "content": [text("q")]})
    h.append({"role": "assistant", "content": [text("a")]})
    h.append({"role": "user", "content": [text("q2")]})
    h.append({"role": "assistant", "content": [tool_use("t", "recall", {})]})   # crash before results
    again = History(path, resume=True)
    assert len(again.messages) == 2
    assert len(History(path, resume=True).messages) == 2   # rollback record replays the same way


def test_context_injects_only_relevant_and_new_memory(data_dir):
    domain = Domain(data_dir, TODAY)
    domain.memory.add("Never studies on Fridays", "preference")
    domain.memory.add("Prefers dark mode in apps", "history")
    domain.store.add_deadline("Algorithms", "Final", "2026-12-14", "exam", 20)
    agent, client = make_agent(data_dir, [reply([text("ok")]), reply([text("ok")]), reply([text("ok")])])
    agent.run_turn("plan my study week")
    ctx1 = client.requests[0]["messages"][-1]["content"][0]["text"]
    assert ctx1.startswith("<context>") and "planner_date: 2026-11-22 (Sun)" in ctx1
    assert "M1 [preference] Never studies on Fridays" in ctx1 and "dark mode" not in ctx1
    assert "D1 Algorithms exam due 2026-12-14 (in 22d)" in ctx1
    agent.run_turn("and schedule another study session")
    # nothing new: no repeated memory, no unchanged digest -> no context block at all
    assert agent.history.messages[-2]["content"] == [{"type": "text", "text": "and schedule another study session"}]
    agent.domain.memory.add("Exam days are off", "decision")   # what the remember tool does
    agent.run_turn("what about exam days?")
    ctx3 = client.requests[2]["messages"][-1]["content"][0]["text"]
    assert "M3 [decision] Exam days are off" in ctx3 and "M1" not in ctx3


def test_compaction_summarizes_and_restarts_history(data_dir):
    big = {"input_tokens": 500, "output_tokens": 10, "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 600}
    agent, client = make_agent(data_dir, [
        reply([text("first answer")], usage=big),
        reply([text("SUMMARY: student added D1; pending: none")]),   # compaction call
        reply([text("second answer")]),
    ], compact_threshold=5000, session="s1")
    agent.run_turn("first")
    stats = agent.run_turn("second")
    compaction_req, after = client.requests[1], client.requests[2]
    assert "Compaction" in compaction_req["messages"][-1]["content"][0]["text"]
    assert compaction_req["tools"] == client.requests[0]["tools"]       # same prefix -> cache reuse
    assert len(after["messages"]) == 1
    assert "SUMMARY: student added D1" in after["messages"][0]["content"][0]["text"]
    assert stats["model_calls"] == 2                                     # compaction call is counted
    log = [json.loads(line) for line in (data_dir / "history" / "s1.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["kind"] for r in log].count("compaction") == 1
    resumed, _ = make_agent(data_dir, [], session="s1", resume=True)
    assert resumed.history.summary.startswith("SUMMARY") and len(resumed.history.messages) == 2


def test_token_meter_cost_per_turn():
    meter = TokenMeter("claude-opus-5-5")
    meter.start_turn()

    class U:
        input_tokens, output_tokens = 1_000_000, 100_000
        cache_read_input_tokens, cache_creation_input_tokens = 2_000_000, 400_000

    meter.record(U())
    t = meter.end_turn()
    # 1M*$4 + 2M*$0.20 + 0.4M*$5 + 0.1M*$20
    assert round(t["cost_usd"], 6) == 4 + 0.4 + 2 + 2
    assert meter.last_prompt_tokens == 3_400_000


def test_every_runtime_action_is_logged_with_its_file(data_dir, capsys):
    agent, _ = make_agent(data_dir, [
        reply([tool_use("t1", "recall", {"query": "friday"})], "tool_use"),
        reply([text("done")]),
    ])
    agent.run_turn("what do you remember")
    out = capsys.readouterr().out
    for name in ("agent.py", "loop.py", "tools.py", "history.py", "memory.py", "context.py", "caching.py", "tokens.py"):
        assert f"[{name}]" in out, name
