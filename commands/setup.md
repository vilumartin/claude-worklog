---
description: First-time setup of claude-worklog, mapping folders and calendars to clients and projects
allowed-tools: Bash Read Write Edit
---

Use the worklog skill and follow its first-time setup: run `init`, then `projects --days 30`, propose a mapping of
folders to clients and projects, confirm it with the user one question at a time, and save it to
`~/.claude/worklog/rules.json`. Then ask about calendars, the user's own addresses and each client's rate, and run
`fetch` (macOS) or `import-ics`, then `report`.
