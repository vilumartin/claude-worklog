# claude-worklog

Count the hours you really work, per client and project, if you bill by the hour and work with Claude.

You work in Claude all day, jump between clients, take calls, and at the end of the month you cannot say how long
anything took. claude-worklog rebuilds your hours from data that is already on your machine and gives you a draft
timesheet and invoice amount for each client.

**Everything stays on your machine.** No network, no account, no message text in any report. Python 3 standard library only.

## What it reads

| Source | What it gives |
|---|---|
| Claude session transcripts (`~/.claude/projects`) | when you worked, in which folder, with which tools |
| Hook ledger (`~/.claude/worklog/events.jsonl`, written by this plugin) | the same, but kept after Claude cleans up old transcripts. Times and folder only, never your text |
| Calendar (macOS Calendar.app, or any `.ics` export) | meetings with attendees |
| Meeting-recap emails (Fathom, in Apple Mail on macOS) | real call length ("26 mins") |
| Your own entries | in-person meetings, phone calls, preparation |

## Three estimates, because watching agents work is work

You do not only type. You read answers, think, and supervise agents. So every number comes in three values:

- **Low:** hands-on only. A 5-minute window after each message you send, plus confirmed calls.
- **Middle (the median):** work blocks stay open while events are less than 10 minutes apart, plus all scheduled calls.
- **High:** a 20-minute gap, which includes time you spend watching and reading agents work.

Calls win over Claude time, and parallel sessions are merged, so no minute is counted twice. Use the middle value for
billing unless you decide otherwise.

## Install

```
/plugin marketplace add <your-github-user>/claude-worklog
/plugin install claude-worklog@claude-worklog
```

To try it from a folder without installing: `claude --plugin-dir /path/to/claude-worklog`.

Then run `/worklog:setup`. Claude lists the folders you worked in, proposes which client or project each belongs to,
asks which calendars to read and what each client pays, and saves it to `~/.claude/worklog/rules.json`.

## Use

| Command | What it does |
|---|---|
| `/worklog:setup` | first-time mapping of folders, calendars and rates |
| `/worklog:report [days]` | hours by project, activity, day and call, with the three estimates |
| `/worklog:invoice <client> <from> <to> [basis]` | draft timesheet and amount for one client (also saved as Markdown and CSV) |
| `/worklog:add <date> <minutes> <project> [title]` | a meeting or preparation that left no trace |

Or just ask: "how many hours did I spend on Acme this month?" The skill answers from the same data.

Command line (also works without Claude): `python3 scripts/worklog.py --help`.

## Configuration (`~/.claude/worklog/rules.json`)

```json
{
  "folders": [["clients/acme", "Acme"], ["clients/beta", "Beta"]],
  "mixed_folders": ["*"],
  "keywords": {"Acme": ["acme"], "Beta": ["beta"]},
  "priority_projects": ["Acme", "Beta"],
  "calendars": ["me@example.com"],
  "own_emails": ["me@example.com"],
  "call_rules": [["attendees", "acme\\.com", "Acme"]],
  "clients": {"Acme": {"rate": 130, "vat": "excl", "currency": "EUR"}},
  "round_minutes": 15
}
```

Folders with no rule are filed under their own name. Sessions in a folder that spans several clients (a general
assistant folder, say) are split by keywords in what was discussed.

## Rules of the game

- A timesheet is a draft. The plugin never sends or submits anything.
- The monthly total is rounded up once (default 15 minutes), not every day.
- Unpaid work (pro bono, mentoring) gets its own project and no rate.
- Pre-sales time (intro calls, writing a proposal) is often not billable. The skill asks before including it.

## Limits

- Recurring calendar events are not expanded yet, so standing meetings are not counted.
- Chats in claude.ai or other apps are not captured. Add them with `add`.
- Activity labels (setup, planning, research) are rough guesses from the tools used.
- Client labels for mixed folders come from keywords. Check them once.
- `fetch` (Calendar.app and Apple Mail) is macOS only. Elsewhere use `import-ics` and `add`.

## Privacy

The plugin reads files in your home folder and writes only to `~/.claude/worklog/`. The hooks store a timestamp, the
event name, the session id and the folder path per event. To stop logging, disable the plugin or delete
`hooks/hooks.json`. Transcript text is read in memory to match keywords and is never written anywhere.

## Development

```
python3 -m unittest discover -s tests -v
claude plugin validate .
```

MIT license.
