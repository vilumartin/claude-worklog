---
description: Add a meeting, call or preparation that left no trace (in person, phone, WhatsApp)
argument-hint: "<date> <minutes> <project> [title]"
allowed-tools: Bash
---

Use the worklog skill. From `$ARGUMENTS` take the date, minutes, project and optional title; ask for anything missing.
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/worklog.py" add --date ... --minutes ... --project ... [--title ...]`.
Add `--activity Preparation` for preparation time. Confirm back what was saved.
