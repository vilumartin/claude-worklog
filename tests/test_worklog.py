import datetime as dt, importlib.util, json, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module(home, projects):
    os.environ["WORKLOG_HOME"] = home
    os.environ["CLAUDE_PROJECTS_DIR"] = projects
    spec = importlib.util.spec_from_file_location("worklog", os.path.join(ROOT, "scripts", "worklog.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def write_session(projects, folder, sid, cwd, events):
    """events: list of (datetime, 'user'|'assistant')"""
    d = os.path.join(projects, folder)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, sid + ".jsonl"), "w") as fh:
        for ts, kind in events:
            msg = {"role": kind, "content": "hello" if kind == "user" else [{"type": "text", "text": "hi"}]}
            fh.write(json.dumps({"type": kind, "timestamp": ts.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                                 "cwd": cwd, "message": msg}) + "\n")


class WorklogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.projects = os.path.join(self.tmp.name, "projects")
        os.makedirs(os.path.join(self.home, "data"))
        self.w = load_module(self.home, self.projects)
        self.base = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).replace(second=0, microsecond=0)
        self.since = self.base - dt.timedelta(days=1)

    def tearDown(self):
        self.tmp.cleanup()

    def minutes(self, result, est, project=None):
        return sum(1 for v in result[est].values() if project is None or v[1] == project)

    def test_estimators_are_ordered_and_project_comes_from_folder_name(self):
        ev = []
        for i in range(6):  # a prompt every 8 minutes: events stay in one block for gap 10 and 20
            t = self.base + dt.timedelta(minutes=8 * i)
            ev += [(t, "user"), (t + dt.timedelta(minutes=1), "assistant")]
        write_session(self.projects, "p1", "s1", "/work/acme", ev)
        r = self.w.claude_minutes(self.w.load_rules(), self.since)
        lo, mid, hi = (self.minutes(r, e, "acme") for e in ("low", "middle", "high"))
        self.assertTrue(0 < lo <= mid <= hi, (lo, mid, hi))
        self.assertGreater(mid, lo)

    def test_idle_gap_is_not_counted(self):
        ev = [(self.base, "user"), (self.base + dt.timedelta(minutes=1), "assistant"),
              (self.base + dt.timedelta(minutes=60), "user"), (self.base + dt.timedelta(minutes=61), "assistant")]
        write_session(self.projects, "p1", "s1", "/work/acme", ev)
        r = self.w.claude_minutes(self.w.load_rules(), self.since)
        self.assertLess(self.minutes(r, "high"), 20)  # two short blocks, not 62 minutes

    def test_parallel_sessions_do_not_double_count(self):
        ev = [(self.base + dt.timedelta(minutes=i), "user" if i % 2 == 0 else "assistant") for i in range(10)]
        write_session(self.projects, "p1", "s1", "/work/acme", ev)
        write_session(self.projects, "p2", "s2", "/work/beta", ev)
        r = self.w.claude_minutes(self.w.load_rules(), self.since)
        self.assertLessEqual(self.minutes(r, "middle"), 13)  # 10 minutes span + 2 tail, once

    def test_call_wins_over_claude_time(self):
        ev = [(self.base + dt.timedelta(minutes=i), "user" if i % 2 == 0 else "assistant") for i in range(30)]
        write_session(self.projects, "p1", "s1", "/work/acme", ev)
        tz = self.w.get_tz(self.w.load_rules())
        start = (self.base + dt.timedelta(minutes=5)).astimezone(tz).replace(tzinfo=None)
        cal = [{"calendar": "c", "uid": "u1", "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "end": (start + dt.timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S"), "allday": False,
                "status": "confirmed", "recurring": False, "attendees": ["me@x.com:accepted", "bob@client.com:accepted"], "title": "Call with Bob"}]
        json.dump(cal, open(os.path.join(self.home, "data", "calendar.json"), "w"))
        rules = self.w.load_rules()
        rules.update({"own_emails": ["me@x.com"], "call_rules": [["attendees", "client\\.com", "Client"]]})
        r = self.w.claude_minutes(rules, self.since)
        calls = self.w.load_calls(rules, self.since.astimezone(self.w.get_tz(rules)), dt.datetime.now(self.w.get_tz(rules)) + dt.timedelta(days=1))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["project"], "Client")
        r = self.w.merge_calls(r, calls)
        self.assertEqual(self.minutes(r, "middle", "Client"), 15)

    def test_same_meeting_in_two_calendars_is_counted_once(self):
        tz = self.w.get_tz(self.w.load_rules())
        start = (self.base).astimezone(tz).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")
        end = (self.base + dt.timedelta(minutes=30)).astimezone(tz).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")
        mk = lambda cal, uid, title: {"calendar": cal, "uid": uid, "start": start, "end": end, "allday": False, "status": "confirmed",
                                      "recurring": False, "attendees": ["me@x.com:accepted", "bob@y.com:accepted"], "title": title}
        json.dump([mk("a", "1", "Sync"), mk("b", "2", "Sync with Bob")], open(os.path.join(self.home, "data", "calendar.json"), "w"))
        rules = self.w.load_rules(); rules["own_emails"] = ["me@x.com"]
        calls = self.w.load_calls(rules, self.since.astimezone(self.w.get_tz(rules)), dt.datetime.now(self.w.get_tz(rules)) + dt.timedelta(days=1))
        self.assertEqual(len(calls), 1)

    def test_manual_entry_and_override_duration(self):
        json.dump([{"date": (self.base.astimezone(self.w.get_tz(self.w.load_rules()))).date().isoformat(), "match": "Prep",
                    "minutes": 30, "project": "Acme", "time": "08:00", "title": "Prep", "activity": "Preparation"}],
                  open(os.path.join(self.home, "data", "overrides.json"), "w"))
        rules = self.w.load_rules()
        calls = self.w.load_calls(rules, self.since.astimezone(self.w.get_tz(rules)), dt.datetime.now(self.w.get_tz(rules)) + dt.timedelta(days=1))
        self.assertEqual([(c["title"], c["minutes"], c["project"]) for c in calls], [("Prep", 30, "Acme")])

    def test_ics_import(self):
        ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:abc\r\nSUMMARY:Planning call\r\nDTSTART:20261029T090000Z\r\n"
               "DTEND:20261029T093000Z\r\nATTENDEE;PARTSTAT=ACCEPTED:mailto:Bob@Client.com\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        ev = self.w.parse_ics(ics, self.w.get_tz(self.w.load_rules()))
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["title"], "Planning call")
        self.assertEqual(ev[0]["attendees"], ["bob@client.com:accepted"])

    def test_hook_logs_no_text(self):
        import subprocess
        p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "log_event.py")],
                           input=json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": "/w", "prompt": "SECRET"}),
                           text=True, env={**os.environ, "WORKLOG_HOME": self.home})
        line = open(os.path.join(self.home, "events.jsonl")).read()
        self.assertIn("UserPromptSubmit", line)
        self.assertNotIn("SECRET", line)


if __name__ == "__main__":
    unittest.main()
