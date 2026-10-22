"""Domain state: deadlines and study sessions, persisted as one JSON file.

Both harnesses (API/ and SDK/) read and write this exact store, so the
scenario checks can inspect the same state regardless of which harness ran.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class DomainError(ValueError):
    """A bad request from the model (invalid date, overlap, unknown id...).

    Harnesses turn this into an error tool_result the model can read and fix.
    """


def parse_date(value: str, field: str = "date") -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise DomainError(f"{field} must be YYYY-MM-DD, got {value!r}") from None


def parse_time(value: str, field: str = "start") -> int:
    """'09:30' -> minutes since midnight."""
    try:
        t = datetime.strptime(value, "%H:%M")
    except (TypeError, ValueError):
        raise DomainError(f"{field} must be HH:MM (24h), got {value!r}") from None
    return t.hour * 60 + t.minute


def fmt_minutes(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def weekday(d: str | date) -> str:
    if isinstance(d, str):
        d = parse_date(d)
    return WEEKDAYS[d.weekday()]


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


class StudyStore:
    """Deadlines (exams/assignments) and scheduled study sessions."""

    def __init__(self, data_dir: Path, today: str):
        self.path = Path(data_dir) / "state.json"
        self.today = parse_date(today, "today")
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"next_id": {"D": 1, "S": 1}, "deadlines": [], "sessions": []}

    def _save(self) -> None:
        write_json_atomic(self.path, self.data)

    def _new_id(self, prefix: str) -> str:
        n = self.data["next_id"][prefix]
        self.data["next_id"][prefix] = n + 1
        return f"{prefix}{n}"

    # ----- deadlines -------------------------------------------------------
    def add_deadline(self, course: str, title: str, due: str, kind: str, est_hours: float) -> dict:
        due_d = parse_date(due, "due_date")
        if kind not in ("exam", "assignment", "project"):
            raise DomainError("kind must be exam, assignment or project")
        if not course.strip():
            raise DomainError("course must not be empty")
        if est_hours < 0 or est_hours > 200:
            raise DomainError("est_hours must be between 0 and 200")
        for d in self.data["deadlines"]:
            if d["course"].lower() == course.lower() and d["title"].lower() == title.lower():
                raise DomainError(f"deadline already exists as {d['id']}; use that id")
        item = {
            "id": self._new_id("D"),
            "course": course.strip(),
            "title": title.strip(),
            "kind": kind,
            "due": due_d.isoformat(),
            "est_hours": est_hours,
        }
        self.data["deadlines"].append(item)
        self._save()
        return item

    def list_deadlines(self, course: str | None = None, before: str | None = None) -> list[dict]:
        before_d = parse_date(before, "before") if before else None
        out = []
        for d in self.data["deadlines"]:
            if course and course.lower() not in d["course"].lower():
                continue
            if before_d and parse_date(d["due"]) > before_d:
                continue
            out.append(d)
        return sorted(out, key=lambda d: d["due"])

    def planned_hours(self, course: str) -> float:
        return sum(s["hours"] for s in self.data["sessions"] if s["course"].lower() == course.lower())

    # ----- sessions --------------------------------------------------------
    def add_session(self, course: str, day: str, start: str, hours: float, topic: str = "") -> dict:
        day_d = parse_date(day, "date")
        start_m = parse_time(start)
        if day_d < self.today:
            raise DomainError(f"{day} is in the past (planner date is {self.today.isoformat()})")
        if not (0.5 <= hours <= 8) or (hours * 2) != int(hours * 2):
            raise DomainError("hours must be a multiple of 0.5 between 0.5 and 8")
        end_m = start_m + int(hours * 60)
        if end_m > 24 * 60:
            raise DomainError("session must end before midnight")
        for s in self.data["sessions"]:
            if s["date"] != day_d.isoformat():
                continue
            s_start = parse_time(s["start"])
            s_end = s_start + int(s["hours"] * 60)
            if start_m < s_end and s_start < end_m:
                raise DomainError(
                    f"overlaps {s['id']} ({s['course']} {s['start']}-{fmt_minutes(s_end)} on {s['date']})"
                )
        item = {
            "id": self._new_id("S"),
            "course": course.strip(),
            "date": day_d.isoformat(),
            "start": fmt_minutes(start_m),
            "end": fmt_minutes(end_m),
            "hours": hours,
            "topic": topic.strip(),
        }
        self.data["sessions"].append(item)
        self._save()
        return item

    def cancel_session(self, session_id: str) -> dict:
        for i, s in enumerate(self.data["sessions"]):
            if s["id"] == session_id:
                removed = self.data["sessions"].pop(i)
                self._save()
                return removed
        raise DomainError(f"no session with id {session_id!r}")

    def list_sessions(self, start: str | None = None, end: str | None = None, course: str | None = None) -> list[dict]:
        start_d = parse_date(start, "from_date") if start else None
        end_d = parse_date(end, "to_date") if end else None
        out = []
        for s in self.data["sessions"]:
            d = parse_date(s["date"])
            if start_d and d < start_d:
                continue
            if end_d and d > end_d:
                continue
            if course and course.lower() not in s["course"].lower():
                continue
            out.append(s)
        return sorted(out, key=lambda s: (s["date"], s["start"]))

    def days_until(self, iso: str) -> int:
        return (parse_date(iso) - self.today).days
