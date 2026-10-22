"""ESTIMATE (not a measurement) of the API version's token usage, without an API key.

  python estimate_api.py --transcripts <Claude Code project dir of runs/sdk/sdk_workspace>

Method
1. Replay: read the Claude Code transcripts of the measured SDK run and extract, per turn, the
   model's actual decisions (text + tool_use blocks, in order). Feed exactly those decisions to the
   real API harness (StudyAgentAPI) through a scripted fake client. The harness executes the tools,
   builds its own context blocks, cache breakpoints and history, and the fake client records every
   request the harness would have sent.
2. Calibrate: in the SDK transcript, the first request of each session is fully visible (system,
   tools, message blobs) and its real token count is known from usage. chars/token = chars / tokens.
3. Convert each recorded API request to tokens with that ratio and apply the API's caching rules
   (5-minute breakpoints on system+tools and on the last message). Output tokens and model-call counts
   are taken from the SDK run (same model, same effort, same decisions).
Writes results/api_estimate.json. It never writes results/api.json, which is reserved for a real run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from anthropic.types import Message  # noqa: E402

from API.agent import StudyAgentAPI  # noqa: E402
from API.harness.tokens import PRICES  # noqa: E402
from shared.calendar_api import http_fetch  # noqa: E402
from shared.loc import api_loc  # noqa: E402
from shared.prompts import MODEL  # noqa: E402
from shared.scenario import load_scenario, reset_dir, summarize  # noqa: E402

PREFIX = "mcp__study__"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def session_files(transcripts: Path, run_tag: str | None) -> list[Path]:
    """The two transcripts of the measured run, in session order (matched by run tag)."""
    found = []
    for f in transcripts.glob("*.jsonl"):
        recs = read_jsonl(f)
        shape = next((r["shape"] for r in recs if r.get("type") == "api-request-shape"), None)
        if not shape or (run_tag and f"(run {run_tag})" not in json.dumps(shape)):
            continue
        first_ts = next(r["timestamp"] for r in recs if r.get("timestamp"))
        found.append((first_ts, f))
    return [f for _, f in sorted(found)]


def text_len(value) -> int:
    """Characters of model-visible content (text, tool inputs/results, schemas)."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(text_len(v) for v in value)
    if isinstance(value, dict):
        return sum(text_len(v) for k, v in value.items()
                   if k not in ("type", "cache_control", "signature", "id", "tool_use_id"))
    return len(str(value)) if value is not None else 0


def parse_session(path: Path) -> tuple[list[list[dict]], list[dict]]:
    """-> (turns: list of assistant messages per turn, calibration points)."""
    recs = read_jsonl(path)
    turns: list[list[dict]] = []
    by_id: dict[str, dict] = {}
    calib, blobs, shape = [], [], None
    for r in recs:
        t = r.get("type")
        if t == "api-request-shape":
            shape = r["shape"]
        elif t == "api-request-blob" and not by_id:
            blobs.append(r.get("message", {}).get("content"))
        elif t == "user" and isinstance(r["message"]["content"], str):
            turns.append([])
        elif t == "assistant":
            m = r["message"]
            if m["id"] not in by_id:
                by_id[m["id"]] = {"content": [], "usage": m.get("usage", {})}
                turns[-1].append(by_id[m["id"]])
                if len(by_id) == 1:   # first request of the session: fully visible -> calibration
                    u = m["usage"]
                    tokens = u["input_tokens"] + u["cache_read_input_tokens"] + u["cache_creation_input_tokens"]
                    chars = text_len(shape["system"]) + text_len(shape["tools"]) + text_len(blobs)
                    calib.append({"chars": chars, "tokens": tokens})
            for block in m["content"]:
                if block["type"] in ("text", "tool_use"):
                    by_id[m["id"]]["content"].append(block)
    return turns, calib


def scripted_responses(turn: list[dict]) -> list[Message]:
    out = []
    for i, msg in enumerate(turn):
        content = []
        for b in msg["content"]:
            if b["type"] == "tool_use":
                content.append({"type": "tool_use", "id": b["id"], "name": b["name"].removeprefix(PREFIX),
                                "input": b["input"]})
            else:
                content.append({"type": "text", "text": b["text"]})
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        out.append(Message.model_validate({
            "id": f"est_{i}", "type": "message", "role": "assistant", "model": MODEL, "content": content,
            "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": msg["usage"].get("output_tokens", 0)},
        }))
    return out


class RecordingClient:
    def __init__(self):
        self.script: list[Message] = []
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        return self.script.pop(0)


def estimate_tokens(requests: list[dict], outputs: list[int], ratio: float, warm_prefix: bool) -> list[dict]:
    """Apply the API harness's caching rules to the recorded requests of one session."""
    price = PRICES[MODEL]
    rows, prev_cached = [], 0
    for i, (req, out) in enumerate(zip(requests, outputs)):
        prefix = round((text_len(req["tools"]) + text_len(req["system"])) / ratio)
        # User-side content (prompts, context blocks, tool results) via the char ratio; the model's own
        # earlier messages at their real output-token size, which includes thinking re-sent as input.
        user_chars = text_len([m["content"] for m in req["messages"] if m["role"] == "user"])
        msgs = round(user_chars / ratio) + sum(outputs[:i])
        total = prefix + msgs
        if i == 0:
            # system+tools may still be warm from the previous session (< 5 min apart)
            read = prefix if warm_prefix else 0
        else:
            read = prev_cached
        write = total - read          # breakpoint sits on the last block -> nothing left uncached
        rows.append({"input": 0, "cache_read": read, "cache_write": write, "output": out})
        prev_cached = total
    for r in rows:
        r["cost_usd"] = (r["cache_read"] * price["cache_read"] + r["cache_write"] * price["cache_write"]
                         + r["output"] * price["output"]) / 1e6
    return rows


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--transcripts", type=Path, required=True)
    p.add_argument("--sdk-results", type=Path, default=ROOT / "results" / "sdk.json")
    p.add_argument("--out", type=Path, default=ROOT / "results" / "api_estimate.json")
    args = p.parse_args()

    scenario = load_scenario(ROOT / "scenario.json")
    sdk = json.loads(args.sdk_results.read_text(encoding="utf-8"))
    run_tag = sdk.get("run_tag")
    files = session_files(args.transcripts, run_tag)[-2:]
    if len(files) != 2:
        sys.exit(f"expected 2 session transcripts, found {len(files)}")
    sessions = [parse_session(f) for f in files]
    calib = [c for _, cs in sessions for c in cs]
    ratio = sum(c["chars"] for c in calib) / sum(c["tokens"] for c in calib)
    print(f"[estimate_api.py] calibration: {calib} -> {ratio:.2f} chars/token")

    data_dir = reset_dir(ROOT / "runs" / "api-estimate")
    turns_out, n = [], 0
    for s_idx, (session, (sdk_turns, _)) in enumerate(zip(scenario["sessions"], sessions)):
        client = RecordingClient()
        agent = StudyAgentAPI(data_dir, scenario["planner_date"], session=session["name"], client=client,
                              fetch=http_fetch, run_tag=run_tag)
        session_reqs, session_outs, per_turn_calls = [], [], []
        for text, sdk_turn in zip(session["turns"], sdk_turns):
            client.script = scripted_responses(sdk_turn)
            start = len(client.requests)
            stats = agent.run_turn(text)
            per_turn_calls.append((len(client.requests) - start, stats))
            session_reqs += client.requests[start:]
            session_outs += [m["usage"].get("output_tokens", 0) for m in sdk_turn]
        rows = estimate_tokens(session_reqs, session_outs, ratio, warm_prefix=s_idx > 0)
        i = 0
        for text, (calls, stats) in zip(session["turns"], per_turn_calls):
            n += 1
            part = rows[i:i + calls]
            i += calls
            turns_out.append({
                "turn": n, "session": session["name"], "prompt": text, "reply": stats["reply"],
                "tokens": {k: sum(r[k] for r in part) for k in ("input", "cache_read", "cache_write", "output")},
                "model_calls": calls, "tools": stats["tools"],
                "cost_usd": round(sum(r["cost_usd"] for r in part), 6),
                "seconds": 0.0,
            })
        agent.close()

    result = {
        "harness": "api",
        "kind": "ESTIMATE - not a measurement. Replay of the SDK run's model decisions through the real "
                "API harness; tokens from a chars/token ratio calibrated on the SDK run.",
        "model": MODEL,
        "chars_per_token": round(ratio, 3),
        "calibration_points": calib,
        "turns": turns_out,
        "totals": summarize(turns_out),
        "checks_passed": None,
        "loc": api_loc(ROOT / "API"),
    }
    args.out.write_bytes(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    print(f"[estimate_api.py] totals: {result['totals']}\nwrote {args.out}")


if __name__ == "__main__":
    main()
