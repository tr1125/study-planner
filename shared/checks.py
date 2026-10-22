"""Pass/fail checks for scenario.json.

Most checks read the persisted state (state.json / memory.json snapshots taken
after each turn), not the reply text, so they verify what the agent actually
did rather than what it claimed.
"""
from __future__ import annotations

import re

from shared.store import parse_time, weekday


def _course_matches(course: str, keys: list[str]) -> bool:
    c = course.lower()
    words = set(re.findall(r"[a-z0-9]+", c))
    return any(k in words or (len(k) > 3 and k in c) for k in (k.lower() for k in keys))


def _text_has_any(text: str, options: list[str]) -> bool:
    t = text.lower()
    return any(o.lower() in t for o in options)


def _snapshot(ctx: dict, after_turn: int | None) -> dict:
    snaps = ctx["snapshots"]
    return snaps[-1] if after_turn is None else snaps[after_turn - 1]


def deadlines_saved(spec: dict, ctx: dict) -> tuple[bool, str]:
    deadlines = _snapshot(ctx, spec.get("after_turn"))["state"].get("deadlines", [])
    missing = []
    for exp in spec["expect"]:
        ok = any(_course_matches(d["course"], exp["course_any"]) and d["due"] == exp["due"] for d in deadlines)
        if not ok:
            missing.append(f"{exp['course_any'][0]}@{exp['due']}")
    return not missing, f"{len(deadlines)} deadlines; missing: {missing or 'none'}"


def memory_active(spec: dict, ctx: dict) -> tuple[bool, str]:
    facts = [f for f in _snapshot(ctx, spec.get("after_turn"))["memory"].get("facts", []) if f["status"] == "active"]
    missing = [g[0] for g in spec["groups"] if not any(_text_has_any(f["text"], g) for f in facts)]
    return not missing, f"{len(facts)} active facts; missing: {missing or 'none'}"


def sessions(spec: dict, ctx: dict) -> tuple[bool, str]:
    snap = _snapshot(ctx, spec.get("after_turn"))
    found = [
        s for s in snap["state"].get("sessions", [])
        if _course_matches(s["course"], spec["course_any"]) and spec["from"] <= s["date"] <= spec["to"]
    ]
    rules = spec.get("rules", {})
    violations = []
    for s in found:
        start, end = parse_time(s["start"]), parse_time(s["end"])
        if weekday(s["date"]) in rules.get("no_weekdays", []):
            violations.append(f"{s['id']} on {weekday(s['date'])}")
        if "start_from" in rules and start < parse_time(rules["start_from"]):
            violations.append(f"{s['id']} starts {s['start']}")
        if "end_by" in rules and end > parse_time(rules["end_by"]):
            violations.append(f"{s['id']} ends {s['end']}")
        if "max_hours" in rules and s["hours"] > rules["max_hours"]:
            violations.append(f"{s['id']} is {s['hours']}h")
    enough = len(found) >= spec.get("min_count", 1)
    return enough and not violations, f"{len(found)} matching sessions; violations: {violations or 'none'}"


def no_session_on(spec: dict, ctx: dict) -> tuple[bool, str]:
    snap = _snapshot(ctx, spec.get("after_turn"))
    hits = [s["id"] for s in snap["state"].get("sessions", []) if s["date"] == spec["date"]]
    return not hits, f"sessions on {spec['date']}: {hits or 'none'}"


def tool_used(spec: dict, ctx: dict) -> tuple[bool, str]:
    turns = [t for t in ctx["turns"] if t["turn"] in spec["turns"]]
    used = [t["turn"] for t in turns if spec["tool"] in t["tools"]]
    return bool(used), f"{spec['tool']} used in turns {used or 'none'}"


def reply_mentions(spec: dict, ctx: dict) -> tuple[bool, str]:
    reply = next(t["reply"] for t in ctx["turns"] if t["turn"] == spec["turn"])
    missing = [g[0] for g in spec["groups"] if not _text_has_any(reply, g)]
    return not missing, f"missing: {missing or 'none'}"


def memory_superseded(spec: dict, ctx: dict) -> tuple[bool, str]:
    facts = _snapshot(ctx, spec.get("after_turn"))["memory"].get("facts", [])
    by_id = {f["id"]: f for f in facts}
    pairs = [
        (f["id"], f["superseded_by"]) for f in facts
        if f["status"] == "superseded" and _text_has_any(f["text"], spec["old_any"])
        and f["superseded_by"] in by_id and by_id[f["superseded_by"]]["status"] == "active"
        and _text_has_any(by_id[f["superseded_by"]]["text"], spec["new_any"])
    ]
    still_active = [f["id"] for f in facts if f["status"] == "active" and _text_has_any(f["text"], spec.get("must_not_be_active", []))]
    kept = all(any(f["status"] == "active" and _text_has_any(f["text"], g) for f in facts) for g in spec.get("keep_active", []))
    ok = bool(pairs) and not still_active and kept
    return ok, f"superseded pairs {pairs or 'none'}; stale active {still_active or 'none'}; kept others {kept}"


def no_overlaps(spec: dict, ctx: dict) -> tuple[bool, str]:
    ss = sorted(_snapshot(ctx, spec.get("after_turn"))["state"].get("sessions", []), key=lambda s: (s["date"], s["start"]))
    clashes = [
        f"{a['id']}/{b['id']}" for a, b in zip(ss, ss[1:])
        if a["date"] == b["date"] and parse_time(b["start"]) < parse_time(a["end"])
    ]
    return not clashes, f"{len(ss)} sessions; overlaps: {clashes or 'none'}"


CHECKS = {f.__name__: f for f in (
    deadlines_saved, memory_active, sessions, no_session_on, tool_used,
    reply_mentions, memory_superseded, no_overlaps,
)}


def run_checks(specs: list[dict], ctx: dict) -> list[dict]:
    results = []
    for spec in specs:
        try:
            passed, detail = CHECKS[spec["type"]](spec, ctx)
        except Exception as exc:  # a broken check must not hide the others
            passed, detail = False, f"check error: {exc!r}"
        results.append({"id": spec["id"], "description": spec["description"], "passed": passed, "detail": detail})
    return results
