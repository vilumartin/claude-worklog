---
description: Show hours per project, activity, day and call, with low, middle and high estimates
argument-hint: "[days, default 14]"
allowed-tools: Bash
---

Use the worklog skill. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/worklog.py" report --days $ARGUMENTS` (use 14 when no
number is given; run `fetch` first on macOS if the calendar data is older than a day). Present the three totals, the
table by project, and any calls with an assumed project. Ask which assumed calls to confirm.
