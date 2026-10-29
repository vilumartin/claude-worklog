---
name: worklog
description: >
  Count the hours the user worked, per client, project and kind of work, and draft a timesheet or invoice. Use when
  they ask how many hours or minutes they spent on a client, project or task, how long calls took, what to bill a
  client for, "what did I work on this week", or want a timesheet, an invoice annex, or a split between companies.
  Reads Claude session transcripts, the calendar and meeting-recap emails on this machine. Nothing is sent anywhere.
allowed-tools: Bash Read Write Edit
---

# worklog: hours per client and project

You turn data that is already on the user's machine into defensible hours. You never send, email or submit a
timesheet or invoice, and you never put message text in a report: only times, projects, activity names and call titles.

## Run the script

Every command is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/worklog.py" <command>`. If `CLAUDE_PLUGIN_ROOT` is empty, find
the script with `find ~/.claude/plugins -name worklog.py -path "*claude-worklog*"`. The user's settings, data and
reports live in `~/.claude/worklog/` (override with `WORKLOG_HOME`).

| Command | Use |
|---|---|
| `init` | first time: creates `~/.claude/worklog/rules.json` |
| `projects --days 30` | folders worked in, minutes, and the project each maps to |
| `fetch --days 14` | macOS: read Calendar.app and meeting-recap emails (Apple Mail) |
| `import-ics FILE` | any system: import a calendar export |
| `report --days 14` | totals by project, activity, day and call |
| `invoice --client C --from D --to D` | draft timesheet and amount for one client |
| `add --date D --minutes N --project P [--title T --time HH:MM --activity A]` | a meeting, call or preparation that left no trace |
| `assign --field attendees\|title\|calendar --regex RX --project P` | remember which project a kind of call belongs to |

## First-time setup (do this with the user, one question at a time)

1. Run `init`, then `projects --days 30`. Show the folders and propose a mapping to clients and projects. Write the
   confirmed mapping into `rules.json` under `folders`. A folder that spans several clients goes under `mixed_folders`
   with `keywords` per project and `priority_projects` for named clients.
2. Ask which calendars to read and which addresses are theirs (`calendars`, `own_emails`).
3. Ask each client's rate, currency and whether VAT is excluded or included, and write it under `clients`.
4. Run `fetch` (macOS) or ask for an `.ics` export, then `report`.

## The three estimates (always show all three)

- **Low:** only hands-on time, a 5-minute window after each message the user sent, plus confirmed calls.
- **Middle (the median):** work blocks stay open while events are under 10 minutes apart, plus scheduled calls.
- **High:** a 20-minute gap, which includes time spent watching and reading agents work, plus scheduled calls.

Explain the difference in one sentence. For billing, use the middle value unless the user chooses another, and say
which one you used. Calls win over Claude time, so no minute is counted twice.

## Working rules

- **Ask before assigning.** Calls marked "assumed" have a guessed project. Ask the user, then save the answer with
  `assign` (for a kind of call) or `add` with `--project` (for one call). Never guess a client for an invoice.
- **Meetings with no trace** (in person, phone, WhatsApp): ask date, length and client, then `add`. Preparation
  before a call is a separate `add` with `--activity Preparation`, unless the Claude sessions already show it.
- **Pro bono or unpaid work** gets its own project name (for example "Mentoring (pro bono)") and no rate.
- **Round once**, at the month total (default 15 minutes), not every day.
- **Things the data cannot see:** recurring calendar events are not expanded, chats in claude.ai or other apps are
  not captured, activity labels are rough guesses from the tools used. Say so when it matters for the answer.
- **Pre-sales time** (intro calls, writing the proposal) is often not billable. Ask before including it in an invoice.
- **A timesheet is a draft.** Present it, let the user check it, and leave sending to them. Show only the one client's
  lines in a client's timesheet.

## Answering "how many hours on X"

Run `report` (or `invoice` for one client), give low, middle and high, split into calls and Claude time, name what is
not covered, and offer the next step (confirm assumed calls, add missing meetings, draft the timesheet).
