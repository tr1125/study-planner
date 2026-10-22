"""External tool backend: Israeli holidays from the public Hebcal REST API.

No API key needed. The raw Hebcal response is ~1 KB per day (memo text,
leyning, links); this module compresses it to one short line per holiday,
merging multi-day holidays into a single date range.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from shared.store import DomainError, parse_date

HEBCAL_URL = "https://www.hebcal.com/hebcal"
KEEP_CATEGORIES = {"holiday", "roshchodesh"}
MAX_RANGE_DAYS = 120

Fetcher = Callable[[str], dict]


def http_fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "study-planner-tamar/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def build_url(start: str, end: str) -> str:
    params = {
        "v": "1", "cfg": "json", "i": "on",   # Israel schedule
        "maj": "on", "min": "on", "mod": "on", "nx": "on",
        "start": start, "end": end,
    }
    return f"{HEBCAL_URL}?{urllib.parse.urlencode(params)}"


def holidays(start: str, end: str, fetch: Fetcher = http_fetch) -> list[dict]:
    """Return [{'from', 'to', 'name', 'kind'}] for holidays between start and end."""
    s, e = parse_date(start, "from_date"), parse_date(end, "to_date")
    if e < s:
        raise DomainError("to_date is before from_date")
    if (e - s).days > MAX_RANGE_DAYS:
        raise DomainError(f"range too long (max {MAX_RANGE_DAYS} days)")
    try:
        payload = fetch(build_url(s.isoformat(), e.isoformat()))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise DomainError(f"holiday service unavailable ({exc.__class__.__name__}); try again later") from None

    merged: list[dict] = []
    last_by_name: dict[str, dict] = {}
    items = sorted(payload.get("items", []), key=lambda i: i.get("date", ""))
    for item in items:
        if item.get("category") not in KEEP_CATEGORIES:
            continue
        name = item["title"].split(":")[0].strip()          # "Chanukah: 3 Candles" -> "Chanukah"
        day = item["date"][:10]
        prev = last_by_name.get(name)
        # Rosh Chodesh can fall inside Chanukah, so merge by name, not by neighbour.
        if prev and (parse_date(day) - parse_date(prev["to"])).days <= 1:
            prev["to"] = day
            continue
        entry = {"from": day, "to": day, "name": name, "kind": item.get("subcat") or item["category"]}
        merged.append(entry)
        last_by_name[name] = entry
    return merged
