---
description: Draft a client timesheet and amount for a period (a draft, never sent)
argument-hint: "<client> <from YYYY-MM-DD> <to YYYY-MM-DD> [low|middle|high]"
allowed-tools: Bash
---

Use the worklog skill. Parse `$ARGUMENTS` as client, start date, end date and an optional basis (default middle). Run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/worklog.py" invoice --client ... --from ... --to ... --basis ...`. If there is
no rate for the client, ask for it and save it under `clients` in `~/.claude/worklog/rules.json`. Show the timesheet,
point out anything that may not be billable (pre-sales, pro bono, preparation without evidence), and do not send it.
