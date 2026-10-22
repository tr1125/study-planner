# Study Planner: one agent, two harnesses

A study-planning agent for a university student. It tracks deadlines, schedules
study sessions, remembers how the student likes to study, and checks Israeli
holidays through the live Hebcal API. The agent is built twice:

| | `API/` | `SDK/` |
|---|---|---|
| Harness | hand-written on the raw Messages API (`anthropic`) | Claude Code via the Claude Agent SDK |
| Auth | `ANTHROPIC_API_KEY` (env var only) | your Claude Code login |
| Model / effort | `claude-opus-5-5` / `medium` | `claude-opus-5-5` / `medium` |

The domain code (tools, data, memory store, Hebcal client) lives in `shared/` and both versions use it.
The measurements and the comparison are in [REPORT.md](REPORT.md).

## Layout

```
shared/        domain: store.py (deadlines/sessions), memory_store.py, calendar_api.py (Hebcal),
               tools.py (8 tool specs), prompts.py (system prompt, model, effort),
               scenario.py (runner), checks.py (pass/fail checks), loc.py (line counts)
API/           main.py  agent.py
  harness/     loop.py tools.py history.py memory.py context.py compaction.py caching.py tokens.py
SDK/           main.py  agent.py  tools.py      (lines tagged "# replaces: <part>")
tests/         offline tests with a fake client, no key needed
scenario.json  7 turns in 2 sessions + 10 checks
results/       sdk.json (measured), api_estimate.json (estimate), api.json (written by a real API run)
report.py      regenerates the measured tables in REPORT.md from results/
estimate_api.py  replays the SDK run's model decisions through the real API harness to estimate
                 its tokens without a key (labelled as an estimate everywhere; see REPORT.md §3)
```

## Tools

| Tool | What it does |
|---|---|
| `add_deadline`, `list_deadlines` | exams/assignments, with planned hours per course |
| `schedule_session`, `list_sessions`, `cancel_session` | study sessions; overlaps and past dates are rejected |
| `check_calendar` | **external**: Israeli holidays from the Hebcal REST API, compressed to one line per holiday |
| `remember`, `recall` | long-term memory; changing a fact supersedes the old one (`replaces`), nothing is deleted |

## Setup

Python 3.12. Library versions are pinned in `requirements.txt`, and the full lock is in `requirements.lock`.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Run

```powershell
# offline tests (no key, no network)
.venv\Scripts\python -m pytest tests

# API version: the key goes in an environment variable in this terminal only, never in code or git
$env:ANTHROPIC_API_KEY = "sk-ant-..."
.venv\Scripts\python API/main.py --scenario scenario.json --out results/api.json

# SDK version: uses your Claude Code login (SDK/main.py drops ANTHROPIC_API_KEY from its own process)
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
.venv\Scripts\python SDK/main.py --scenario scenario.json --out results/sdk.json

# refresh the tables in REPORT.md
.venv\Scripts\python report.py

# interactive mode (either version); --resume continues a saved conversation
.venv\Scripts\python API/main.py --chat --session mine
.venv\Scripts\python SDK/main.py --chat --session mine --resume
```

Every scenario run starts from a clean state: `runs/api/` or `runs/sdk/` is deleted first.
Each run also adds a random tag to the system prompt, so it can't read prompt-cache entries
written by an earlier run.
Run the SDK version from a normal terminal, not from inside a Claude Code session. The Claude Code
child process inherits `CLAUDECODE` / `CLAUDE_CODE_*` environment variables.
Session 2 always runs on a new agent instance, which loads memory and state from disk.
