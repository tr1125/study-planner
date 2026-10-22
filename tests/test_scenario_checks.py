"""scenario.json is well formed, and its checks pass/fail on synthetic state as intended."""
from conftest import ROOT
from shared.checks import CHECKS, run_checks
from shared.loc import api_loc
from shared.scenario import load_scenario, summarize

SCENARIO = load_scenario(ROOT / "scenario.json")


def _turn(n, reply="", tools=()):
    return {"turn": n, "reply": reply, "tools": list(tools),
            "tokens": {"input": 10, "cache_read": 90, "cache_write": 0, "output": 5},
            "model_calls": 1, "cost_usd": 0.001, "seconds": 1.0}


def _session(id_, course, day, start, end, hours):
    return {"id": id_, "course": course, "date": day, "start": start, "end": end, "hours": hours}


def _fact(id_, text, status="active", superseded_by=None):
    return {"id": id_, "text": text, "category": "preference", "status": status, "superseded_by": superseded_by}


def good_run():
    deadlines = [{"course": "Algorithms", "due": "2026-12-14"}, {"course": "Operating Systems", "due": "2026-12-03"},
                 {"course": "Databases", "due": "2026-12-21"}]
    facts = [_fact("M1", "Never studies on Fridays"), _fact("M2", "Focuses best in the mornings 08:00-12:00"),
             _fact("M3", "Sessions of max 3 hours")]
    os_ = [_session("S1", "OS", "2026-11-23", "09:00", "12:00", 3), _session("S2", "OS", "2026-11-25", "08:00", "10:00", 2)]
    algo = [_session(f"S{i}", "Algorithms", d, "09:00", "12:00", 3)
            for i, d in ((3, "2026-11-29"), (4, "2026-11-30"), (5, "2026-12-01"))]
    final_facts = [_fact("M1", "Never studies on Fridays", "superseded", "M4"), *facts[1:],
                   _fact("M4", "Fridays are fine for studying")]
    snap = lambda s, f: {"state": {"deadlines": deadlines, "sessions": s}, "memory": {"facts": f}}  # noqa: E731
    snaps = [snap([], []), snap([], facts), snap(os_, facts), snap(os_, facts), snap(os_ + algo, facts),
             snap(os_ + algo, facts),
             snap(os_ + algo + [_session("S6", "Algorithms", "2026-12-11", "09:00", "12:00", 3)], final_facts)]
    turns = [_turn(i) for i in range(1, 8)]
    turns[2]["tools"] = ["check_calendar", "schedule_session"]
    turns[3]["reply"] = "You never study on Fridays, prefer mornings 08:00-12:00, and max 3 hours."
    return {"turns": turns, "snapshots": snaps}


def test_scenario_shape():
    assert len(SCENARIO["sessions"]) == 2
    assert 6 <= sum(len(s["turns"]) for s in SCENARIO["sessions"]) <= 8
    assert len(SCENARIO["checks"]) >= 5
    assert all(c["type"] in CHECKS for c in SCENARIO["checks"])
    state_based = [c for c in SCENARIO["checks"] if c["type"] not in ("reply_mentions", "tool_used")]
    assert len(state_based) > len(SCENARIO["checks"]) / 2


def test_all_checks_pass_on_a_good_run():
    results = run_checks(SCENARIO["checks"], good_run())
    assert all(r["passed"] for r in results), [r for r in results if not r["passed"]]


def test_checks_catch_bad_behaviour():
    ctx = good_run()
    ctx["snapshots"][5]["state"]["sessions"] = ctx["snapshots"][5]["state"]["sessions"] + [
        _session("S9", "Algorithms", "2026-12-11", "09:00", "14:00", 5)]               # executed the conflict
    ctx["snapshots"][2] = {"state": {**ctx["snapshots"][2]["state"], "sessions": [
        _session("S1", "OS", "2026-11-27", "09:00", "11:00", 2)]}, "memory": ctx["snapshots"][2]["memory"]}  # Friday
    ctx["snapshots"][6]["memory"]["facts"][0]["status"] = "active"                     # never superseded
    ctx["turns"][2]["tools"] = []                                                      # no external call
    failed = {r["id"] for r in run_checks(SCENARIO["checks"], ctx) if not r["passed"]}
    assert failed == {"conflict_not_executed", "preference_updated", "external_tool_used", "os_sessions_follow_prefs"}


def test_totals_and_loc():
    totals = summarize(good_run()["turns"])
    assert totals["cache_hit_pct"] == 90.0 and totals["model_calls"] == 7
    loc = api_loc(ROOT / "API")
    assert set(loc["parts"]) == {"loop", "tools", "history", "memory", "context", "compaction", "caching", "tokens"}
    assert all(v > 0 for v in loc["parts"].values())
