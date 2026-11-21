#!/usr/bin/env python3
"""
assist.py - the Work Assistant That Remembers.

One file, four commands (plus a bonus):
    python assist.py ingest --day N
    python assist.py brief  --person P --date YYYY-MM-DD
    python assist.py ask    --person P --at ISO --ask "text"
    python assist.py forget --person P --what "text"
    python assist.py audit  --person P            (bonus)

Big ideas (read these first):
  1. PRIVACY FIRST. Every command starts from `visible_records(person)`.
     Records the person may not see never reach the logic, so they can never leak.
  2. NO MODEL NEEDED. Plain Python rules read the data. Token usage is honestly 0.
  3. MEMORY = store.json: the raw records, the feedback, preferences and forgets.
     Facts are worked out again on every call from what is allowed, so a forget
     or a privacy rule applies everywhere at once.
  4. NEWEST TRUSTED WINS. A correction from feedback > a higher role > a newer record.
  5. NO SOURCE, NO LINE. Every line points to the record ids it came from.
  6. RECORDS ARE DATA, NOT COMMANDS. We never follow text found inside a record.

Standard library only. Python 3.9+.
"""
import argparse, json, os, re, sys, time
from datetime import datetime, timedelta, date

STORE = os.environ.get("ASSIST_STORE", "store.json")
START = time.time()

# =====================================================================
# 1. Small helpers: files, dates, text
# =====================================================================
def pack_root():
    env = os.environ.get("R3_PACK")
    if env and os.path.isdir(os.path.join(env, "data")):
        return env
    return os.getcwd()

def data_path(*parts):
    return os.path.join(pack_root(), "data", *parts)

def read_jsonl(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def read_json(path, default):
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def new_store():
    return {"days": [], "records": [], "feedback": [], "forgets": []}

def load_store():
    return read_json(STORE, new_store())

def save_store(st):
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(st, f)

def usage():
    return {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "ms": int((time.time() - START) * 1000)}

def out(obj):
    print(json.dumps(obj))   # plain ASCII JSON: safe on Windows consoles too

# ---- time zones (zoneinfo if present, else a small fallback table) ----
FALLBACK_OFFSETS = {"Asia/Kolkata": 5.5, "Europe/London": 0, "UTC": 0}

def parse_utc(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")

def to_local(utc_str, zone):
    dt = parse_utc(utc_str)
    try:
        from zoneinfo import ZoneInfo
        from datetime import timezone
        return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zone)).replace(tzinfo=None)
    except Exception:
        return dt + timedelta(hours=FALLBACK_OFFSETS.get(zone, 0))

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def nice(d):
    """date -> '14 Nov 2026'. Simple English."""
    return f"{d.day} {d.strftime('%b')} {d.year}"

def short_date(d):
    return f"{d.day} {d.strftime('%b')}"

def iso_to_date(s):
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None

def find_date(text, today):
    """Find a calendar date like '14 Nov', 'Nov 14', '2026-11-14' or 'the 12th'."""
    t = text.lower()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*", t)
    if m:
        return date(today.year, MONTHS[m[2]], int(m[1]))
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})\b", t)
    if m:
        return date(today.year, MONTHS[m[1]], int(m[2]))
    m = re.search(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b", t)
    if m:
        d = date(today.year, today.month, int(m[1]))
        return d if d >= today - timedelta(days=7) else date(today.year, today.month % 12 + 1, int(m[1]))
    return None

def relative_day(text, today):
    """'kal'/'tomorrow' -> +1, 'today'/'eod' -> today, 'next monday'/'friday' -> that day."""
    t = text.lower()
    if re.search(r"\b(parso|day after tomorrow)\b", t):
        return today + timedelta(days=2)
    if re.search(r"\b(kal|tomorrow)\b", t):
        return today + timedelta(days=1)
    if re.search(r"\b(today|eod|aaj|tonight)\b", t):
        return today
    for i, wd in enumerate(WEEKDAYS):
        m = re.search(r"\b(next )?" + wd + r"\b", t)
        if m:
            ahead = (i - today.weekday()) % 7
            if m.group(1) and ahead == 0:
                ahead = 7
            return today + timedelta(days=ahead)
    return None

# ---- text ----
STOP = set("""a an the to of for in on at by with and or is are was were be been it its this that
these those my me i you your we our us he she they them his her their what who whom which when
where why how does do did done has have had can could will would should please now still any
anything about from as up so not no yes there here just tell know want need thing things one
owns own owner owned handles handle handling handled status due date deadline whats what's
is it's whose responsible""".split())

def words(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())

def content_words(text):
    return [w for w in words(text) if w not in STOP and len(w) > 1]

def sentences(body):
    parts = re.split(r"(?<=[.!?])\s+|\n+", body or "")
    return [p.strip() for p in parts if p.strip()]

INJECTION = re.compile(r"\b(assistant|ai|bot)\b\s*[:,]|ignore (your|all|previous) (rules|instructions)", re.I)

# =====================================================================
# 2. People, clients and PRIVACY
# =====================================================================
ROLE_RANK = [("founder", 6), ("ceo", 6), ("director", 5), ("manager", 5), ("lead", 4),
             ("senior", 3), ("executive", 3), ("intern", 1)]

def load_people():
    people = {}
    for org_id, org in read_json(data_path("people.json"), {}).items():
        for p in org.get("people", []):
            p = dict(p)
            p["org"] = org_id
            p["first"] = p.get("name", "").split()[0].lower() if p.get("name") else ""
            people[p["id"]] = p
    return people

def role_rank(pid, people):
    """Higher number = more trusted on 'who owns what'."""
    p = people.get(pid)
    if not p:
        return 0                      # outsiders and 'system'
    role = p.get("role", "").lower()
    for word, rank in ROLE_RANK:
        if word in role:
            return rank
    return 2

def can_see(person, record, people):
    """THE privacy rule. Used before anything else."""
    me = people.get(person)
    if not me or record.get("org") != me["org"]:
        return False                                  # other company: never
    v = record.get("visibility", "team")
    if v == "team":
        return True
    if v == "private":
        return record.get("author") == person         # only the author
    if v == "restricted":
        return person in (record.get("readers") or [])
    return False                                      # unknown: hide

def is_forgotten(record, forgets):
    """A record is hidden if its author asked to forget something it mentions."""
    body = (record.get("body") or "").lower()
    for f in forgets:
        if record.get("author") == f["person"] and f["words"] and all(w in body for w in f["words"]):
            return True
    return False

def visible_records(person, st, people, upto=None):
    """Everything this person may use. `upto` = an ISO time; newer records are ignored."""
    out = []
    for r in st["records"]:
        if upto and r.get("at", "") > upto:
            continue
        if can_see(person, r, people) and not is_forgotten(r, st["forgets"]):
            out.append(r)
    return out

def is_noise(r, clients):
    """Newsletters, system notifications and anything that looks like an order to us."""
    if r.get("type") == "notification" or r.get("author") == "system":
        return True
    if INJECTION.search(r.get("body") or ""):
        return True
    a = r.get("author") or ""
    if a.startswith("ext:"):
        # outsiders count only if they are staff of one of our clients
        domain = a.split("@")[-1]
        return not any(domain in c["domains"] for c in clients.values())
    return False

def load_clients(records):
    """Clients plus what we LEARN from the data: staff email domains and their country."""
    clients = {}
    for c in read_json(data_path("clients.json"), []):
        clients[c["id"]] = {"id": c["id"], "name": c["name"], "domains": set(), "countries": set()}
    for r in records:
        cid = r.get("client")
        if cid not in clients:
            continue
        addrs = [r.get("author") or ""] + list(r.get("to") or []) + list(r.get("attendees") or [])
        for a in addrs:
            if isinstance(a, str) and a.startswith("ext:") and "@" in a:
                dom = a.split("@")[-1].lower()
                clients[cid]["domains"].add(dom)
                tld = dom.rsplit(".", 1)[-1]
                if len(tld) == 2:
                    clients[cid]["countries"].add(tld)
    return clients

# World knowledge (not client nicknames): which country a city is in.
CITY_COUNTRY = {"london": "uk", "manchester": "uk", "uk": "uk", "british": "uk", "england": "uk",
                "mumbai": "in", "delhi": "in", "bangalore": "in", "bengaluru": "in", "pune": "in",
                "hyderabad": "in", "chennai": "in", "kolkata": "in", "india": "in", "indian": "in",
                "dubai": "ae", "singapore": "sg", "sydney": "au", "berlin": "de", "paris": "fr",
                "new york": "us", "us": "us", "american": "us"}

def is_abbrev_of(token, cid):
    """'NB' -> northbeam: letters appear in order and the first letter matches."""
    t = token.lower()
    if t[0] != cid[0]:
        return False
    pos = 0
    for ch in t:
        pos = cid.find(ch, pos)
        if pos < 0:
            return False
        pos += 1
    return True

def find_clients(text, clients):
    """Which clients does a piece of text talk about? Returns [(phrase, client_id)]."""
    found = []
    low = (text or "").lower()
    for cid, c in clients.items():
        name = c["name"].lower()
        if name in low:
            found.append((c["name"], cid)); continue
        hit = None
        for tok in re.findall(r"[A-Za-z]+", text or ""):
            tl = tok.lower()
            if tl == cid or (len(tl) >= 4 and cid.startswith(tl)):
                hit = tok
            elif len(tok) == 2 and tok.isupper() and is_abbrev_of(tok, cid):
                hit = tok
            if hit:
                break
        if not hit:
            for city, country in CITY_COUNTRY.items():
                m = re.search(r"\bthe " + city + r" (client|account|team|customer)\b", low)
                if m and country in c["countries"]:
                    hit = m.group(0); break
        if hit:
            found.append((hit, cid))
    return found

def record_client(r, clients):
    """The client a record is about: its tag, else a clear mention in its text."""
    if r.get("client") in clients:
        return r["client"]
    hits = find_clients(r.get("body", ""), clients)
    return hits[0][1] if len(hits) == 1 else None

# ---- who is 'Arjun'? ----
def involved(r):
    ids = {r.get("author"), r.get("owner")}
    for k in ("to", "attendees", "readers"):
        ids.update(x for x in (r.get(k) or []) if isinstance(x, str))
    return ids

def resolve_name(name, asker, recs, people, context_words=()):
    """Turn a name into person ids, best first. Ties are returned together."""
    name = name.lower().strip()
    org = people.get(asker, {}).get("org")
    cands = [p for p in people.values() if p["org"] == org and
             (p.get("name", "").lower() == name or p["first"] == name)]
    if len(cands) <= 1:
        return [c["id"] for c in cands], {}
    my_clients = {r.get("client") for r in recs if asker in involved(r) and r.get("client")}
    ctx = set(context_words)
    scores, evidence = {}, {}
    for c in cands:
        s, ev = 0, []
        role_words = set(content_words(c.get("role", "") + " " + c.get("team", "")))
        if ctx & role_words:
            s += 3                                    # the topic fits their job
        for r in recs:
            inv = involved(r)
            if c["id"] in inv and asker in inv:
                s += 1; ev.append(r["id"])            # worked together
            elif c["first"] in words(r.get("body")) and r.get("client") in my_clients \
                    and role_words & set(content_words(r.get("body"))):
                s += 2; ev.append(r["id"])            # named on my client, in their job
        scores[c["id"]], evidence[c["id"]] = s, ev
    best = max(scores.values())
    top = [pid for pid, s in scores.items() if s == best]
    return top, evidence

def person_name(pid, people):
    return people.get(pid, {}).get("name", pid)

# =====================================================================
# 3. Facts we read out of the records (all rule-based)
# =====================================================================
def task_states(recs):
    """task_id -> current state. Only REAL changes count, not the snapshot in comments."""
    tasks = {}
    for r in sorted((x for x in recs if x.get("type") == "task" and x.get("task_id")), key=lambda x: x["at"]):
        t = tasks.setdefault(r["task_id"], {"id": r["task_id"], "client": r.get("client"),
                                            "history": [], "created": r["id"]})
        t["title"] = r.get("title", t.get("title", ""))
        field = (r.get("change") or {}).get("field")
        if field == "created" or "status" not in t:
            for k in ("owner", "due", "status"):
                t.setdefault(k, r.get(k)); t.setdefault(k + "_src", r["id"])
        if field in ("owner", "due", "status"):
            t[field] = r["change"].get("to", r.get(field))
            t[field + "_src"] = r["id"]
            t["history"].append(r)
    return tasks

def extract_owner_facts(recs, people, clients):
    """Sentences like 'Arjun takes over Northbeam billing from Kavya' or 'Billing contact: Kavya'."""
    facts, prev_lines = [], {}
    pat_claim = re.compile(
        r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?) (?:now owns|owns|takes over|is taking over|will take over|"
        r"has taken over|handles|is handling|will handle) (.+?)(?: from ([A-Z][a-z]+(?: [A-Z][a-z]+)?))?"
        r"(?:,| now| going forward|\.|$)")
    pat_label = re.compile(r"^([A-Za-z][A-Za-z ]{2,30}?) (?:contact|owner|lead|poc): ([A-Z][a-z]+(?: [A-Z][a-z]+)?)")
    for r in sorted(recs, key=lambda x: x["at"]):
        if is_noise(r, clients) or r.get("type") in ("task", "event"):
            continue
        lines = sentences(r.get("body"))
        if r.get("type") == "doc":
            # a new doc version repeats old lines; only NEW lines are new statements
            old = prev_lines.get(r.get("doc_id"), set())
            prev_lines[r.get("doc_id")] = set(lines)
            lines = [l for l in lines if l not in old]
        for line in lines:
            if line.endswith("?"):
                continue                              # a question is not a claim
            for m in [pat_claim.search(line), pat_label.search(line)]:
                if not m:
                    continue
                who, what = (m[1], m[2]) if m.re is pat_claim else (m[2], m[1])
                topic = [w for w in content_words(what) if not find_clients(w, clients)]
                if not topic:
                    continue
                ids, _ = resolve_name(who.split()[0] if len(who.split()) == 1 else who,
                                      r.get("author"), recs, people, topic)
                if len(ids) != 1:
                    ids, _ = resolve_name(who.split()[0], r.get("author"), recs, people, topic)
                if len(ids) != 1:
                    continue
                prev = m[3] if m.re is pat_claim else None
                facts.append({"kind": "owner", "topic": topic, "value": ids[0], "prev": prev,
                              "client": record_client(r, clients) or (find_clients(what, clients) or [(0, None)])[0][1],
                              "src": r["id"], "at": r["at"], "author": r.get("author"),
                              "rank": role_rank(r.get("author"), people), "correction": False})
    return facts

def extract_date_facts(recs, clients):
    """'Launch date: 10 Nov' in a doc, or 'move the launch to 14 Nov' in a mail."""
    facts, prev_lines = [], {}
    pat_label = re.compile(r"^([A-Za-z][A-Za-z ]{2,30}?) date: (.+)$", re.I)
    pat_move = re.compile(r"\bmov(?:e|ing|ed) (?:the )?([a-z][a-z ]{2,30}?) (?:date )?to (.+)$", re.I)
    for r in sorted(recs, key=lambda x: x["at"]):
        if is_noise(r, clients) or r.get("type") in ("task", "event", "note"):
            continue
        today = parse_utc(r["at"]).date()
        lines = sentences(r.get("body"))
        if r.get("type") == "doc":
            old = prev_lines.get(r.get("doc_id"), set())
            prev_lines[r.get("doc_id")] = set(lines)
            lines = [l for l in lines if l not in old]
        for line in lines:
            m = pat_label.search(line) or pat_move.search(line)
            if not m:
                continue
            d = find_date(m[2], today)
            topic = content_words(m[1])
            if d and topic:
                facts.append({"kind": "date", "topic": topic, "value": d.isoformat(), "src": r["id"],
                              "at": r["at"], "client": record_client(r, clients)})
    return facts

PROMISE_PATTERNS = [
    re.compile(r"^(?:hi [a-z ]+,\s*)?(?:i will|i'll|will|we will|we'll) (?:send|share|deliver|submit|get you) "
               r"(the .+?) (?:by|before|on) (.+?)[.!]?$", re.I),
    re.compile(r"^(the .+?) ((?:next )?\w+) tak (?:bhej|share|de|send|submit)", re.I),
]
DELIVERY = re.compile(r"\b(?:sharing|attached|attaching|here is|here's|sent) (the .+?)(?: as promised|[.!]|$)", re.I)

def norm_obj(s):
    return " ".join(content_words(s))

def extract_promises(recs, people, clients):
    """Promises still open: owner, what, due. Closed when the same thing is delivered later."""
    promises, deliveries = [], []
    for r in sorted(recs, key=lambda x: x["at"]):
        if r.get("type") not in ("mail", "chat") or is_noise(r, clients):
            continue
        if (r.get("author") or "") not in people:
            continue
        zone = people[r["author"]].get("zone", "UTC")
        today = to_local(r["at"], zone).date()
        for line in sentences(r.get("body")):
            dm = DELIVERY.search(line)
            if dm:
                deliveries.append({"obj": norm_obj(dm[1]), "what": dm[1], "src": r["id"], "at": r["at"],
                                   "author": r["author"], "client": record_client(r, clients)})
                continue
            for pat in PROMISE_PATTERNS:
                m = pat.search(line)
                if m:
                    due = find_date(m[2], today) or relative_day(m[2], today)
                    if due:
                        promises.append({"owner": r["author"], "what": m[1], "obj": norm_obj(m[1]),
                                         "due": due.isoformat(), "src": r["id"], "at": r["at"],
                                         "client": record_client(r, clients)})
                    break
    for p in promises:
        p["delivered"] = next((d for d in deliveries if d["obj"] == p["obj"] and d["at"] > p["at"]), None)
    return promises, deliveries

def extract_leaves(recs, people, clients):
    """'I'm on leave from 9 Nov till the 12th' -> a fact that EXPIRES after the 12th."""
    out = []
    for r in recs:
        body = r.get("body") or ""
        if is_noise(r, clients) or not re.search(r"\b(on leave|out of office|ooo|off from|away from)\b", body, re.I):
            continue
        today = parse_utc(r["at"]).date()
        m_end = re.search(r"\b(?:till|until|to|through)\s+(.+?)(?:[.|]|$)", body, re.I)
        m_start = re.search(r"\bfrom\s+(.+?)\s+(?:till|until|to|through)\b", body, re.I)
        end = find_date(m_end[1], today) if m_end else None
        start = find_date(m_start[1], today) if m_start else today
        if end:
            out.append({"person": r.get("author"), "start": start.isoformat(), "end": end.isoformat(), "src": r["id"]})
    return out

def corrections_from_feedback(st, people, clients, recs, asker):
    """Feedback 'No, Arjun owns billing now' becomes an owner fact that beats everything.
    It is a team fact: it applies to everyone in the corrector's company, nobody else."""
    facts = []
    org = people.get(asker, {}).get("org")
    meetings = {r.get("event_id"): r for r in st["records"] if r.get("type") == "event"}
    pat = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?) (?:now owns|owns|handles|is handling|is the owner of) (.+?)"
                     r"(?:,| now|\.|$)")
    for fb in st["feedback"]:
        if fb.get("type") != "correction" or people.get(fb.get("person"), {}).get("org") != org:
            continue
        ev = meetings.get(fb.get("meeting")) or {}
        m = pat.search(fb.get("words", ""))
        if not m:
            continue
        topic = [w for w in content_words(m[2]) if not find_clients(w, clients)]
        ids, _ = resolve_name(m[1], fb["person"], recs, people, topic)
        if len(ids) == 1 and topic:
            facts.append({"kind": "owner", "topic": topic, "value": ids[0], "prev": None,
                          "client": ev.get("client") or (find_clients(m[2], clients) or [(0, None)])[0][1],
                          "src": None, "at": "9999-%02d" % fb.get("day", 0), "author": fb["person"],
                          "rank": 99, "correction": True})
    return facts

def date_corrections(st, people, asker):
    """Feedback like 'No, the launch is on 14 Nov' -> a date fact newer than any record."""
    facts, org = [], people.get(asker, {}).get("org")
    pat = re.compile(r"(?:no,?\s*)?(?:the )?([a-z][a-z0-9 ]{2,40}?) (?:is|is on|is due|is due on|moved to|is now|is now on) (.+)$", re.I)
    for fb in st["feedback"]:
        if fb.get("type") != "correction" or people.get(fb.get("person"), {}).get("org") != org:
            continue
        m = pat.search(fb.get("words", ""))
        d = find_date(m[2], date(2026, 11, 2)) if m else None
        if d:
            facts.append({"kind": "date", "topic": content_words(m[1]), "value": d.isoformat(), "src": None,
                          "at": "9999-%02d" % fb.get("day", 0), "client": None, "correction": True})
    return facts

def best_fact(facts):
    """Who wins: a correction > a higher role > newer."""
    return max(facts, key=lambda f: (f.get("correction", False), f.get("rank", 0), f["at"])) if facts else None

def facts_for(facts, topic_words, client):
    tw = set(topic_words)
    return [f for f in facts if tw & set(f["topic"]) and (client is None or f["client"] in (client, None))]

# =====================================================================
# 4. Preferences and feedback memory
# =====================================================================
def prefs_for(person, st):
    p = {"max_changes": None, "blockers_first": False, "skip_words": [], "boost_words": [], "notes": []}
    for fb in st["feedback"]:
        if fb.get("person") != person:
            continue
        w = (fb.get("words") or "").lower()
        if fb.get("type") == "preference":
            p["notes"].append(fb["words"])
            m = re.search(r"max(?:imum)?\s+(\d+)", w) or re.search(r"(?:at most|only|no more than)\s+(\d+)", w)
            if m:
                p["max_changes"] = int(m[1])
            if "block" in w and ("first" in w or "top" in w):
                p["blockers_first"] = True
            m = re.search(r"\b(?:skip|ignore|no more|hide|drop)\s+(.+?)(?: in my briefs| for me|[.]|$)", w)
            if m:
                p["skip_words"].append(content_words(m[1]))
        elif fb.get("type") == "verdict":
            topic = content_words(fb.get("topic", ""))
            if fb.get("verdict") == "ignored" and topic:
                p["skip_words"].append(topic)
            elif fb.get("verdict") == "kept" and topic:
                p["boost_words"].append(topic)
    return p

def matches_topic(text, topic):
    tw = set(words(text))
    hits = sum(1 for w in topic if w in tw)
    return topic and hits >= max(1, (len(topic) + 1) // 2)

def forget_words(what):
    w = re.sub(r"(?i)^\s*(please\s+)?forget\s+(everything\s+|what\s+)?(i\s+(said|told you|wrote|mentioned)\s+)?(about\s+)?", "", what)
    return [x for x in content_words(w) if x not in ("said", "told", "mentioned")]

# =====================================================================
# 5. Commands
# =====================================================================
def cmd_ingest(day):
    st = new_store() if day == 1 else load_store()
    if day not in st["days"]:
        st["records"] += read_jsonl(data_path("days", f"day-{day:02d}.jsonl"))
        for fb in read_jsonl(data_path("feedback", f"day-{day - 1:02d}.jsonl")):
            st["feedback"].append(fb)
            if fb.get("type") == "forget":
                add_forget(st, fb["person"], fb.get("words", ""))
        st["days"].append(day)
        save_store(st)
    out({"ok": True, "day": day, "records": len(st["records"]), "feedback": len(st["feedback"])})

def add_forget(st, person, what):
    entry = {"person": person, "what": what, "words": forget_words(what)}
    if entry not in st["forgets"]:
        st["forgets"].append(entry)

def cmd_forget(person, what):
    st = load_store()
    add_forget(st, person, what)
    save_store(st)
    out({"ok": True, "forgetting": forget_words(what)})

# ---------------------------------------------------------------- brief
STATUS_TEXT = {"done": "is done", "blocked": "is blocked", "cancelled": "was cancelled",
               "in_progress": "is now in progress", "todo": "is back to to-do"}

def build_changes(cid, since, recs, people, clients, tasks):
    """Everything that changed for this client after `since` (ISO time). Each line has sources."""
    ch = []
    # (a) task status / owner / due changes
    for t in tasks.values():
        if t["client"] != cid:
            continue
        for field in ("status", "owner", "due"):
            moves = [h for h in t["history"] if h["change"]["field"] == field and h["at"] >= since]
            if not moves:
                continue
            old, new, src = moves[0]["change"].get("from"), moves[-1]["change"].get("to"), moves[-1]["id"]
            if old == new:
                continue
            if field == "status":
                text = f"{t['title']} {STATUS_TEXT.get(new, 'is ' + str(new))}"
                if old == "blocked" and new != "blocked":
                    text = f"{t['title']} is unblocked (now {STATUS_WORDS.get(new, new)})"
                why = re.sub(r"(?i)^blocked:\s*", "", moves[-1].get("body", "")).rstrip(".")
                if new == "blocked" and why:
                    text += f" ({why})"
                prio = 1 if new in ("blocked", "cancelled") else 2
                kind = "blocked" if new == "blocked" else "status"
            elif field == "owner":
                text = f"{t['title']} now owned by {person_name(new, people)} (was {person_name(old, people)})"
                prio, kind = 2, "owner"
            else:
                o, n = iso_to_date(old or ""), iso_to_date(new or "")
                text = f"{t['title']} due date moved from {short_date(o) if o else old} to {nice(n) if n else new}"
                prio, kind = 2, "date"
            ch.append({"text": text, "sources": [src], "prio": prio, "kind": kind, "at": moves[-1]["at"],
                       "task": t})
    # (b) decisions written in meeting notes
    for r in recs:
        if r.get("type") == "note" and r["at"] >= since and record_client(r, clients) == cid:
            for line in sentences(r["body"]):
                m = re.match(r"(?i)decision:\s*(.+)", line)
                if m:
                    ch.append({"text": "Decision: " + m[1].rstrip("."), "sources": [r["id"]], "prio": 1,
                               "kind": "decision", "at": r["at"]})
    # a decision about a task replaces that task's own line (one line per topic)
    for d in [c for c in ch if c["kind"] == "decision"]:
        for c in list(ch):
            if c.get("task") and set(content_words(c["task"]["title"])) <= set(words(d["text"])):
                d["sources"] += c["sources"]; ch.remove(c)
    # (c) who owns a topic (billing etc.) and (d) key dates (launch etc.)
    for fx in (extract_owner_facts(recs, people, clients), extract_date_facts(recs, clients)):
        topics = {}
        for f in fx:
            if f["client"] == cid:
                topics.setdefault(" ".join(sorted(f["topic"])), []).append(f)
        merged = {}
        for f in [x for x in fx if x["client"] == cid]:        # join 'launch' and 'launch date'
            key = next((k for k in merged if set(k.split()) & set(f["topic"])), " ".join(sorted(f["topic"])))
            merged.setdefault(key, []).append(f)
        for key, fs in merged.items():
            before = best_fact([f for f in fs if f["at"] < since]) if fs[0]["kind"] == "owner" else \
                max([f for f in fs if f["at"] < since], key=lambda f: f["at"], default=None)
            now = best_fact(fs) if fs[0]["kind"] == "owner" else max(fs, key=lambda f: f["at"])
            if not before and now:          # first meeting: compare with the first value we ever saw
                first = min(fs, key=lambda f: f["at"])
                before = first if first["value"] != now["value"] else None
            if not now or now["at"] < since or (before and before["value"] == now["value"]):
                continue
            srcs = sorted({f["src"] for f in fs if f["value"] == now["value"] and f["at"] >= since})
            client_name = clients[cid]["name"].split()[0]
            if now["kind"] == "owner":
                was = person_name(before["value"], people) if before else now.get("prev")
                text = f"{person_name(now['value'], people)} now owns {client_name} {' '.join(now['topic'])}"
                text += f" (was {was})" if was else ""
            else:
                d = date.fromisoformat(now["value"])
                name = " ".join(w for w in now["topic"] if w != "date").capitalize()
                text = f"{name} moved from {short_date(date.fromisoformat(before['value']))} to {nice(d)}" \
                    if before else f"{name} date set to {nice(d)}"
            ch.append({"text": text, "sources": srcs, "prio": 1, "kind": now["kind"], "at": now["at"]})
    # (e) things delivered (closes a promise)
    promises, deliveries = extract_promises(recs, people, clients)
    promised = {p["obj"] for p in promises}
    for d in deliveries:
        # only a delivery that closes a real promise is news ("the minutes" is routine)
        if d["client"] == cid and d["at"] >= since and d["obj"] in promised:
            ch.append({"text": f"{person_name(d['author'], people).split()[0]} delivered {d['what']}",
                       "sources": [d["src"]], "prio": 3, "kind": "delivered", "at": d["at"]})
    return ch

def make_question(top, promises, people):
    if not top:
        return None
    c = top[0]
    if c["kind"] == "blocked":
        q = f"What do we need to unblock {c['text'].split(' is blocked')[0]}?"
    elif c["kind"] == "date":
        q = f"Does everyone agree with the new date: {c['text']}?"
    elif c["kind"] == "owner":
        q = f"Does the handover look complete: {c['text']}?"
    elif c["kind"] == "decision":
        q = f"What does this decision change for our plan: {c['text']}?"
    elif promises:
        p = promises[0]
        q = f"Is {p['what']} from {person_name(p['owner'], people)} still on track for {p['due']}?"
        return {"text": q, "sources": p["sources"]}
    else:
        q = f"Anything the client wants to discuss about: {c['text']}?"
    return {"text": q, "sources": c["sources"]}

def cmd_brief(person, day_str):
    st, people = load_store(), load_people()
    recs = visible_records(person, st, people)
    clients = load_clients(recs)
    zone = people.get(person, {}).get("zone", "UTC")
    prefs = prefs_for(person, st)

    events = {}
    for r in sorted((x for x in recs if x.get("type") == "event"), key=lambda x: x["at"]):
        events[r.get("event_id")] = r                      # newest version of each meeting
    mine = [e for e in events.values() if person in (e.get("attendees") or []) and e.get("start")
            and to_local(e["start"], zone).date().isoformat() == day_str
            and "cancel" not in (e.get("status", "") + e.get("title", "")).lower()]
    mine.sort(key=lambda e: e["start"])

    tasks = task_states(recs)
    promises_all, _ = extract_promises(recs, people, clients)
    result = []
    for ev in mine:
        cid = ev.get("client") if ev.get("client") in clients else record_client(ev, clients)
        brief = {"meeting_id": ev["event_id"], "status": "nothing_new", "changed": [], "promises": [],
                 "open_these": [], "question_to_ask": None}
        if cid:
            # "since the last time I met this client": the day of my previous meeting with them
            prev = [e for e in events.values() if e is not ev and person in (e.get("attendees") or [])
                    and e.get("client") == cid and to_local(e["start"], zone).date().isoformat() < day_str]
            if prev:
                last = max(prev, key=lambda e: e["start"])
                local_day = to_local(last["start"], zone).date()
                since = (datetime.combine(local_day, datetime.min.time())
                         - (to_local(last["start"], zone) - parse_utc(last["start"]))).strftime("%Y-%m-%dT%H:%M:%S")
            else:
                since = "0000"
            changes = build_changes(cid, since, recs, people, clients, tasks)
            # personal preferences and past feedback
            changes = [c for c in changes if not any(matches_topic(c["text"], t) for t in prefs["skip_words"])]
            for c in changes:
                c["boost"] = any(matches_topic(c["text"], t) for t in prefs["boost_words"])
                if prefs["blockers_first"] and c["kind"] == "blocked":
                    c["prio"] = 0
            changes.sort(key=lambda c: (c["prio"], not c["boost"], c["at"]))
            if prefs["max_changes"]:
                changes = changes[:prefs["max_changes"]]
            if changes:
                open_p = [p for p in promises_all if p["client"] == cid and not p["delivered"]]
                brief["status"] = "brief"
                brief["changed"] = [{"text": c["text"], "sources": c["sources"]} for c in changes]
                brief["promises"] = [{"owner": p["owner"], "what": p["what"], "due": p["due"],
                                      "sources": [p["src"]]} for p in open_p]
                seen = []
                for c in changes:
                    if c["sources"] and c["sources"][0] not in seen and len(seen) < 3:
                        seen.append(c["sources"][0])
                        brief["open_these"].append({"record": c["sources"][0], "why": c["text"]})
                brief["question_to_ask"] = make_question(changes, brief["promises"], people)
        brief["usage"] = usage()
        result.append(brief)
    out(result)

# ---------------------------------------------------------------- ask
def answer(text, sources, matched, u=None):
    return {"answer": {"text": text, "sources": sorted(set(s for s in sources if s))}, "matched": matched,
            "clarify": None, "refused": None, "usage": usage()}

def match_tasks(q, tasks, client_ids):
    qw = set(words(q))
    scored = []
    for t in tasks.values():
        tw = [w for w in content_words(t["title"]) if not client_ids or True]
        tw = [w for w in tw if w not in {"to"}]
        if not tw:
            continue
        hit = sum(1 for w in tw if w in qw) / len(tw)
        if hit >= 0.6:
            bonus = 0.5 if t["client"] in client_ids else (-1 if client_ids else 0)
            scored.append((hit + bonus, t))
    if not scored:
        return []
    best = max(s for s, _ in scored)
    return [t for s, t in scored if s == best]

STATUS_WORDS = {"todo": "not started yet (to do)", "in_progress": "in progress", "done": "done",
                "blocked": "blocked", "cancelled": "cancelled"}

def lower_title(title):
    """'UAT test plan' -> 'UAT test plan', 'Homepage redesign' -> 'homepage redesign'."""
    return " ".join(w if w.isupper() and len(w) > 1 else w.lower() for w in title.split())

def task_answer(t, intent, people):
    title = t["title"]
    m = [{"phrase": title, "id": t["id"], "sources": [t["created"]]}]
    if intent == "owner":
        m.append({"phrase": person_name(t["owner"], people), "id": t["owner"],
                  "sources": [x for x in [t["owner_src"]] if x]})
        return answer(f"{person_name(t['owner'], people)} owns the {lower_title(title)}.", [t["owner_src"]], m)
    if intent == "due":
        d = iso_to_date(t.get("due") or "")
        return answer(f"The {lower_title(title)} is due on {nice(d) if d else t.get('due')}.", [t["due_src"]], m)
    s = STATUS_WORDS.get(t["status"], t["status"])
    yes = "Yes, the" if t["status"] == "done" else ("No, the" if intent == "done" else "The")
    return answer(f"{yes} {lower_title(title)} is {s}.", [t["status_src"]], m)

def detect_intent(q):
    l = q.lower()
    if re.search(r"\bwho\b.*\b(own|owns|handles?|handling|responsible|in charge|takes care|working on|works on|"
                 r"doing|contact|assigned)\b|\bowner\b|\bwho is the\b", l):
        return "owner"
    if re.search(r"\b(what|which)\b.*\b(changed|changes|new|happened)\b|\bwhat'?s new\b", l):
        return "changes"
    if re.search(r"\b(blocked|blockers?|stuck)\b", l) and re.search(r"\b(what|which|any|list)\b", l):
        return "blocked"
    if re.search(r"\bmy (tasks|work|to-?dos?)\b|\bwhat (do|should) i (have|do)\b", l):
        return "my_tasks"
    if re.search(r"\b(i|my)\b.*\bpromis", l):
        return "my_promises"
    if re.search(r"\b(when|due|deadline|date|by when)\b", l):
        return "due"
    if re.search(r"\b(is|was|has)\b.*\b(done|finished|complete|completed|over)\b", l):
        return "done"
    if re.search(r"\b(status|progress|update on|how is|where are we)\b", l):
        return "status"
    return "other"

COMMON2 = set("am an as at be by do go he hi if in is it me my no of ok on or so to up us we".split())

def upper_abbrevs(q):
    """In a question, 'nb' or 'cl' may be typed in lowercase: treat them like 'NB'/'CL'."""
    return re.sub(r"\b([a-z]{2})\b", lambda m: m[1] if m[1] in COMMON2 else m[1].upper(), q)

def cmd_ask(person, at, q):
    st, people = load_store(), load_people()
    recs = visible_records(person, st, people, upto=at)
    clients = load_clients(recs)
    zone = people.get(person, {}).get("zone", "UTC")
    today = to_local(at, zone).date()
    intent = detect_intent(q)
    cl_hits = find_clients(upper_abbrevs(q), clients)
    client_ids = [c for _, c in cl_hits]
    matched = [{"phrase": ph, "id": c, "sources": []} for ph, c in cl_hits]
    tasks = task_states(recs)

    # A. "Which Arjun is that?" / "Who is Arjun?"
    m = re.search(r"\b(?:which|who is|who's)\s+([a-z]+)\b", q, re.I)
    if m and m[1].lower() in {p["first"] for p in people.values()}:
        m = [m[0], m[1].capitalize()]
        ctx = content_words(q)
        ids, ev = resolve_name(m[1], person, recs, people, ctx)
        if len(ids) == 1:
            p = people[ids[0]]
            src = (ev or {}).get(ids[0], [])[:3]
            matched.append({"phrase": m[1], "id": p["id"], "sources": src})
            note = f" This is the {m[1]} who works with you." if src else ""
            return out(answer(f"{p['name']} is the {p.get('role', 'team member')}.{note}", src, matched))
        if len(ids) > 1:
            return out(clarify(f"Which {m[1]} do you mean?", [{"id": i, "text": person_name(i, people)} for i in ids], matched))

    # B. leave / availability (facts that expire)
    if re.search(r"\b(leave|holiday|vacation|away|out of office|ooo|available|back)\b", q, re.I):
        names = [p for p in people.values() if p["org"] == people.get(person, {}).get("org")
                 and re.search(r"\b" + p["first"] + r"\b", q.lower())]
        if names:
            who = names[0]
            for lv in extract_leaves(recs, people, clients):
                if lv["person"] != who["id"]:
                    continue
                s, e = date.fromisoformat(lv["start"]), date.fromisoformat(lv["end"])
                matched.append({"phrase": who["first"].capitalize(), "id": who["id"], "sources": [lv["src"]]})
                if s <= today <= e:
                    return out(answer(f"Yes, {who['name']} is on leave until {nice(e)}.", [lv["src"]], matched))
                if today < s:
                    return out(answer(f"{who['name']} will be on leave from {short_date(s)} to {nice(e)}.", [lv["src"]], matched))
            return out(answer(f"I have no current leave on record for {who['name']}.", [], matched))

    # B2. list questions: what changed / what is blocked / my tasks / my promises
    if intent in ("changes", "blocked", "my_tasks", "my_promises"):
        return out(list_answer(intent, person, at, recs, people, clients, tasks, client_ids, matched))
        # B3. "What did I say about Rohan?" (own notes are fine, other people's private notes are refused)
    res = said_about(person, q, st, people, recs, clients, matched, at)
    if res:
        return out(res)

    # B4. a shared first name ("send the deck to Arjun") -> say which person, and which thing
    res = name_mention(person, q, people, recs, clients, client_ids, matched)
    if res:
        return out(res)
    # C. a task, found by its title words
    found = match_tasks(q, tasks, client_ids)
    # C2. or by a time word: "the Friday thing", "tomorrow's task"
    if not found:
        d = relative_day(q, today)
        if d and re.search(r"\b(thing|task|item|one|work|it)\b", q.lower()):
            mine = [t for t in tasks.values() if t.get("due") == d.isoformat() and t.get("owner") == person
                    and t.get("status") != "cancelled"]
            found = mine or [t for t in tasks.values() if t.get("due") == d.isoformat()
                             and (not client_ids or t["client"] in client_ids)]
    if len(found) == 1:
        t = dict(found[0])
        for f in corrections_from_feedback(st, people, clients, recs, person):
            if set(content_words(t["title"])) <= set(f["topic"]):
                t["owner"], t["owner_src"] = f["value"], None   # the person's correction wins
        for f in date_corrections(st, people, person):
            if set(content_words(t["title"])) <= set(f["topic"]):
                t["due"], t["due_src"] = f["value"], None
        res = task_answer(t, intent, people)
        res["matched"] = matched + res["matched"]
        return out(res)
    if len(found) > 1:
        opts = [{"id": t["id"], "text": t["title"]} for t in sorted(found, key=lambda t: t["id"])]
        return out(clarify("Which one: " + " or ".join(o["text"] for o in opts) + "?", opts, matched))

    # D. who owns a topic (e.g. billing), or the date of something (e.g. launch)
    topic = [w for w in content_words(q) if not any(w == ph.lower() or w in ph.lower().split() for ph, _ in cl_hits)]
    topic = [w for w in topic if w not in {"account", "client", "retail"}]
    cid = client_ids[0] if client_ids else None
    if intent == "owner" and topic:
        fs = facts_for(extract_owner_facts(recs, people, clients) + corrections_from_feedback(st, people, clients, recs, person),
                       topic, cid)
        best = best_fact(fs)
        if best:
            srcs = [f["src"] for f in fs if f["value"] == best["value"] and f["src"]]
            matched.append({"phrase": person_name(best["value"], people).split()[0], "id": best["value"], "sources": srcs})
            where = f" for {clients[best['client']]['name']}" if best.get("client") in clients else ""
            return out(answer(f"{person_name(best['value'], people)} owns {' '.join(best['topic'])}{where}.",
                              srcs, matched))
    if intent == "due" and topic:
        fs = facts_for(extract_date_facts(recs, clients) + date_corrections(st, people, person), topic, cid)
        if fs:
            best = max(fs, key=lambda f: f["at"])
            srcs = [f["src"] for f in fs if f["value"] == best["value"] and f["src"]]
            what = " ".join(w for w in best["topic"] if w != "date")
            return out(answer(f"The {what} is on {nice(date.fromisoformat(best['value']))}.",
                              srcs, matched))

    # D2. a task named by part of its title ("the invoice"): answer if one, ask back if several
    if topic and intent in ("owner", "due", "status", "done"):
        part = [t for t in tasks.values() if set(topic) <= set(words(t["title"]))
                and (not client_ids or t["client"] in client_ids) and t.get("status") != "cancelled"]
        if len(part) == 1:
            res = task_answer(part[0], intent, people)
            res["matched"] = matched + res["matched"]
            return out(res)
        if 1 < len(part) <= 4:
            opts = [{"id": t["id"], "text": t["title"]} for t in sorted(part, key=lambda t: t["id"])]
            return out(clarify("Which one: " + " or ".join(o["text"] for o in opts) + "?", opts, matched))

    # E. free-text search, privacy-aware
    return out(free_text(person, q, st, people, recs, clients, matched))

def list_answer(intent, person, at, recs, people, clients, tasks, client_ids, matched):
    """Short lists in plain English, each item with its source."""
    lines, srcs = [], []
    if intent == "changes":
        since = (parse_utc(at) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
        for cid in (client_ids or list(clients)):
            for c in sorted(build_changes(cid, since, recs, people, clients, tasks), key=lambda c: c["prio"]):
                if len(lines) < 8:
                    lines.append(c["text"]); srcs += c["sources"]
        head = "In the last 7 days: "
    elif intent == "blocked":
        for t in tasks.values():
            if t.get("status") == "blocked" and (not client_ids or t["client"] in client_ids):
                lines.append(f"{t['title']} (owner {person_name(t['owner'], people)})"); srcs.append(t["status_src"])
        head = "Blocked right now: "
    elif intent == "my_tasks":
        for t in sorted(tasks.values(), key=lambda t: t.get("due") or ""):
            if t.get("owner") == person and t.get("status") not in ("done", "cancelled"):
                d = iso_to_date(t.get("due") or "")
                state = {"todo": "not started", "in_progress": "in progress"}.get(t["status"], t["status"])
                lines.append(f"{t['title']} (due {nice(d) if d else '?'}, {state})")
                srcs.append(t["owner_src"])
        head = "Your open tasks: "
    else:
        promises, _ = extract_promises(recs, people, clients)
        for p in promises:
            if p["owner"] == person and not p["delivered"]:
                lines.append(f"{p['what']} (due {nice(date.fromisoformat(p['due']))})"); srcs.append(p["src"])
        head = "Your open promises: "
    if not lines:
        return answer("I have nothing on that.", [], matched)
    return answer(head + "; ".join(lines[:8]) + ".", srcs, matched)
SAY_PAT = re.compile(r"\bwhat (?:did|does|has|have) (\w+) (?:say|said|write|wrote|tell|told|mention|mentioned|think|thinks|"
                     r"feel|note|noted)\b(?:\s+(?:about|of|on|regarding)\s+(.+))?", re.I)
OPINION_PAT = re.compile(r"\b(my|\w+'s) (?:opinion|thoughts?|views?|notes?|feelings?) (?:on|about|of|regarding) (.+)", re.I)

def said_about(person, q, st, people, recs, clients, matched, at="9999"):
    """'What did I say about Rohan?' / 'What did Meera say about me?' -> quote the speaker's own words.
    Your own private notes are yours to see. Someone else's private notes are refused."""
    m = SAY_PAT.search(q)
    if m:
        who_word, subject = m[1].lower(), m[2] or ""
    else:
        m = OPINION_PAT.search(q)
        if not m:
            return None
        who_word, subject = m[1].lower().replace("'s", ""), m[2]
    me = people.get(person, {})
    if who_word in ("i", "my", "me"):
        speaker = person
    else:
        ids, _ = resolve_name(who_word, person, recs, people)
        if len(ids) != 1:
            return None
        speaker = ids[0]
    subj = set(content_words(subject)) - {"say", "said"}
    if re.search(r"\b(me|myself)\b", subject, re.I) and me:
        subj.add(me["first"])
    if not subj:
        return None
    matched.append({"phrase": who_word, "id": speaker, "sources": []})

    def hits(r):
        return len(subj & set(words(r.get("body"))))
    theirs = [r for r in st["records"] if r.get("author") == speaker and r.get("org") == me.get("org")
              and r.get("at", "") <= at
              and r.get("type") not in ("task", "event", "notification") and hits(r)
              and not is_forgotten(r, st["forgets"])]
    seen = [r for r in theirs if can_see(person, r, people)]
    if seen:
        name = "You" if speaker == person else person_name(speaker, people)
        quotes, ids = [], []
        for r in sorted(seen, key=lambda r: (hits(r), r["at"]), reverse=True)[:3]:   # up to 3, best first
            sent = " ".join(x for x in sentences(r["body"]) if subj & set(words(x))) or r["body"]
            private = " (your private note)" if r.get("visibility") == "private" and speaker == person else ""
            quotes.append(f'on {short_date(parse_utc(r["at"]).date())}{private}: "{sent}"')
            ids.append(r["id"])
        return answer(f"{name} wrote " + "; and ".join(quotes), ids, matched)
    if theirs:                                        # it exists, but not for this person's eyes
        return {"answer": None, "matched": matched, "clarify": None,
                "refused": {"reason": "private"}, "usage": usage()}
    return answer("I have nothing on that.", [], matched)

def name_mention(person, q, people, recs, clients, client_ids, matched):
    """'Send the NB deck to Arjun' -> which Arjun is meant, and which deck."""
    org = people.get(person, {}).get("org")
    firsts = {}
    for p in people.values():
        if p["org"] == org:
            firsts.setdefault(p["first"], []).append(p["id"])
    qwords = words(q)
    name = next((w for w in qwords if len(firsts.get(w, [])) > 1), None)   # only names two people share
    if not name:
        return None
    ids, ev = resolve_name(name, person, recs, people, content_words(q))
    if len(ids) != 1:
        return clarify(f"Which {name.capitalize()} do you mean?",
                       [{"id": i, "text": person_name(i, people)} for i in ids], matched)
    p = people[ids[0]]
    src = (ev or {}).get(ids[0], [])[:3]
    matched.append({"phrase": name.capitalize(), "id": p["id"], "sources": src})
    text = f"{name.capitalize()} here means {p['name']} ({p.get('role', '')})."
    # the thing they want to send: newest record about that client that names it ("deck")
    thing = next((w for w in qwords if w in ("deck", "doc", "document", "report", "sheet", "plan", "file", "invoice")), None)
    if thing:
        cand = [r for r in recs if not is_noise(r, clients) and r.get("type") not in ("task", "event")
                and (not client_ids or record_client(r, clients) in client_ids)
                and thing in words((r.get("title") or "") + " " + (r.get("subject") or "") + " " + r.get("body", ""))]
        if cand:
            r = max(cand, key=lambda r: (person in involved(r), r["at"]))
            line = next((x for x in sentences(r["body"]) if thing in words(x)), r.get("title") or r["body"])
            text += f' The {thing} is most likely this one from {person_name(r.get("author"), people)} on ' \
                    f'{short_date(parse_utc(r["at"]).date())}: "{line}"'
            src = src + [r["id"]]
    return answer(text, src, matched)
def clarify(question, options, matched):
    return {"answer": None, "matched": matched, "clarify": {"question": question, "options": options},
            "refused": None, "usage": usage()}

def free_text(person, q, st, people, recs, clients, matched):
    """Search sentences. If only records the asker may NOT see match, refuse (and quote nothing)."""
    me = people.get(person, {})
    qw = set(content_words(q)) - {"say", "said", "says", "anything", "anywhere", "month", "week", "today"}
    authors = {p["id"] for p in people.values() if p["org"] == me.get("org") and p["first"] in qw}
    if re.search(r"\babout me\b|\bme\b", q.lower()) and me:
        qw.add(me["first"])
    if re.search(r"\b(my|i|me)\b", q.lower()):
        authors_my = {person}
    else:
        authors_my = set()
    def score(r):
        bw = set(words(r.get("body")))
        s = len(qw & bw)
        if r.get("author") in authors and s:
            s += 1
        if r.get("author") in authors_my and s:
            s += 0.5
        return s

    need = 2 if len(qw) + len(authors) >= 2 else 1
    pool = [r for r in recs if not is_noise(r, clients) and r.get("type") not in ("event", "task")]
    best = max(pool, key=score, default=None)
    if best and score(best) >= need:
        sent = max(sentences(best["body"]), key=lambda s: len(qw & set(words(s))))
        who = "You" if best.get("author") == person else \
            (person_name(best.get("author"), people) if best.get("author") in people else "A record")
        when = short_date(parse_utc(best["at"]).date())
        return answer(f'{who} wrote on {when}: "{sent}"', [best["id"]], matched)
    # Would a hidden record have answered? Then say it is private - and quote nothing.
    hidden = [r for r in st["records"] if r.get("org") == me.get("org") and not can_see(person, r, people)
              and not is_noise(r, {}) and not is_forgotten(r, st["forgets"])]
    if any(score(r) >= need for r in hidden):
        return {"answer": None, "matched": matched, "clarify": None,
                "refused": {"reason": "private"}, "usage": usage()}
    return answer("I have nothing on that.", [], matched)

# ---------------------------------------------------------------- audit (bonus)
def cmd_audit(person):
    """Everything we remember from or about this person - only what they may see."""
    st, people = load_store(), load_people()
    recs = visible_records(person, st, people)
    clients = load_clients(recs)
    prefs = prefs_for(person, st)
    tasks = [t for t in task_states(recs).values() if t.get("owner") == person]
    promises, _ = extract_promises(recs, people, clients)
    out({"person": person, "name": person_name(person, people),
         "preferences": [{"words": n, "why": "you told us in feedback"} for n in prefs["notes"]],
         "max_changes": prefs["max_changes"],
         "ignored_topics": [" ".join(t) for t in prefs["skip_words"]],
         "corrections_you_gave": [fb["words"] for fb in st["feedback"]
                                  if fb.get("person") == person and fb.get("type") == "correction"],
         "forget_requests": [f["what"] for f in st["forgets"] if f["person"] == person],
         "tasks_you_own": [{"id": t["id"], "title": t["title"], "status": t["status"], "due": t["due"],
                            "sources": [t["owner_src"]]} for t in tasks],
         "your_promises": [{"what": p["what"], "due": p["due"], "open": not p["delivered"], "sources": [p["src"]]}
                           for p in promises if p["owner"] == person],
         "your_private_notes_kept": [r["id"] for r in recs if r.get("author") == person
                                     and r.get("visibility") == "private"],
         "usage": usage()})

# ---------------------------------------------------------------- chat (for humans)
def print_brief(briefs, day):
    if not briefs:
        print(f"You have no meetings on {day}."); return
    for b in briefs:
        print(f"Meeting {b['meeting_id']}:")
        if b["status"] == "nothing_new":
            print("  Nothing new since your last meeting."); continue
        print("  Whwhoat changed:")
        for c in b["changed"]:
            print(f"   - {c['text']}  [{', '.join(c['sources'])}]")
        if b["promises"]:
            print("  Open promises:")
            for p in b["promises"]:
                who = person_name(p["owner"], load_people())
                print(f"   - {who} will send {p['what']} by {nice(date.fromisoformat(p['due']))}  [{', '.join(p['sources'])}]")
        if b["open_these"]:
            print("  Open these: " + ", ".join(o["record"] for o in b["open_these"]))
        if b["question_to_ask"]:
            print("  Ask: " + b["question_to_ask"]["text"])

def cmd_chat(person, at):
    """Type questions in plain English, get plain-English answers. Not used by the judges."""
    import io, contextlib
    st = load_store()
    at = at or max((r["at"] for r in st["records"]), default="2026-11-02T00:00:00Z")
    print(f"Chatting as {person}, time {at}. Type a question, 'brief 2026-11-05' for meeting notes, or 'exit'.")
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if q.lower() in ("exit", "quit", ""):
            break
        m = re.match(r"(?i)brief\s*(\d{4}-\d{2}-\d{2})?$", q)
        if m:                                  # 'brief 2026-11-05' -> the meeting notes in plain English
            day = m[1] or (parse_utc(at).date() + timedelta(days=1)).isoformat()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_brief(person, day)
            print_brief(json.loads(buf.getvalue()), day)
            continue
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_ask(person, at, q)           # same brain as the real 'ask'
        res = json.loads(buf.getvalue())
        if res.get("answer"):
            print(res["answer"]["text"], " [sources:", ", ".join(res["answer"]["sources"]) or "none", "]")
        elif res.get("clarify"):
            print(res["clarify"]["question"])
        elif res.get("refused"):
            print("Sorry, I can't share that (" + res["refused"]["reason"] + ").")
        else:
            print("I have nothing on that.")

# =====================================================================
# 6. Command line
# =====================================================================
def main():
    p = argparse.ArgumentParser(prog="assist")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest"); s.add_argument("--day", type=int, required=True)
    s = sub.add_parser("brief");  s.add_argument("--person", required=True); s.add_argument("--date", required=True)
    s = sub.add_parser("ask");    s.add_argument("--person", required=True); s.add_argument("--at", required=True)
    s.add_argument("--ask", required=True)
    s = sub.add_parser("forget"); s.add_argument("--person", required=True); s.add_argument("--what", required=True)
    s = sub.add_parser("audit");  s.add_argument("--person", required=True)
    s = sub.add_parser("chat");   s.add_argument("--person", required=True); s.add_argument("--at", default=None)
    a = p.parse_args()
    try:
        if a.cmd == "ingest": cmd_ingest(a.day)
        if a.cmd == "brief":  cmd_brief(a.person, a.date)
        if a.cmd == "ask":    cmd_ask(a.person, a.at, a.ask)
        if a.cmd == "forget": cmd_forget(a.person, a.what)
        if a.cmd == "audit":  cmd_audit(a.person)
        if a.cmd == "chat":   cmd_chat(a.person, a.at)
    except Exception as e:                       # never crash the harness; say we know nothing
        print(f"error: {e!r}", file=sys.stderr)
        if a.cmd == "brief":
            out([])
        elif a.cmd == "ask":
            out({"answer": None, "matched": [], "clarify": None, "refused": None, "usage": usage()})
        else:
            out({"ok": False})

if __name__ == "__main__":
    main()