#!/usr/bin/env python3
"""claude-worklog: how many hours did you work, on which client and project?

Reads what is already on your machine: Claude session transcripts, the optional hook ledger, your calendar
and meeting-recap emails. Nothing leaves the machine. Standard library only.

Commands
  init                          create ~/.claude/worklog with a starter rules.json
  projects [--days 30]          folders you worked in, with minutes, and the project each maps to
  fetch    [--days 14]          macOS: read Calendar.app and meeting-recap emails (Apple Mail) into data/
  import-ics FILE               any OS: import events from an .ics calendar export into data/calendar.json
  report   [--days 14] [--out F]  totals by project, activity, day and call, three estimates
  invoice  --client C --from D --to D [--basis low|middle|high] [--rate N] [--vat excl|incl]
  add      --date D --minutes N --project P [--title T] [--time HH:MM] [--activity A]
  assign   --field attendees|title|calendar --regex RX --project P

Estimates (what counts as work time)
  low     hands-on: a 5-minute window after each message you send, plus confirmed calls
  middle  Claude blocks stay open while events are less than 10 minutes apart, plus scheduled calls (the median)
  high    same with a 20-minute gap (you watching and reading agents), plus scheduled calls
Calls win over Claude time: a minute in a call belongs to the call. Overlapping sessions are merged.
Set WORKLOG_HOME to use another config folder (default ~/.claude/worklog).
"""
import argparse, bisect, collections, csv, datetime as dt, glob, json, math, os, re, subprocess, sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
HOMEDIR = os.environ.get("WORKLOG_HOME") or os.path.expanduser("~/.claude/worklog")
PROJECTS_DIR = os.environ.get("CLAUDE_PROJECTS_DIR") or os.path.expanduser("~/.claude/projects")
DATA = os.path.join(HOMEDIR, "data")
EST = ["low", "middle", "high"]
CALL_ACT = "Calls and meetings"

STARTER_RULES = {
    "timezone": "",
    "folders": [],
    "mixed_folders": [],
    "keywords": {},
    "priority_projects": [],
    "priority_threshold": 2,
    "calendars": [],
    "own_emails": [],
    "call_rules": [],
    "fallback_call_project": ["Unassigned", True],
    "skip_titles": ["lunch", "block:", "flight", "focus", "birthday", "holiday"],
    "clients": {},
    "round_minutes": 15,
}
RULES_HELP = {
    "folders": "[[\"part of a folder path\", \"Project name\"], ...] first match wins; unmatched folders use their own name",
    "mixed_folders": "folder fragments (or \"*\") whose sessions span several projects; their text is matched against keywords",
    "keywords": "{\"Project\": [\"regex\", ...]} used only for mixed folders",
    "calendars": "Calendar.app calendar names to read (macOS)",
    "own_emails": "your own addresses, to tell you from the other attendees",
    "call_rules": "[[\"attendees|title|calendar\", \"regex\", \"Project\"], ...] first match wins",
    "clients": "{\"Project\": {\"rate\": 130, \"vat\": \"excl\", \"currency\": \"EUR\"}} used by the invoice command",
}

# ---------------------------------------------------------------- config
def jload(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)

def jdump(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)

def detect_tz():
    try:
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return ZoneInfo(link.split("zoneinfo/", 1)[1])
    except Exception:
        pass
    return ZoneInfo("UTC")

def load_rules():
    rules = json.loads(json.dumps(STARTER_RULES))
    p = os.path.join(HOMEDIR, "rules.json")
    if os.path.exists(p):
        rules.update(jload(p))
    return rules

def save_rules(rules):
    os.makedirs(HOMEDIR, exist_ok=True)
    jdump(rules, os.path.join(HOMEDIR, "rules.json"))

def get_tz(rules):
    return ZoneInfo(rules["timezone"]) if rules.get("timezone") else detect_tz()

def hm(minutes):
    minutes = int(round(minutes))
    return f"{minutes // 60}h {minutes % 60:02d}m"

def mkey(ts):
    return int(ts.timestamp() // 60)

# ---------------------------------------------------------------- transcripts and ledger
def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))

def is_human(d):
    if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
        return False
    c = d.get("message", {}).get("content")
    if isinstance(c, str):
        t = c.strip()
        return bool(t) and not t.startswith("<") and not t.startswith("This session is being continued")
    if isinstance(c, list):
        return any(x.get("type") in ("text", "image") for x in c if isinstance(x, dict))
    return False

def tools_of(d):
    c = d.get("message", {}).get("content")
    if d.get("type") == "assistant" and isinstance(c, list):
        return [x.get("name", "") for x in c if isinstance(x, dict) and x.get("type") == "tool_use"]
    return []

def blob_of(d):
    """short text kept in memory only, used to match keywords; never written to any report"""
    c = d.get("message", {}).get("content")
    out = []
    if isinstance(c, str):
        out.append(c[:600])
    elif isinstance(c, list):
        for x in c:
            if isinstance(x, dict) and x.get("type") == "text":
                out.append(x.get("text", "")[:600])
            elif isinstance(x, dict) and x.get("type") == "tool_use":
                out.append(json.dumps(x.get("input", {}), ensure_ascii=False)[:300])
    return " ".join(out)

def folder_project(cwd, rules):
    low = cwd.lower()
    for frag, proj in rules["folders"]:
        if frag.lower() in low:
            return proj, False
    for frag in rules["mixed_folders"]:
        if frag == "*" or frag.lower() in low:
            return None, True
    base = os.path.basename(cwd.rstrip("/")) or "Unassigned"
    return base, False

def activity(t):
    dev = t["Edit"] + t["Write"] + t["Bash"] + t["NotebookEdit"]
    web = t["WebSearch"] + t["WebFetch"]
    mcp = sum(v for k, v in t.items() if k.startswith("mcp__"))
    if sum(t.values()) == 0:
        return "Chat and planning"
    if t["Artifact"] >= 3:
        return "Docs and decks"
    if dev >= 3 and dev >= max(web, mcp, 1):
        return "Setup and build (files, git, config)"
    if mcp >= 3:
        return "Agent work with connectors (mail, calendar, data)"
    if web >= 2:
        return "Research"
    return "Chat and planning"

def build_blocks(events, gap_min):
    blocks, cur = [], None
    for ts, human in events:
        if cur and (ts - cur["end"]).total_seconds() <= gap_min * 60:
            cur["end"] = ts
        else:
            if cur:
                blocks.append(cur)
            cur = {"start": ts, "end": ts, "humans": []}
        if human:
            cur["humans"].append(ts)
    if cur:
        blocks.append(cur)
    return blocks

def read_transcripts(since):
    """yield (session_id, cwd, [(ts, human, tools, blob)]) from Claude transcripts"""
    for f in glob.glob(os.path.join(PROJECTS_DIR, "*/*.jsonl")):
        ev, cwd = [], ""
        with open(f, errors="ignore") as fh:
            lines = fh.readlines()
        for line in lines:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("isSidechain") or "timestamp" not in d or d.get("type") not in ("user", "assistant"):
                continue
            ts = parse_ts(d["timestamp"])
            cwd = d.get("cwd") or cwd
            if ts >= since:
                ev.append((ts, is_human(d), tools_of(d), blob_of(d)))
        if ev:
            yield os.path.splitext(os.path.basename(f))[0], cwd, ev

def read_ledger(since, skip_sessions):
    """events written by the plugin hooks, for sessions whose transcript is gone"""
    p = os.path.join(HOMEDIR, "events.jsonl")
    if not os.path.exists(p):
        return
    sessions = collections.defaultdict(list)
    cwds = {}
    with open(p) as fh:
        ledger_lines = fh.readlines()
    for line in ledger_lines:
        try:
            d = json.loads(line)
            ts = parse_ts(d["ts"])
        except Exception:
            continue
        if ts < since or d.get("session") in skip_sessions:
            continue
        sessions[d["session"]].append((ts, d.get("event") == "UserPromptSubmit", [], ""))
        cwds[d["session"]] = d.get("cwd", "")
    for sid, ev in sessions.items():
        yield sid, cwds[sid], ev

def claude_minutes(rules, since):
    """returns {estimator: {minute: (recency, project, activity)}}"""
    result = {n: {} for n in EST}
    sessions, seen = [], set()
    for sid, cwd, ev in read_transcripts(since):
        seen.add(sid); sessions.append((cwd, ev))
    for sid, cwd, ev in read_ledger(since, seen):
        sessions.append((cwd, ev))
    for cwd, ev in sessions:
        ev.sort(key=lambda e: e[0])
        fproj, mixed = folder_project(cwd, rules)
        humans_idx = [i for i, e in enumerate(ev) if e[1]]
        if not humans_idx:
            continue
        seg_start, seg_proj, seg_act, prev = [], [], [], "Unassigned"
        for k, i in enumerate(humans_idx):
            j = humans_idx[k + 1] if k + 1 < len(humans_idx) else len(ev)
            seg = ev[i:j]
            tc = collections.Counter(t for e in seg for t in e[2])
            if not mixed:
                proj = fproj
            else:
                blob = " ".join(e[3] for e in seg).lower()
                scores = {p: sum(len(re.findall(rx, blob)) for rx in rxs) for p, rxs in rules["keywords"].items()}
                best = max(scores, key=scores.get) if scores else None
                prio = [q for q in rules.get("priority_projects", []) if scores.get(q, 0) >= rules.get("priority_threshold", 2)]
                if prio:  # named clients win over generic company words that appear everywhere
                    best = max(prio, key=scores.get)
                proj = best if best and scores[best] > 0 else prev
                prev = proj
            seg_start.append(mkey(ev[i][0])); seg_proj.append(proj); seg_act.append(activity(tc))
        def label_at(m, seg_start=seg_start, seg_proj=seg_proj, seg_act=seg_act):
            k = max(0, bisect.bisect_right(seg_start, m) - 1)
            return seg_proj[k], seg_act[k]
        humans = [e[0] for e in ev if e[1]]
        for name, spec in (("low", ("win", 5)), ("middle", ("gap", 10)), ("high", ("gap", 20))):
            if spec[0] == "win":
                blocks = [{"start": h, "end": h + dt.timedelta(minutes=5), "humans": [h]} for h in humans]
            else:
                blocks = build_blocks([(e[0], e[1]) for e in ev], spec[1])
                for b in blocks:
                    b["end"] += dt.timedelta(minutes=2)  # time to read the last answer
            for b in blocks:
                last_h = max(b["humans"]) if b["humans"] else b["start"]
                m0, m1 = mkey(b["start"]), mkey(b["end"])
                for m in range(m0, m1 + 1):
                    rec = mkey(last_h) if mkey(last_h) <= m else m0
                    cur = result[name].get(m)
                    if cur is None or rec > cur[0]:
                        proj, act = label_at(m)
                        result[name][m] = (rec, proj, act)
    return result

# ---------------------------------------------------------------- calls: fetch and import
def run_osascript(path, *args):
    return subprocess.run(["osascript", path, *args], capture_output=True, text=True, timeout=900).stdout

def cmd_fetch(a, rules):
    if sys.platform != "darwin":
        sys.exit("fetch reads Calendar.app and Apple Mail, so it only runs on macOS. Use: import-ics FILE")
    os.makedirs(DATA, exist_ok=True)
    cals = rules["calendars"]
    if not cals:
        sys.exit("No calendars set. Add calendar names to \"calendars\" in " + os.path.join(HOMEDIR, "rules.json"))
    out = run_osascript(os.path.join(HERE, "fetch_calendar.applescript"), str(a.days + 1), *cals)
    rows = []
    for line in out.splitlines():
        p = line.split("|", 8)
        if len(p) < 9 or p[0] == "ERR":
            continue
        rows.append({"calendar": p[0], "uid": p[1], "start": p[2], "end": p[3], "allday": p[4] == "true",
                     "status": p[5], "recurring": p[6] == "1", "attendees": [x for x in p[7].split(";") if x], "title": p[8]})
    jdump(rows, os.path.join(DATA, "calendar.json"))
    out = run_osascript(os.path.join(HERE, "fetch_recaps.applescript"), str(a.days + 1))
    rec, seen = [], set()
    for line in out.splitlines():
        p = line.split("|", 2)
        if len(p) < 3:
            continue
        m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})\s*[•·]\s*(\d+) min", p[2])
        if m and (p[0], p[1]) not in seen:
            seen.add((p[0], p[1]))
            rec.append({"received": p[0], "subject": p[1], "minutes": int(m.group(2))})
    jdump(rec, os.path.join(DATA, "recaps.json"))
    print(f"calendar events: {len(rows)}, meeting recaps: {len(rec)}")

def parse_ics(text, tz):
    text = re.sub(r"\r?\n[ \t]", "", text)
    events, cur = [], None
    for line in text.splitlines():
        if line == "BEGIN:VEVENT":
            cur = {"attendees": [], "recurring": False, "allday": False, "status": "confirmed", "title": "", "calendar": "ics", "uid": ""}
        elif line == "END:VEVENT" and cur:
            if cur.get("start") and cur.get("end"):
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, val = line.split(":", 1)
            name, _, params = key.partition(";")
            if name in ("DTSTART", "DTEND"):
                allday = "VALUE=DATE" in params and len(val) == 8
                if allday:
                    cur["allday"] = True
                    d = dt.datetime.strptime(val, "%Y%m%d")
                elif val.endswith("Z"):
                    d = dt.datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).astimezone(tz).replace(tzinfo=None)
                else:
                    d = dt.datetime.strptime(val[:15], "%Y%m%dT%H%M%S")
                    m = re.search(r"TZID=([^;:]+)", params)
                    if m:
                        try:
                            d = d.replace(tzinfo=ZoneInfo(m.group(1))).astimezone(tz).replace(tzinfo=None)
                        except Exception:
                            pass
                cur["start" if name == "DTSTART" else "end"] = d.strftime("%Y-%m-%dT%H:%M:%S")
            elif name == "SUMMARY":
                cur["title"] = val.replace("\\,", ",").replace("\\n", " ")
            elif name == "UID":
                cur["uid"] = val
            elif name == "RRULE":
                cur["recurring"] = True
            elif name == "STATUS":
                cur["status"] = val.lower()
            elif name == "ATTENDEE":
                email = re.sub(r"(?i)^mailto:", "", val).lower()
                m = re.search(r"PARTSTAT=([A-Z-]+)", params)
                cur["attendees"].append(f"{email}:{(m.group(1).lower() if m else 'unknown')}")
    return events

def cmd_import_ics(a, rules):
    os.makedirs(DATA, exist_ok=True)
    with open(a.file, encoding="utf-8", errors="ignore") as fh:
        text = fh.read()
    events = parse_ics(text, get_tz(rules))
    p = os.path.join(DATA, "calendar.json")
    old = jload(p) if os.path.exists(p) else []
    known = {(e["uid"], e["start"]) for e in old}
    new = [e for e in events if (e["uid"], e["start"]) not in known]
    jdump(old + new, p)
    print(f"imported {len(new)} events ({len(events) - len(new)} already known)")

# ---------------------------------------------------------------- calls: build the list
def load_calls(rules, since, until):
    tz = get_tz(rules)
    rd = lambda n: jload(os.path.join(DATA, n)) if os.path.exists(os.path.join(DATA, n)) else []
    cal, recaps, over = rd("calendar.json"), rd("recaps.json"), rd("overrides.json")
    own = {x.lower() for x in rules["own_emails"]}
    local = lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=tz)
    calls, seen = [], set()
    for e in cal:
        if e["allday"] or e["status"] == "cancelled" or e["recurring"]:
            continue
        key = (e["start"], e["title"].strip().lower())
        if key in seen:
            continue
        others = [x.rsplit(":", 1)[0] for x in e["attendees"] if x.rsplit(":", 1)[0].lower() not in own]
        mine = [x.rsplit(":", 1)[1] for x in e["attendees"] if x.rsplit(":", 1)[0].lower() in own]
        if not others or (mine and all(s in ("declined", "cancelled") for s in mine)):
            continue
        if any(k in e["title"].lower() for k in rules["skip_titles"]):
            continue
        s, en = local(e["start"]), local(e["end"])
        if not (since <= s <= until):
            continue
        seen.add(key)
        calls.append({"id": e["uid"] or e["title"] + e["start"], "title": e["title"].strip(), "start": s,
                      "minutes": int((en - s).total_seconds() // 60), "attendees": others, "calendar": e["calendar"],
                      "confirmed": False, "source": "calendar (scheduled)"})
    for f in recaps:
        rec = dt.datetime.strptime(f["received"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=tz)
        est_start = rec - dt.timedelta(minutes=f["minutes"] + 3)
        best, bd = None, 25
        for c in calls:
            d = abs((c["start"] - est_start).total_seconds()) / 60
            if d <= bd and c["source"].startswith("calendar"):
                best, bd = c, d
        if best:
            best["minutes"], best["confirmed"], best["source"] = f["minutes"], True, "calendar + recap"
        elif since <= est_start <= until:
            title = re.sub(r"^Recap (of your meeting with|for) ", "", f["subject"]).strip('" ')
            calls.append({"id": "recap-" + f["received"], "title": title, "start": est_start, "minutes": f["minutes"],
                          "attendees": [], "calendar": "", "confirmed": True, "source": "recap only"})
    for o in over:
        day = dt.date.fromisoformat(o["date"])
        hit = [c for c in calls if c["start"].date() == day and o["match"].lower() in (c["title"] + " " + " ".join(c["attendees"])).lower()]
        if hit:
            c = hit[0]
            if "minutes" in o:
                c["minutes"], c["confirmed"], c["source"] = o["minutes"], True, "calendar + manual"
            if o.get("project"):
                c["force_project"] = o["project"]
        elif "minutes" in o:
            start = dt.datetime.combine(day, dt.time.fromisoformat(o.get("time", "12:00")), tz)
            if since <= start <= until:
                calls.append({"id": "manual-" + o["date"] + o["match"], "title": o.get("title", o["match"]), "start": start,
                              "minutes": o["minutes"], "attendees": [], "calendar": "", "confirmed": True, "source": "manual",
                              "force_project": o.get("project"), "activity": o.get("activity")})
    def overlap(x, y):
        a0, a1 = x["start"], x["start"] + dt.timedelta(minutes=x["minutes"])
        b0, b1 = y["start"], y["start"] + dt.timedelta(minutes=y["minutes"])
        return (min(a1, b1) - max(a0, b0)).total_seconds() / 60 / max(1, min(x["minutes"], y["minutes"]))
    rank = lambda c: (not c["confirmed"], c["source"].startswith("recap only"), "manual" not in c["source"])
    kept = []
    for c in sorted(calls, key=rank):
        if c.get("activity") or not any(overlap(c, k) >= 0.7 for k in kept if not k.get("activity")):
            kept.append(c)
    calls = kept
    for c in calls:
        if c.get("force_project"):
            c["project"], c["assumed"] = c["force_project"], False
            continue
        blob = {"attendees": " ".join(c["attendees"]).lower(), "title": c["title"].lower(), "calendar": c["calendar"].lower()}
        proj = None
        for field, rx, p in rules["call_rules"]:
            if re.search(rx, blob[field]):
                proj = p
                break
        if proj:
            c["project"], c["assumed"] = proj, False
        else:
            c["project"], c["assumed"] = rules["fallback_call_project"][0], True
    calls.sort(key=lambda c: c["start"])
    return calls

def merge_calls(result, calls):
    for name in EST:
        for c in calls:
            if name == "low" and not c["confirmed"]:
                continue
            m0 = mkey(c["start"])
            for m in range(m0, m0 + c["minutes"]):
                result[name][m] = (10 ** 12, c["project"], c.get("activity") or CALL_ACT, c["id"])
    return result

# ---------------------------------------------------------------- report
def aggregate(result, tz):
    bp = {n: collections.Counter() for n in EST}
    ba = {n: collections.Counter() for n in EST}
    bd = {n: collections.defaultdict(collections.Counter) for n in EST}
    for n in EST:
        for m, v in result[n].items():
            day = dt.datetime.fromtimestamp(m * 60, tz).date()
            bp[n][v[1]] += 1; ba[n][v[2]] += 1; bd[n][day][v[1]] += 1
    return bp, ba, bd

def table(title, counters):
    keys = sorted(set().union(*[set(counters[n]) for n in EST]), key=lambda k: -counters["middle"][k])
    lines = [f"\n## {title}\n", "| | Low | Middle (median) | High |", "|---|---|---|---|"]
    for k in keys:
        lines.append(f"| {k} | " + " | ".join(hm(counters[n][k]) for n in EST) + " |")
    return lines

def compute(rules, since_utc, until_local):
    tz = get_tz(rules)
    result = claude_minutes(rules, since_utc)
    calls = load_calls(rules, since_utc.astimezone(tz), until_local)
    return result, calls, tz

def cmd_report(a, rules):
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=a.days)
    result, calls, tz = compute(rules, since, now.astimezone(get_tz(rules)))
    calls = [c for c in calls if c["start"] <= now.astimezone(tz)]
    result = merge_calls(result, calls)
    bp, ba, bd = aggregate(result, tz)
    L = [f"# Work log estimate, {since.astimezone(tz).date()} to {now.astimezone(tz).date()} ({tz.key})\n",
         "Low = hands-on Claude time (5-minute window after each message) plus confirmed calls. "
         "Middle = median: Claude blocks with gaps up to 10 minutes plus all scheduled calls. "
         "High = gaps up to 20 minutes (you watching and reading agents) plus scheduled calls. "
         "Calls win over Claude time and no minute is counted twice.\n"]
    tot = {n: sum(bp[n].values()) for n in EST}
    L.append(f"**Total:** low {hm(tot['low'])} | middle {hm(tot['middle'])} | high {hm(tot['high'])}\n")
    L += table("By project (Claude time and calls)", bp)
    L += table("By activity", ba)
    L += ["\n## By day (middle estimate)\n", "| Day | Total | Top projects |", "|---|---|---|"]
    for day in sorted(bd["middle"]):
        c = bd["middle"][day]
        L.append(f"| {day} ({day.strftime('%a')}) | {hm(sum(c.values()))} | " + ", ".join(f"{p} {hm(v)}" for p, v in c.most_common(3)) + " |")
    if calls:
        L += ["\n## Calls and meetings counted\n", "| Date | Call | Min | Project | Basis |", "|---|---|---|---|---|"]
        for c in calls:
            flag = " (assumed, please confirm)" if c["assumed"] else ""
            L.append(f"| {c['start']:%a %d %b %H:%M} | {c['title']} | {c['minutes']} | {c['project']}{flag} | {c['source']} |")
        un = [c for c in calls if not c["confirmed"]]
        L.append(f"\n{len(un)} of {len(calls)} calls are counted at their scheduled length with no recap or correction "
                 "(the low estimate leaves them out). Recurring meetings are not expanded from the calendar, so they are not counted.\n")
    else:
        L.append("\nNo calls found. Run `fetch` (macOS) or `import-ics FILE`, or add meetings with `add`.\n")
    out = "\n".join(L) + "\n"
    if a.out:
        open(a.out, "w").write(out)
    print(out)

def cmd_projects(a, rules):
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=a.days)
    per = collections.Counter()
    for sid, cwd, ev in read_transcripts(since):
        ev.sort(key=lambda e: e[0])
        for b in build_blocks([(e[0], e[1]) for e in ev], 10):
            per[cwd] += (b["end"] - b["start"]).total_seconds() / 60 + 2
    print(f"# Folders you worked in, last {a.days} days (middle estimate)\n")
    print("| Folder | Time | Maps to |\n|---|---|---|")
    for cwd, mins in per.most_common():
        proj, mixed = folder_project(cwd, rules)
        print(f"| {cwd} | {hm(mins)} | {'(mixed: keywords)' if mixed else proj} |")

# ---------------------------------------------------------------- invoice
def cmd_invoice(a, rules):
    d_from, d_to = dt.date.fromisoformat(a.__dict__["from"]), dt.date.fromisoformat(a.to)
    tz = get_tz(rules)
    since = dt.datetime.combine(d_from, dt.time(0, 0), tz).astimezone(dt.timezone.utc)
    until = dt.datetime.combine(d_to, dt.time(23, 59), tz)
    result, calls, tz = compute(rules, since, until)
    result = merge_calls(result, calls)
    cl = rules["clients"].get(a.client, {})
    rate = a.rate if a.rate is not None else cl.get("rate")
    vat = a.vat or cl.get("vat", "excl")
    cur = cl.get("currency", "EUR")
    if rate is None:
        sys.exit(f"No rate for {a.client}: pass --rate or add it under \"clients\" in {os.path.join(HOMEDIR, 'rules.json')}")
    rnd = rules["round_minutes"]
    callmap = {c["id"]: c for c in calls}
    per_day = collections.defaultdict(lambda: collections.defaultdict(int))
    for m, v in result[a.basis].items():
        if v[1] != a.client:
            continue
        day = dt.datetime.fromtimestamp(m * 60, tz).date()
        if not (d_from <= day <= d_to):
            continue
        if len(v) > 3 and v[3] in callmap and not callmap[v[3]].get("activity"):
            label = f"Call: {callmap[v[3]]['title']}"
        elif len(v) > 3 and v[3] in callmap:
            label = f"{callmap[v[3]]['activity']}: {callmap[v[3]]['title']}"
        else:
            label = f"Work: {v[2]}"
        per_day[day][label] += 1
    rows, total_exact = [], 0
    for day in sorted(per_day):
        day_total = sum(per_day[day].values())
        total_exact += day_total
        rows += [(day, lab, mins) for lab, mins in sorted(per_day[day].items(), key=lambda kv: -kv[1])]
        rows.append((day, "Day total", day_total))
    billed = int(math.ceil(total_exact / rnd) * rnd)
    hours = billed / 60
    L = [f"# DRAFT timesheet: {a.client}, {d_from} to {d_to}\n",
         f"Draft, not an invoice. Basis: {a.basis} estimate; daily lines are exact; the total is rounded up once to {rnd} minutes.\n",
         "| Date | Work | Minutes |", "|---|---|---|"]
    L += [f"| {day:%a %d %b %Y} | {lab} | {mins} |" for day, lab, mins in rows]
    L += ["", f"**Exact time:** {hm(total_exact)}  \n**Billable (rounded):** {hm(billed)} = {hours:.2f} h  ",
          f"**Rate:** {cur} {rate}/h {'excluding VAT' if vat == 'excl' else 'including VAT and taxes'}  ",
          f"**Amount:** {cur} {hours * rate:,.2f}" + ("  \nVAT added or reverse-charged as applicable for the invoicing entity." if vat == "excl" else ""), ""]
    out = "\n".join(L) + "\n"
    stem = f"timesheet-{a.client.lower().replace(' ', '-')}-{d_from}-{d_to}"
    outdir = a.outdir or os.path.join(HOMEDIR, "out")
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, stem + ".md"), "w").write(out)
    with open(os.path.join(outdir, stem + ".csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["date", "work", "minutes"])
        w.writerows([(d.isoformat(), lab, mins) for d, lab, mins in rows])
    print(out)
    print(f"Saved to {outdir}/{stem}.md and .csv")

# ---------------------------------------------------------------- edit commands
def cmd_add(a, rules):
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, "overrides.json")
    over = jload(p) if os.path.exists(p) else []
    entry = {"date": a.date, "match": a.match or a.title or a.project, "minutes": a.minutes, "project": a.project}
    if a.title: entry["title"] = a.title
    if a.time: entry["time"] = a.time
    if a.activity: entry["activity"] = a.activity
    if a.note: entry["note"] = a.note
    over.append(entry)
    jdump(over, p)
    print("saved:", json.dumps(entry, ensure_ascii=False))

def cmd_assign(a, rules):
    rules["call_rules"].insert(0, [a.field, a.regex, a.project])
    save_rules(rules)
    print(f"rule saved: {a.field} matching /{a.regex}/ -> {a.project}")

def cmd_init(a, rules):
    os.makedirs(os.path.join(HOMEDIR, "data"), exist_ok=True)
    p = os.path.join(HOMEDIR, "rules.json")
    if os.path.exists(p):
        print(f"{p} already exists, left unchanged")
    else:
        save_rules(STARTER_RULES)
        print(f"created {p}")
    print("Fields:\n" + "\n".join(f"  {k}: {v}" for k, v in RULES_HELP.items()))

def main():
    ap = argparse.ArgumentParser(description="claude-worklog")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    pr = sub.add_parser("projects"); pr.add_argument("--days", type=int, default=30)
    f = sub.add_parser("fetch"); f.add_argument("--days", type=int, default=14)
    ic = sub.add_parser("import-ics"); ic.add_argument("file")
    r = sub.add_parser("report"); r.add_argument("--days", type=int, default=14); r.add_argument("--out", default="")
    i = sub.add_parser("invoice")
    i.add_argument("--client", required=True); i.add_argument("--from", required=True); i.add_argument("--to", required=True)
    i.add_argument("--basis", choices=EST, default="middle"); i.add_argument("--rate", type=float)
    i.add_argument("--vat", choices=["excl", "incl"]); i.add_argument("--outdir", default="")
    ad = sub.add_parser("add")
    ad.add_argument("--date", required=True); ad.add_argument("--minutes", type=int, required=True)
    ad.add_argument("--project", required=True); ad.add_argument("--title"); ad.add_argument("--match")
    ad.add_argument("--time"); ad.add_argument("--activity"); ad.add_argument("--note")
    asg = sub.add_parser("assign")
    asg.add_argument("--field", choices=["attendees", "title", "calendar"], required=True)
    asg.add_argument("--regex", required=True); asg.add_argument("--project", required=True)
    a = ap.parse_args()
    rules = load_rules()
    {"init": cmd_init, "projects": cmd_projects, "fetch": cmd_fetch, "import-ics": cmd_import_ics, "report": cmd_report,
     "invoice": cmd_invoice, "add": cmd_add, "assign": cmd_assign}[a.cmd](a, rules)

if __name__ == "__main__":
    main()
