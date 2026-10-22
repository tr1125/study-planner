"""Domain layer: store, memory, external calendar tool, compact tool output."""
import pytest

from conftest import TODAY, fake_fetch
from shared.calendar_api import holidays
from shared.memory_store import MemoryStore
from shared.store import DomainError, StudyStore
from shared.tools import Domain, run_tool


def test_sessions_reject_overlap_and_past(data_dir):
    store = StudyStore(data_dir, TODAY)
    store.add_session("OS", "2026-11-23", "09:00", 2)
    with pytest.raises(DomainError, match="overlaps S1"):
        store.add_session("Algorithms", "2026-11-23", "10:30", 1)
    with pytest.raises(DomainError, match="in the past"):
        store.add_session("OS", "2026-11-01", "09:00", 1)
    with pytest.raises(DomainError, match="multiple of 0.5"):
        store.add_session("OS", "2026-11-24", "09:00", 1.2)
    s = store.add_session("OS", "2026-11-23", "11:00", 1)   # touching, not overlapping
    assert s["end"] == "12:00"


def test_store_persists_between_instances(data_dir):
    StudyStore(data_dir, TODAY).add_deadline("Algorithms", "Final", "2026-12-14", "exam", 20)
    again = StudyStore(data_dir, TODAY)
    assert [d["id"] for d in again.list_deadlines()] == ["D1"]


def test_memory_supersede_keeps_history(data_dir):
    mem = MemoryStore(data_dir, TODAY)
    old = mem.add("Never studies on Fridays", "preference")
    mem.add("Max 3 hours per session", "constraint")
    new = mem.add("Fridays are fine for studying", "preference", replaces=old["id"])
    reloaded = MemoryStore(data_dir, TODAY)
    assert reloaded.get("M1")["status"] == "superseded"
    assert reloaded.get("M1")["superseded_by"] == new["id"]
    assert [f["id"] for f in reloaded.active()] == ["M2", "M3"]
    with pytest.raises(DomainError, match="already superseded"):
        reloaded.add("Another", "preference", replaces="M1")


def test_memory_search_ranks_by_keywords(data_dir):
    mem = MemoryStore(data_dir, TODAY)
    mem.add("Focuses best in the mornings 08:00-12:00", "preference")
    mem.add("Max 3 hours per session", "constraint")
    assert mem.search("morning focus")[0]["id"] == "M1"
    assert mem.search("long sessions")[0]["id"] == "M2"


def test_calendar_compacts_hebcal_payload():
    fake_fetch.urls.clear()
    found = holidays("2026-12-01", "2026-12-20", fetch=fake_fetch)
    # Chanukah days merged into one range despite Rosh Chodesh in between; parashat dropped
    assert found == [
        {"from": "2026-12-04", "to": "2026-12-06", "name": "Chanukah", "kind": "major"},
        {"from": "2026-12-10", "to": "2026-12-10", "name": "Rosh Chodesh Tevet", "kind": "roshchodesh"},
    ]
    assert "i=on" in fake_fetch.urls[0] and "start=2026-12-01" in fake_fetch.urls[0]


def test_calendar_errors_become_domain_errors():
    def down(url):
        raise OSError("network down")
    with pytest.raises(DomainError, match="unavailable"):
        holidays("2026-12-01", "2026-12-02", fetch=down)
    with pytest.raises(DomainError, match="range too long"):
        holidays("2026-01-01", "2026-12-31", fetch=fake_fetch)


def test_tool_output_is_compact(data_dir):
    domain = Domain(data_dir, TODAY, fetch=fake_fetch)
    run_tool(domain, "add_deadline", {"course": "Algorithms", "title": "Final", "due_date": "2026-12-14",
                                      "kind": "exam", "est_hours": 20})
    run_tool(domain, "schedule_session", {"course": "Algorithms", "date": "2026-11-23", "start": "09:00", "hours": 3})
    out = run_tool(domain, "list_deadlines", {})
    assert out == 'D1 Algorithms exam "Final" due 2026-12-14 (Mon, in 22d) est 20h planned 3h'
    cal = run_tool(domain, "check_calendar", {"from_date": "2026-12-01", "to_date": "2026-12-20"})
    assert len(cal) < 150 and "2026-12-04..2026-12-06 Chanukah [major]" in cal
