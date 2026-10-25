import sqlite3, json, datetime as dt
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "lockin.db"

CATS = ["Didn't know it", "Knew it, didn't recognise the question", "Silly mistake"]


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS mistakes(
          id INTEGER PRIMARY KEY, created TEXT, subject TEXT, topic TEXT, question TEXT,
          my_answer TEXT, correct_answer TEXT, reason TEXT, category TEXT, paper_ref TEXT,
          source TEXT DEFAULT 'manual', retries INTEGER DEFAULT 0, last_retry TEXT,
          resolved INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS notes(
          id INTEGER PRIMARY KEY, created TEXT, subject TEXT, topic TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS scans(
          id INTEGER PRIMARY KEY, created TEXT, subject TEXT, topic TEXT, label TEXT,
          mime TEXT, data BLOB);
        CREATE TABLE IF NOT EXISTS topic_tests(
          id INTEGER PRIMARY KEY, created TEXT, subject TEXT, topic TEXT, score_pct REAL);
        CREATE TABLE IF NOT EXISTS sprints(
          id INTEGER PRIMARY KEY, created TEXT, subject TEXT, paper TEXT,
          minutes INTEGER, score_pct REAL);
        CREATE TABLE IF NOT EXISTS cards(
          id INTEGER PRIMARY KEY, created TEXT, subject TEXT, topic TEXT, front TEXT, back TEXT,
          source TEXT, source_id INTEGER, ease REAL DEFAULT 2.5, interval INTEGER DEFAULT 0,
          due TEXT, reps INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS reviews(
          id INTEGER PRIMARY KEY, created TEXT, card_id INTEGER, ok INTEGER);
        CREATE TABLE IF NOT EXISTS study_log(
          id INTEGER PRIMARY KEY, day TEXT, subject TEXT, minutes INTEGER);
        CREATE TABLE IF NOT EXISTS checkins(
          id INTEGER PRIMARY KEY, week_start TEXT UNIQUE, hours REAL, energy INTEGER,
          wins TEXT, struggles TEXT, goals TEXT, ai_plan TEXT);
        CREATE TABLE IF NOT EXISTS topic_stats(
          subject TEXT, topic TEXT, attempts INTEGER DEFAULT 0, correct INTEGER DEFAULT 0,
          last_seen TEXT, PRIMARY KEY(subject, topic));
        CREATE TABLE IF NOT EXISTS exams(
          id INTEGER PRIMARY KEY, created TEXT, week_start TEXT, data TEXT,
          score REAL, taken INTEGER DEFAULT 0);
        """)


def today(): return dt.date.today().isoformat()
def now(): return dt.datetime.now().isoformat(timespec="seconds")
def _norm(s): return (s or "General").strip().title() or "General"


def week_start(d=None):
    d = d or dt.date.today()
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def rows(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def run(sql, args=()):
    with conn() as c:
        return c.execute(sql, args).lastrowid


def subjects():
    q = " UNION ".join(f"SELECT subject FROM {t}" for t in
                       ["mistakes", "notes", "cards", "study_log", "sprints", "topic_tests", "scans"])
    return sorted({r["subject"] for r in rows(q) if r["subject"]})


def add_mistake(subject, topic, question, my_answer="", correct_answer="", reason="",
                category=CATS[0], paper_ref="", source="manual"):
    run("INSERT INTO mistakes(created,subject,topic,question,my_answer,correct_answer,reason,category,paper_ref,source)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (now(), _norm(subject), _norm(topic), question, my_answer, correct_answer, reason,
         category, paper_ref, source))
    record_result(subject, topic, False)


def record_result(subject, topic, ok: bool):
    s, t = _norm(subject), _norm(topic)
    run("INSERT OR IGNORE INTO topic_stats(subject,topic) VALUES(?,?)", (s, t))
    run("UPDATE topic_stats SET attempts=attempts+1, correct=correct+?, last_seen=? WHERE subject=? AND topic=?",
        (1 if ok else 0, today(), s, t))


def days_ago(n): return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def mistakes_since(days=7):
    return rows("SELECT * FROM mistakes WHERE substr(created,1,10)>=? ORDER BY created DESC", (days_ago(days),))


def retry_queue(scope, subject=None):
    base = "SELECT * FROM mistakes WHERE resolved=0 "
    if scope == "week":
        return rows(base + "AND substr(created,1,10)>=? ORDER BY COALESCE(last_retry,'') ", (days_ago(7),))
    if scope == "month":
        return rows(base + "AND substr(created,1,10)>=? ORDER BY COALESCE(last_retry,'') ", (days_ago(30),))
    return rows(base + "AND subject=? ORDER BY COALESCE(last_retry,'') ", (_norm(subject),))


def mark_retry(mid, passed):
    if passed:
        run("UPDATE mistakes SET retries=retries+1, last_retry=?, resolved=CASE WHEN retries+1>=2 THEN 1 ELSE 0 END WHERE id=?",
            (today(), mid))
    else:
        run("UPDATE mistakes SET last_retry=? WHERE id=?", (today(), mid))


def weak_topics(limit=8, subject=None):
    m = rows("SELECT subject,topic,COUNT(*) n FROM mistakes WHERE substr(created,1,10)>=? "
             + ("AND subject=? " if subject else "") + "AND resolved=0 GROUP BY subject,topic",
             (days_ago(30),) + ((_norm(subject),) if subject else ()))
    stats = {(r["subject"], r["topic"]): r for r in rows("SELECT * FROM topic_stats")}
    out = []
    for r in m:
        st = stats.get((r["subject"], r["topic"]))
        acc = (st["correct"] / st["attempts"]) if st and st["attempts"] else 0.0
        w = round(r["n"] * 2 + (1 - acc) * 5, 1)
        out.append({"subject": r["subject"], "topic": r["topic"], "open_mistakes": r["n"],
                    "accuracy_%": round(acc * 100), "weakness": w,
                    "level": "🔴" if w >= 8 else "🟠" if w >= 4 else "🟢"})
    return sorted(out, key=lambda x: -x["weakness"])[:limit]


def add_card(subject, topic, front, back, source="manual", source_id=None):
    return run("INSERT INTO cards(created,subject,topic,front,back,source,source_id,due) VALUES(?,?,?,?,?,?,?,?)",
               (now(), _norm(subject), _norm(topic), front, back, source, source_id, today()))


def due_cards(): return rows("SELECT * FROM cards WHERE due<=? ORDER BY due,id", (today(),))


def review_card(card, grade):
    ease, iv, reps, lapses = card["ease"], card["interval"], card["reps"], card["lapses"]
    if grade == 0:
        reps, lapses, iv, ease = 0, lapses + 1, 0, max(1.3, ease - 0.2)
    else:
        if grade == 1:
            iv, ease = max(1, round(iv * 1.2)), max(1.3, ease - 0.15)
        elif grade == 2:
            iv = 1 if reps == 0 else 3 if reps == 1 else round(iv * ease)
        else:
            iv, ease = max(4, round(max(iv, 1) * ease * 1.3)), ease + 0.15
        reps += 1
    due = (dt.date.today() + dt.timedelta(days=iv)).isoformat()
    run("UPDATE cards SET ease=?,interval=?,reps=?,lapses=?,due=? WHERE id=?", (ease, iv, reps, lapses, due, card["id"]))
    run("INSERT INTO reviews(created,card_id,ok) VALUES(?,?,?)", (now(), card["id"], 0 if grade == 0 else 1))
    if card.get("subject"):
        record_result(card["subject"], card["topic"], grade != 0)


def log_study(subject, minutes, day=None):
    run("INSERT INTO study_log(day,subject,minutes) VALUES(?,?,?)", (day or today(), _norm(subject), int(minutes)))


def heat_minutes():
    logged = {r["day"]: r["m"] for r in rows("SELECT day, SUM(minutes) m FROM study_log GROUP BY day")}
    other = rows("""SELECT d FROM (
        SELECT substr(created,1,10) d FROM reviews UNION SELECT substr(created,1,10) FROM mistakes
        UNION SELECT substr(created,1,10) FROM notes UNION SELECT substr(created,1,10) FROM sprints)""")
    for r in other:
        logged.setdefault(r["d"], 10)
    return logged


def streak():
    active = set(heat_minutes())
    d = dt.date.today()
    if d.isoformat() not in active:
        d -= dt.timedelta(days=1)
    n = 0
    while d.isoformat() in active:
        n += 1
        d -= dt.timedelta(days=1)
    return n


def week_stats(ws):
    end = (dt.date.fromisoformat(ws) + dt.timedelta(days=7)).isoformat()
    a = (ws, end)
    mins = rows("SELECT COALESCE(SUM(minutes),0) m FROM study_log WHERE day>=? AND day<?", a)[0]["m"]
    days = rows("SELECT COUNT(DISTINCT day) n FROM study_log WHERE day>=? AND day<?", a)[0]["n"]
    rv = rows("SELECT COUNT(*) n, COALESCE(SUM(ok),0) ok FROM reviews WHERE substr(created,1,10)>=? AND substr(created,1,10)<?", a)[0]
    sp = rows("SELECT subject,paper,score_pct,minutes FROM sprints WHERE substr(created,1,10)>=? AND substr(created,1,10)<?", a)
    cats = rows("SELECT category,COUNT(*) n FROM mistakes WHERE substr(created,1,10)>=? AND substr(created,1,10)<? GROUP BY category", a)
    ex = rows("SELECT score FROM exams WHERE taken=1 AND substr(created,1,10)>=? AND substr(created,1,10)<?", a)
    return {"study_minutes": mins, "days_studied": days, "cards_reviewed": rv["n"],
            "card_accuracy_%": round(rv["ok"] / rv["n"] * 100) if rv["n"] else None,
            "sprints": sp, "mistake_categories": {c["category"]: c["n"] for c in cats},
            "exam_scores": [e["score"] for e in ex]}


def save_exam(week, data): return run("INSERT INTO exams(created,week_start,data) VALUES(?,?,?)", (now(), week, json.dumps(data)))
def finish_exam(eid, score): run("UPDATE exams SET score=?, taken=1 WHERE id=?", (score, eid))
