"""Scenario runner shared by API/main.py and SDK/main.py.

A harness plugs in through a factory: make_agent(session_name) -> agent, where
agent.run_turn(text) returns a dict with reply / tokens / model_calls / tools /
cost_usd, and agent.close() releases resources. Every session gets a *new*
agent instance, which has to load whatever it needs from disk.
"""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Callable, Protocol

from shared.checks import run_checks
from shared.prompts import EFFORT, MODEL


class Agent(Protocol):
    def run_turn(self, text: str) -> dict: ...
    def close(self) -> None: ...


def load_scenario(path: Path) -> dict:
    scenario = json.loads(Path(path).read_text(encoding="utf-8"))
    turns = [t for s in scenario["sessions"] for t in s["turns"]]
    if not 6 <= len(turns) <= 8 or len(scenario["sessions"]) != 2:
        raise ValueError("scenario must have 6-8 turns across exactly 2 sessions")
    return scenario


def reset_dir(path: Path) -> Path:
    """Every run starts from a clean state."""
    path = Path(path)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def snapshot(data_dir: Path) -> dict:
    return {"state": _read_json(data_dir / "state.json"), "memory": _read_json(data_dir / "memory.json")}


def _versions() -> dict:
    out = {}
    for pkg in ("anthropic", "claude-agent-sdk"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = None
    try:
        from claude_agent_sdk._cli_version import __cli_version__
        out["claude-code-cli (bundled)"] = __cli_version__
    except ImportError:
        pass
    return out


def summarize(turns: list[dict]) -> dict:
    keys = ("input", "cache_read", "cache_write", "output")
    tok = {k: sum(t["tokens"][k] for t in turns) for k in keys}
    prompt_total = tok["input"] + tok["cache_read"] + tok["cache_write"]
    return {
        "tokens": tok,
        "prompt_tokens": prompt_total,
        "cache_hit_pct": round(100 * tok["cache_read"] / prompt_total, 1) if prompt_total else 0.0,
        "model_calls": sum(t["model_calls"] for t in turns),
        "tool_calls": sum(len(t["tools"]) for t in turns),
        "cost_usd": round(sum(t["cost_usd"] for t in turns), 6),
        "seconds": round(sum(t["seconds"] for t in turns), 2),
    }


def run_scenario(
    scenario: dict,
    harness: str,
    data_dir: Path,
    make_agent: Callable[[str], Agent],
    loc: dict,
    out_path: Path,
) -> dict:
    turns: list[dict] = []
    snapshots: list[dict] = []
    n = 0
    for session in scenario["sessions"]:
        print(f"\n=== {harness}: session {session['name']} (new agent instance) ===")
        agent = make_agent(session["name"])
        try:
            for text in session["turns"]:
                n += 1
                print(f"\n--- turn {n} [{session['name']}] user: {text}")
                t0 = time.perf_counter()
                stats = agent.run_turn(text)
                seconds = round(time.perf_counter() - t0, 2)
                record = {"turn": n, "session": session["name"], "prompt": text, **stats, "seconds": seconds}
                turns.append(record)
                snapshots.append(snapshot(data_dir))
                print(f"--- turn {n} assistant: {stats['reply']}")
                print(f"--- turn {n} stats: tokens={stats['tokens']} calls={stats['model_calls']} "
                      f"tools={stats['tools']} cost=${stats['cost_usd']:.4f} time={seconds}s")
        finally:
            agent.close()

    checks = run_checks(scenario["checks"], {"turns": turns, "snapshots": snapshots})
    passed = sum(c["passed"] for c in checks)
    result = {
        "harness": harness,
        "model": MODEL,
        "effort": EFFORT,
        "planner_date": scenario["planner_date"],
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "versions": _versions(),
        "turns": turns,
        "totals": summarize(turns),
        "checks": checks,
        "checks_passed": f"{passed}/{len(checks)}",
        "loc": loc,
        "final_state": snapshots[-1] if snapshots else {},
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== checks {result['checks_passed']} ===")
    for c in checks:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['id']}: {c['detail']}")
    print(f"totals: {result['totals']}\nwrote {out_path}")
    return result
