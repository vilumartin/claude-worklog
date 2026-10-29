#!/usr/bin/env python3
"""Hook: append one line per Claude Code event to ~/.claude/worklog/events.jsonl.

Stores only the time, the event name, the session id and the folder. Never the prompt text.
This is a durable ledger that survives Claude's transcript cleanup. Fails silently so it never blocks a session.
"""
import datetime as dt, json, os, sys

try:
    d = json.load(sys.stdin)
    home = os.environ.get("WORKLOG_HOME") or os.path.expanduser("~/.claude/worklog")
    os.makedirs(home, exist_ok=True)
    line = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "event": d.get("hook_event_name", ""), "session": d.get("session_id", ""), "cwd": d.get("cwd", "")}
    with open(os.path.join(home, "events.jsonl"), "a") as fh:
        fh.write(json.dumps(line) + "\n")
except Exception:
    pass
