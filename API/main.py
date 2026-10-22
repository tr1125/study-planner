"""Run the API version.

  python API/main.py --scenario scenario.json --out results/api.json
  python API/main.py --chat [--session s1 --resume]
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from API.agent import StudyAgentAPI  # noqa: E402
from shared.loc import api_loc  # noqa: E402
from shared.scenario import load_scenario, reset_dir, run_scenario  # noqa: E402

DATA_DIR = ROOT / "runs" / "api"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", type=Path)
    p.add_argument("--out", type=Path, default=ROOT / "results" / "api.json")
    p.add_argument("--chat", action="store_true", help="interactive mode")
    p.add_argument("--session", default="chat")
    p.add_argument("--resume", action="store_true", help="continue the saved conversation of --session")
    p.add_argument("--today", default=None, help="planner date YYYY-MM-DD (chat mode)")
    p.add_argument("--compact-threshold", type=int, default=None)
    args = p.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Set it in this terminal only, e.g.\n"
                 "  PowerShell: $env:ANTHROPIC_API_KEY = 'sk-ant-...'\n"
                 "  bash:       export ANTHROPIC_API_KEY=sk-ant-...")
    extra = {"compact_threshold": args.compact_threshold} if args.compact_threshold else {}

    if args.scenario:
        scenario = load_scenario(args.scenario)
        data_dir = reset_dir(DATA_DIR)
        run_tag = uuid.uuid4().hex[:8]   # fresh prompt-cache namespace for this run
        run_scenario(
            scenario, "api", data_dir,
            lambda name: StudyAgentAPI(data_dir, scenario["planner_date"], session=name, run_tag=run_tag,
                                       **extra),
            api_loc(ROOT / "API"), args.out,
        )
        return

    from datetime import date
    data_dir = ROOT / "runs" / "api-chat"
    agent = StudyAgentAPI(data_dir, args.today or date.today().isoformat(), session=args.session,
                          resume=args.resume, **extra)
    print("Study Planner (API). Empty line to quit.")
    try:
        while text := input("\nyou> ").strip():
            print("\nplanner>", agent.run_turn(text)["reply"])
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        agent.close()


if __name__ == "__main__":
    main()
