"""Domain tools shared by both harnesses.

Each ToolSpec holds a name, a description, a JSON schema, and a function
(domain, args) -> str. The function returns a compact, line-oriented string;
that output is what the model reads, so every character costs tokens.

The harnesses differ only in how they expose these specs: API/harness/tools.py
builds Messages API tool definitions and dispatches them itself, while
SDK/tools.py wraps them with @tool for an in-process MCP server.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from shared import calendar_api
from shared.memory_store import CATEGORIES, MemoryStore
from shared.store import DomainError, StudyStore, weekday


class Domain:
    """All persistent state for one student, rooted at data_dir."""

    def __init__(self, data_dir: Path, today: str, fetch: calendar_api.Fetcher | None = None):
        self.data_dir = Path(data_dir)
        self.today = today
        self.store = StudyStore(self.data_dir, today)
        self.memory = MemoryStore(self.data_dir, today)
        self.fetch = fetch or calendar_api.http_fetch


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict
    fn: Callable[[Domain, dict], str]


def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


DATE = {"type": "string", "description": "YYYY-MM-DD"}


# ----- formatting helpers (compact output) ---------------------------------
def _deadline_line(domain: Domain, d: dict) -> str:
    planned = domain.store.planned_hours(d["course"])
    return (f"{d['id']} {d['course']} {d['kind']} \"{d['title']}\" due {d['due']} ({weekday(d['due'])}, "
            f"in {domain.store.days_until(d['due'])}d) est {d['est_hours']:g}h planned {planned:g}h")


def _session_line(s: dict) -> str:
    topic = f" - {s['topic']}" if s.get("topic") else ""
    return f"{s['id']} {s['date']} {weekday(s['date'])} {s['start']}-{s['end']} {s['course']}{topic}"


def _fact_line(f: dict) -> str:
    status = "" if f["status"] == "active" else f" (superseded by {f['superseded_by']})"
    return f"{f['id']} [{f['category']}] {f['text']}{status}"


# ----- tool implementations ------------------------------------------------
def add_deadline(domain: Domain, a: dict) -> str:
    d = domain.store.add_deadline(a["course"], a["title"], a["due_date"], a["kind"], a.get("est_hours", 0))
    return "added " + _deadline_line(domain, d)


def list_deadlines(domain: Domain, a: dict) -> str:
    items = domain.store.list_deadlines(a.get("course"), a.get("before"))
    if not items:
        return "no deadlines"
    return "\n".join(_deadline_line(domain, d) for d in items)


def schedule_session(domain: Domain, a: dict) -> str:
    s = domain.store.add_session(a["course"], a["date"], a["start"], a["hours"], a.get("topic", ""))
    return "scheduled " + _session_line(s)


def cancel_session(domain: Domain, a: dict) -> str:
    s = domain.store.cancel_session(a["session_id"])
    return "cancelled " + _session_line(s)


def list_sessions(domain: Domain, a: dict) -> str:
    limit = a.get("limit", 20)
    items = domain.store.list_sessions(a.get("from_date"), a.get("to_date"), a.get("course"))
    if not items:
        return "no sessions"
    lines = [_session_line(s) for s in items[:limit]]
    if len(items) > limit:
        lines.append(f"... {len(items) - limit} more (narrow the range)")
    return "\n".join(lines)


def check_calendar(domain: Domain, a: dict) -> str:
    found = calendar_api.holidays(a["from_date"], a["to_date"], domain.fetch)
    head = f"Israel holidays {a['from_date']}..{a['to_date']}:"
    if not found:
        return head + " none"
    lines = []
    for h in found:
        span = h["from"] if h["from"] == h["to"] else f"{h['from']}..{h['to']}"
        lines.append(f"{span} {h['name']} [{h['kind']}]")
    return head + "\n" + "\n".join(lines)


def remember(domain: Domain, a: dict) -> str:
    f = domain.memory.add(a["fact"], a["category"], a.get("replaces"))
    suffix = f" (retired {a['replaces']})" if a.get("replaces") else ""
    return f"saved {_fact_line(f)}{suffix}"


def recall(domain: Domain, a: dict) -> str:
    facts = domain.memory.search(a.get("query", ""), a.get("limit", 5), a.get("include_superseded", False))
    if not facts:
        return "no matching memory"
    return "\n".join(_fact_line(f) for f in facts)


TOOLS: list[ToolSpec] = [
    ToolSpec(
        "add_deadline",
        "Add an exam, assignment or project deadline for a course.",
        _obj({
            "course": {"type": "string"},
            "title": {"type": "string", "description": "e.g. 'Final exam', 'Assignment 3'"},
            "due_date": DATE,
            "kind": {"type": "string", "enum": ["exam", "assignment", "project"]},
            "est_hours": {"type": "number", "description": "estimated study/work hours needed"},
        }, ["course", "title", "due_date", "kind"]),
        add_deadline,
    ),
    ToolSpec(
        "list_deadlines",
        "List deadlines sorted by due date, with hours already planned per course.",
        _obj({"course": {"type": "string"}, "before": DATE}, []),
        list_deadlines,
    ),
    ToolSpec(
        "schedule_session",
        "Schedule a study session. Fails on overlap with an existing session or a past date.",
        _obj({
            "course": {"type": "string"},
            "date": DATE,
            "start": {"type": "string", "description": "HH:MM, 24h"},
            "hours": {"type": "number", "description": "duration, multiple of 0.5"},
            "topic": {"type": "string"},
        }, ["course", "date", "start", "hours"]),
        schedule_session,
    ),
    ToolSpec(
        "cancel_session",
        "Cancel a scheduled study session by id (e.g. S4).",
        _obj({"session_id": {"type": "string"}}, ["session_id"]),
        cancel_session,
    ),
    ToolSpec(
        "list_sessions",
        "List scheduled study sessions, optionally filtered by date range and course.",
        _obj({
            "from_date": DATE, "to_date": DATE, "course": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        }, []),
        list_sessions,
    ),
    ToolSpec(
        "check_calendar",
        "Look up Israeli holidays in a date range (live Hebcal API). Use before planning around holidays.",
        _obj({"from_date": DATE, "to_date": DATE}, ["from_date", "to_date"]),
        check_calendar,
    ),
    ToolSpec(
        "remember",
        "Save one durable fact about the student to long-term memory. "
        "Set replaces=<old id> when the student changes a saved fact; the old one is retired.",
        _obj({
            "fact": {"type": "string", "description": "short, third person, e.g. 'Never studies on Fridays'"},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "replaces": {"type": "string", "description": "id of the fact this one supersedes, e.g. M2"},
        }, ["fact", "category"]),
        remember,
    ),
    ToolSpec(
        "recall",
        "Search long-term memory by keywords. Empty query returns the newest facts.",
        _obj({
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            "include_superseded": {"type": "boolean"},
        }, []),
        recall,
    ),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def run_tool(domain: Domain, name: str, args: dict) -> str:
    """Execute a domain tool. Raises DomainError for problems the model should fix."""
    spec = TOOLS_BY_NAME.get(name)
    if spec is None:
        raise DomainError(f"unknown tool {name!r}")
    return spec.fn(domain, args)
