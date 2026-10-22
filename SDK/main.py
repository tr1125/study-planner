"""Run the SDK version (uses your Claude Code login, not an API key).

  python SDK/main.py --scenario scenario.json --out results/sdk.json
  python SDK/main.py --chat [--session s1 --resume]
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from SDK.agent import StudyAgentSDK  # noqa: E402
from shared.loc import sdk_loc  # noqa: E402
from shared.scenario import load_scenario, reset_dir, run_scenario  # noqa: E402

DATA_DIR = ROOT / "runs" / "sdk"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", type=Path)
    p.add_argument("--out", type=Path, default=ROOT / "results" / "sdk.json")
    p.add_argument("--chat", action="store_true", help="interactive mode")
    p.add_argument("--session", default="chat")
    p.add_argument("--resume", action="store_true", help="resume the saved Claude Code session of --session")
    p.add_argument("--today", default=None, help="planner date YYYY-MM-DD (chat mode)")
    args = p.parse_args()

    # Billing must go to the Claude Code login: an API key in the environment would take precedence.
    if os.environ.pop("ANTHROPIC_API_KEY", None):
        print("[SDK/main.py] ANTHROPIC_API_KEY removed from this process so the run uses your Claude Code login")

    if args.scenario:
        scenario = load_scenario(args.scenario)
        data_dir = reset_dir(DATA_DIR)
        run_tag = uuid.uuid4().hex[:8]   # fresh prompt-cache namespace for this run
        run_scenario(
            scenario, "sdk", data_dir,
            lambda name: StudyAgentSDK(data_dir, scenario["planner_date"], session=name, run_tag=run_tag),
            sdk_loc(ROOT / "SDK"), args.out,
        )
        return

    from datetime import date
    agent = StudyAgentSDK(ROOT / "runs" / "sdk-chat", args.today or date.today().isoformat(),
                          session=args.session, resume=args.resume)
    print("Study Planner (SDK). Empty line to quit.")
    try:
        while text := input("\nyou> ").strip():
            print("\nplanner>", agent.run_turn(text)["reply"])
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        agent.close()


if __name__ == "__main__":
    main()
