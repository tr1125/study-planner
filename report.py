"""Regenerate the measured tables in REPORT.md from results/api.json and results/sdk.json.

  python report.py

Only the blocks between <!-- AUTO:name --> and <!-- /AUTO:name --> are rewritten;
the written analysis around them is left alone.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from shared.loc import PARTS, api_loc, sdk_loc  # noqa: E402

PENDING = "—"
NOT_MEASURED = "לא נמדד"
API_LABEL = "API"


def load(name: str) -> dict | None:
    path = ROOT / "results" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def is_estimate(r: dict | None) -> bool:
    return bool(r and r.get("kind", "").startswith("ESTIMATE"))


def fmt_int(v) -> str:
    return f"{v:,}" if isinstance(v, int) else PENDING


def summary_table(api: dict | None, sdk: dict | None) -> str:
    def row(label, fn):
        cells = [fn(r) if r else PENDING for r in (api, sdk)]
        return f"| {label} | {cells[0]} | {cells[1]} |"

    tot = lambda r: r["totals"]  # noqa: E731
    rows = [
        f"| מדד | {API_LABEL} | SDK |",
        "|---|---:|---:|",
        row("input (לא מ-cache)", lambda r: fmt_int(tot(r)["tokens"]["input"])),
        row("cache read", lambda r: fmt_int(tot(r)["tokens"]["cache_read"])),
        row("cache write", lambda r: fmt_int(tot(r)["tokens"]["cache_write"])),
        row("output", lambda r: fmt_int(tot(r)["tokens"]["output"])),
        row("סה\"כ טוקני prompt", lambda r: fmt_int(tot(r)["prompt_tokens"])),
        row("אחוז cache (read / prompt)", lambda r: f"{tot(r)['cache_hit_pct']}%"),
        row("קריאות למודל", lambda r: str(tot(r)["model_calls"])),
        row("קריאות לכלים", lambda r: str(tot(r)["tool_calls"])),
        row("עלות (USD)", lambda r: f"${tot(r)['cost_usd']:.4f}"),
        row("זמן (שניות)", lambda r: NOT_MEASURED if is_estimate(r) else f"{tot(r)['seconds']:.0f}"),
        row("בדיקות שעברו", lambda r: NOT_MEASURED if is_estimate(r) else r["checks_passed"]),
    ]
    return "\n".join(rows)


def turns_table(api: dict | None, sdk: dict | None) -> str:
    lines = [f"| תור | סשן | {API_LABEL}: prompt / out / קריאות / $ | SDK: prompt / out / קריאות / $ | כלים (SDK) |",
             "|---:|---|---|---|---|"]
    n = max(len(r["turns"]) for r in (api, sdk) if r) if (api or sdk) else 0

    def cell(r, i):
        if not r or i >= len(r["turns"]):
            return PENDING
        t = r["turns"][i]
        p = t["tokens"]["input"] + t["tokens"]["cache_read"] + t["tokens"]["cache_write"]
        return f"{p:,} / {t['tokens']['output']:,} / {t['model_calls']} / ${t['cost_usd']:.4f}"

    for i in range(n):
        ref = (sdk or api)["turns"][i]
        tools = ", ".join(sdk["turns"][i]["tools"]) if sdk and i < len(sdk["turns"]) else PENDING
        lines.append(f"| {ref['turn']} | {ref['session']} | {cell(api, i)} | {cell(sdk, i)} | {tools or '-'} |")
    return "\n".join(lines)


def checks_table(api: dict | None, sdk: dict | None) -> str:
    ref = (sdk or api)
    if not ref:
        return "(no results yet)"
    lines = [f"| בדיקה | מה נבדק | {API_LABEL} | SDK |", "|---|---|:-:|:-:|"]
    for i, c in enumerate(ref["checks"]):
        def mark(r):
            if not r or is_estimate(r):
                return NOT_MEASURED if is_estimate(r) else PENDING
            return "✅" if r["checks"][i]["passed"] else "❌"
        lines.append(f"| `{c['id']}` | {c['description']} | {mark(api)} | {mark(sdk)} |")
    return "\n".join(lines)


def loc_table() -> str:
    a, s = api_loc(ROOT / "API"), sdk_loc(ROOT / "SDK")
    lines = ["| חלק ב-harness | API (קובץ ב-harness/) | SDK (שורות `# replaces:`) |", "|---|---:|---:|"]
    for p in PARTS:
        lines.append(f"| {p} | {a['parts'][p]} | {s['parts'][p]} |")
    lines.append(f"| **סה\"כ חלקי harness** | **{sum(a['parts'].values())}** | **{sum(s['parts'].values())}** |")
    other_api = ", ".join(f"{k} {v}" for k, v in a["other_files"].items())
    other_sdk = ", ".join(f"{k} {v}" for k, v in s["files"].items())
    lines.append(f"| קבצי חיווט (לא harness) | {other_api} | סה\"כ קבצי SDK: {other_sdk} |")
    lines.append(f"| **סה\"כ קוד בגרסה** | **{a['total']}** | **{s['total']}** |")
    return "\n".join(lines)


def main() -> None:
    global API_LABEL
    sys.stdout.reconfigure(encoding="utf-8")
    api, sdk = load("api"), load("sdk")
    if api is None and (api := load("api_estimate")):
        API_LABEL = "API (הערכה*)"
    blocks = {
        "summary": summary_table(api, sdk),
        "turns": turns_table(api, sdk),
        "checks": checks_table(api, sdk),
        "loc": loc_table(),
    }
    path = ROOT / "REPORT.md"
    text = path.read_text(encoding="utf-8")
    for name, body in blocks.items():
        pattern = re.compile(rf"(<!-- AUTO:{name} -->).*?(<!-- /AUTO:{name} -->)", re.S)
        if not pattern.search(text):
            raise SystemExit(f"REPORT.md has no AUTO:{name} block")
        text = pattern.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(2)}", text)
    path.write_bytes(text.encode("utf-8"))   # keep LF line endings on Windows
    print(f"REPORT.md updated (api: {API_LABEL if api else 'missing'}, sdk: {'yes' if sdk else 'missing'})")


if __name__ == "__main__":
    main()
