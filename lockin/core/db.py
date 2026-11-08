import os
import sqlite3
import threading
import datetime as dt
from pathlib import Path
import streamlit as st
from core import config

SQLITE_PATH = Path(os.getenv("LOCKIN_DB") or Path(__file__).resolve().parent.parent / "lockin.db")
CATS = ["Didn't know it", "Knew it, didn't recognise the question", "Silly mistake"]
DATA_TABLES = ["mistakes", "notes", "scans", "topic_tests", "sprints", "cards", "reviews",
               "study_log", "checkins", "topic_stats", "exams", "events", "plans"]
SUBJECT_TABLES = ["mistakes", "notes", "cards", "study_log", "sprints", "topic_tests", "scans"]

_pool = None
_lock = threading.Lock()
_ready = False
_writes = 0

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id {pk}, username TEXT UNIQUE NOT NULL, display_name TEXT, pw_hash TEXT,
  role TEXT DEFAULT 'user', active INTEGER DEFAULT 1, must_change INTEGER DEFAULT 0, created TEXT,
  last_login TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS requests(id {pk}, created TEXT, name TEXT, contact TEXT, message TEXT,
  status TEXT DEFAULT 'pending', handled TEXT);
CREATE TABLE IF NOT EXISTS events(id {pk}, user_id INTEGER, created TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS login_log(id {pk}, created TEXT, username TEXT, role TEXT, ok INTEGER);
CREATE TABLE IF NOT EXISTS mistakes(id {pk}, user_id INTEGER, created TEXT, subject TEXT, topic TEXT,
  question TEXT, my_answer TEXT, correct_answer TEXT, reason TEXT, category TEXT, paper_ref TEXT,
  source TEXT DEFAULT 'manual', retries INTEGER DEFAULT 0, last_retry TEXT, resolved INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS notes(id {pk}, user_id INTEGER, created TEXT, subject TEXT, topic TEXT, body TEXT);
CREATE TABLE IF NOT EXISTS scans(id {pk}, user_id INTEGER, created TEXT, subject TEXT, topic TEXT,
  label TEXT, mime TEXT, data {blob});
CREATE TABLE IF NOT EXISTS topic_tests(id {pk}, user_id INTEGER, created TEXT, subject TEXT, topic TEXT,
  score_pct DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS sprints(id {pk}, user_id INTEGER, created TEXT, subject TEXT, paper TEXT,
  minutes INTEGER, score_pct DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS cards(id {pk}, user_id INTEGER, created TEXT, subject TEXT, topic TEXT,
  front TEXT, back TEXT, source TEXT, source_id INTEGER, ease DOUBLE PRECISION DEFAULT 2.5,
  ivl INTEGER DEFAULT 0, due TEXT, reps INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS reviews(id {pk}, user_id INTEGER, created TEXT, card_id INTEGER, ok INTEGER);
CREATE TABLE IF NOT EXISTS study_log(id {pk}, user_id INTEGER, day TEXT, subject TEXT, minutes INTEGER);
CREATE TABLE IF NOT EXISTS checkins(id {pk}, user_id INTEGER, week_start TEXT, hours DOUBLE PRECISION,
  energy INTEGER, wins TEXT, struggles TEXT, goals TEXT, ai_plan TEXT, UNIQUE(user_id, week_start));
CREATE TABLE IF NOT EXISTS topic_stats(user_id INTEGER, subject TEXT, topic TEXT, attempts INTEGER DEFAULT 0,
  correct INTEGER DEFAULT 0, last_seen TEXT, PRIMARY KEY(user_id, subject, topic));
CREATE TABLE IF NOT EXISTS exams(id {pk}, user_id INTEGER, created TEXT, week_start TEXT, data TEXT,
  score DOUBLE PRECISION, taken INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS plans(id {pk}, user_id INTEGER, created TEXT, exam TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS ix_events_user ON events(user_id, created);
CREATE INDEX IF NOT EXISTS ix_mistakes_user ON mistakes(user_id, created);
CREATE INDEX IF NOT EXISTS ix_cards_user ON cards(user_id, due);
CREATE INDEX IF NOT EXISTS ix_reviews_user ON reviews(user_id, created);
CREATE INDEX IF NOT EXISTS ix_login_user ON login_log(username, created)
"""


def database_url():
    return config.secret("DATABASE_URL")


def backend():
    return "postgres" if database_url() else "sqlite"


def _get_pool():
    global _pool
    with _lock:
        if _pool is None:
            from psycopg2.pool import ThreadedConnectionPool
            _pool = ThreadedConnectionPool(1, 6, database_url(), connect_timeout=10)
        return _pool


def _clean(r):
    return {k: (bytes(v) if isinstance(v, memoryview) else v) for k, v in dict(r).items()}


def _exec(sql, args=()):
    if backend() == "postgres":
        import psycopg2
        from psycopg2.extras import RealDictCursor
        sql = sql.replace("?", "%s")
        args = tuple(psycopg2.Binary(a) if isinstance(a, (bytes, bytearray)) else a for a in args)
        for attempt in (0, 1):
            pool = _get_pool()
            conn = pool.getconn()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, args)
                    out = [_clean(r) for r in cur.fetchall()] if cur.description else []
                conn.commit()
                pool.putconn(conn)
                return out
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                pool.putconn(conn, close=True)
                if attempt:
                    raise
            except Exception:
                conn.rollback()
                pool.putconn(conn)
                raise
    c = sqlite3.connect(SQLITE_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        cur = c.execute(sql, args)
        out = [_clean(r) for r in cur.fetchall()] if cur.description else []
        c.commit()
        return out
    finally:
        c.close()


def rows(sql, args=()):
    return _exec(sql, tuple(args))


def _bump():
    global _writes
    _writes += 1


def run(sql, args=()):
    _exec(sql, tuple(args))
    _bump()


def insert(sql, args=()):
    out = _exec(sql + " RETURNING id", tuple(args))
    _bump()
    return out[0]["id"] if out else None


def init():
    global _ready
    if _ready:
        return
    pg = backend() == "postgres"
    ddl = SCHEMA.format(pk="SERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT",
                        blob="BYTEA" if pg else "BLOB")
    for stmt in ddl.split(";"):
        if stmt.strip():
            _exec(stmt)
    _ready = True


def reset_ready():
    global _ready
    _ready = False


def uid():
    return st.session_state["user"]["id"]


def _u(u):
    return uid() if u is None else u


def today():
    return dt.date.today().isoformat()


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def days_ago(n):
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def _norm(s):
    return (s or "General").strip().title() or "General"


def week_start(d=None):
    d = d or dt.date.today()
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def log_event(kind, detail="", u=None):
    try:
        run("INSERT INTO events(user_id,created,kind,detail) VALUES(?,?,?,?)", (_u(u), now(), kind, str(detail)[:200]))
    except Exception:
        pass


@st.cache_data(ttl=300, show_spinner=False, max_entries=500)
def _c_subjects(u, w):
    q = " UNION ".join(f"SELECT subject FROM {t} WHERE user_id=?" for t in SUBJECT_TABLES)
    return sorted({r["subject"] for r in rows(q, (u,) * len(SUBJECT_TABLES)) if r["subject"]})


def subjects(u=None):
    return _c_subjects(_u(u), _writes)


def record_result(subject, topic, ok, u=None):
    u, s, t = _u(u), _norm(subject), _norm(topic)
    run("INSERT INTO topic_stats(user_id,subject,topic) VALUES(?,?,?) ON CONFLICT DO NOTHING", (u, s, t))
    run("UPDATE topic_stats SET attempts=attempts+1, correct=correct+?, last_seen=? WHERE user_id=? AND subject=? AND topic=?",
        (1 if ok else 0, today(), u, s, t))


def add_mistake(subject, topic, question, my_answer="", correct_answer="", reason="",
                category=CATS[0], paper_ref="", source="manual", u=None):
    u = _u(u)
    run("INSERT INTO mistakes(user_id,created,subject,topic,question,my_answer,correct_answer,reason,category,paper_ref,source)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (u, now(), _norm(subject), _norm(topic), question, my_answer, correct_answer, reason, category, paper_ref, source))
    record_result(subject, topic, False, u)
    log_event("mistake", f"{_norm(subject)}/{_norm(topic)}", u)


def mistakes_since(days=7, u=None):
    return rows("SELECT * FROM mistakes WHERE user_id=? AND substr(created,1,10)>=? ORDER BY created DESC",
                (_u(u), days_ago(days)))


def retry_queue(scope, subject=None, u=None):
    u = _u(u)
    base = "SELECT * FROM mistakes WHERE user_id=? AND resolved=0 "
    order = " ORDER BY COALESCE(last_retry,''), id"
    if scope == "week":
        return rows(base + "AND substr(created,1,10)>=?" + order, (u, days_ago(7)))
    if scope == "month":
        return rows(base + "AND substr(created,1,10)>=?" + order, (u, days_ago(30)))
    return rows(base + "AND subject=?" + order, (u, _norm(subject)))


def mark_retry(mid, passed, u=None):
    u = _u(u)
    if passed:
        run("UPDATE mistakes SET retries=retries+1, last_retry=?, resolved=CASE WHEN retries+1>=2 THEN 1 ELSE 0 END WHERE id=? AND user_id=?",
            (today(), mid, u))
    else:
        run("UPDATE mistakes SET last_retry=? WHERE id=? AND user_id=?", (today(), mid, u))
    log_event("retry", "pass" if passed else "fail", u)


@st.cache_data(ttl=300, show_spinner=False, max_entries=500)
def _c_weak(u, w, limit, subject):
    args = [u, days_ago(30)]
    q = "SELECT subject,topic,COUNT(*) AS n FROM mistakes WHERE user_id=? AND substr(created,1,10)>=? AND resolved=0 "
    if subject:
        q += "AND subject=? "
        args.append(_norm(subject))
    m = rows(q + "GROUP BY subject,topic", args)
    stats = {(r["subject"], r["topic"]): r for r in rows("SELECT * FROM topic_stats WHERE user_id=?", (u,))}
    out = []
    for r in m:
        st_ = stats.get((r["subject"], r["topic"]))
        acc = (st_["correct"] / st_["attempts"]) if st_ and st_["attempts"] else 0.0
        wk = round(r["n"] * 2 + (1 - acc) * 5, 1)
        out.append({"subject": r["subject"], "topic": r["topic"], "open_mistakes": r["n"],
                    "accuracy_%": round(acc * 100), "weakness": wk,
                    "level": "🔴" if wk >= 8 else "🟠" if wk >= 4 else "🟢"})
    return sorted(out, key=lambda x: -x["weakness"])[:limit]


def weak_topics(limit=8, subject=None, u=None):
    return _c_weak(_u(u), _writes, limit, subject)


def add_card(subject, topic, front, back, source="manual", source_id=None, u=None):
    return insert("INSERT INTO cards(user_id,created,subject,topic,front,back,source,source_id,due) VALUES(?,?,?,?,?,?,?,?,?)",
                  (_u(u), now(), _norm(subject), _norm(topic), front, back, source, source_id, today()))


def due_cards(u=None):
    return rows("SELECT * FROM cards WHERE user_id=? AND due<=? ORDER BY due,id", (_u(u), today()))


def review_card(card, grade, u=None):
    u = _u(u)
    ease, iv, reps, lapses = card["ease"], card["ivl"], card["reps"], card["lapses"]
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
    run("UPDATE cards SET ease=?,ivl=?,reps=?,lapses=?,due=? WHERE id=? AND user_id=?",
        (ease, iv, reps, lapses, due, card["id"], u))
    run("INSERT INTO reviews(user_id,created,card_id,ok) VALUES(?,?,?,?)", (u, now(), card["id"], 0 if grade == 0 else 1))
    record_result(card["subject"], card["topic"], grade != 0, u)
    log_event("card", card["subject"], u)


def log_study(subject, minutes, day=None, u=None):
    u = _u(u)
    run("INSERT INTO study_log(user_id,day,subject,minutes) VALUES(?,?,?,?)", (u, day or today(), _norm(subject), int(minutes)))
    log_event("study", f"{_norm(subject)} {int(minutes)}m", u)


def add_note(subject, topic, body, u=None):
    u = _u(u)
    run("INSERT INTO notes(user_id,created,subject,topic,body) VALUES(?,?,?,?,?)", (u, now(), _norm(subject), _norm(topic), body))
    log_event("note", _norm(subject), u)


def add_scan(subject, topic, label, mime, data, u=None):
    u = _u(u)
    run("INSERT INTO scans(user_id,created,subject,topic,label,mime,data) VALUES(?,?,?,?,?,?,?)",
        (u, now(), _norm(subject), _norm(topic) if topic else "", label, mime, data))
    log_event("scan", _norm(subject), u)


def add_topic_test(subject, topic, score, u=None):
    u = _u(u)
    run("INSERT INTO topic_tests(user_id,created,subject,topic,score_pct) VALUES(?,?,?,?,?)",
        (u, now(), _norm(subject), _norm(topic), float(score)))
    log_event("topic_test", _norm(subject), u)


def add_sprint(subject, paper, minutes, score, u=None):
    u = _u(u)
    run("INSERT INTO sprints(user_id,created,subject,paper,minutes,score_pct) VALUES(?,?,?,?,?,?)",
        (u, now(), _norm(subject), paper, int(minutes), float(score)))
    log_event("sprint", _norm(subject), u)


def save_checkin(ws, hours, energy, wins, struggles, goals, plan, u=None):
    u = _u(u)
    run("INSERT INTO checkins(user_id,week_start,hours,energy,wins,struggles,goals,ai_plan) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(user_id,week_start) DO UPDATE SET hours=excluded.hours, energy=excluded.energy, wins=excluded.wins, "
        "struggles=excluded.struggles, goals=excluded.goals, ai_plan=excluded.ai_plan",
        (u, ws, float(hours), int(energy), wins, struggles, goals, plan))
    log_event("checkin", ws, u)


def save_exam(week, data, u=None):
    import json
    u = _u(u)
    eid = insert("INSERT INTO exams(user_id,created,week_start,data) VALUES(?,?,?,?)", (u, now(), week, json.dumps(data)))
    log_event("exam_generated", week, u)
    return eid


def finish_exam(eid, score, u=None):
    u = _u(u)
    run("UPDATE exams SET score=?, taken=1 WHERE id=? AND user_id=?", (float(score), eid, u))
    log_event("exam_taken", f"{score:.0f}%", u)


@st.cache_data(ttl=300, show_spinner=False, max_entries=500)
def _c_heat(u, w):
    logged = {r["day"]: int(r["m"]) for r in rows("SELECT day, SUM(minutes) AS m FROM study_log WHERE user_id=? GROUP BY day", (u,))}
    for r in rows("SELECT DISTINCT substr(created,1,10) AS d FROM events WHERE user_id=? AND kind<>'login'", (u,)):
        logged.setdefault(r["d"], 10)
    return logged


def heat_minutes(u=None):
    return _c_heat(_u(u), _writes)


@st.cache_data(ttl=300, show_spinner=False, max_entries=500)
def _c_streak(u, w, day):
    active = set(_c_heat(u, w))
    d = dt.date.today()
    if d.isoformat() not in active:
        d -= dt.timedelta(days=1)
    n = 0
    while d.isoformat() in active:
        n += 1
        d -= dt.timedelta(days=1)
    return n


def streak(u=None):
    return _c_streak(_u(u), _writes, today())


@st.cache_data(ttl=300, show_spinner=False, max_entries=500)
def _c_week(u, w, ws):
    end = (dt.date.fromisoformat(ws) + dt.timedelta(days=7)).isoformat()
    a = (u, ws, end)
    mins = int(rows("SELECT COALESCE(SUM(minutes),0) AS m FROM study_log WHERE user_id=? AND day>=? AND day<?", a)[0]["m"])
    days = int(rows("SELECT COUNT(DISTINCT day) AS n FROM study_log WHERE user_id=? AND day>=? AND day<?", a)[0]["n"])
    rv = rows("SELECT COUNT(*) AS n, COALESCE(SUM(ok),0) AS good FROM reviews WHERE user_id=? AND substr(created,1,10)>=? AND substr(created,1,10)<?", a)[0]
    sp = rows("SELECT subject,paper,score_pct,minutes FROM sprints WHERE user_id=? AND substr(created,1,10)>=? AND substr(created,1,10)<?", a)
    cats = rows("SELECT category,COUNT(*) AS n FROM mistakes WHERE user_id=? AND substr(created,1,10)>=? AND substr(created,1,10)<? GROUP BY category", a)
    ex = rows("SELECT score FROM exams WHERE user_id=? AND taken=1 AND substr(created,1,10)>=? AND substr(created,1,10)<?", a)
    n, good = int(rv["n"]), int(rv["good"])
    return {"study_minutes": mins, "days_studied": days, "cards_reviewed": n,
            "card_accuracy_%": round(good / n * 100) if n else None,
            "sprints": sp, "mistake_categories": {c["category"]: c["n"] for c in cats},
            "exam_scores": [e["score"] for e in ex]}


def week_stats(ws, u=None):
    return _c_week(_u(u), _writes, ws)


def save_plan(exam, data, u=None):
    import json
    u = _u(u)
    pid = insert("INSERT INTO plans(user_id,created,exam,data) VALUES(?,?,?,?)", (u, now(), exam, json.dumps(data)))
    log_event("plan", exam, u)
    return pid


@st.cache_data(ttl=300, show_spinner=False, max_entries=200)
def _c_plan(u, w):
    import json
    r = rows("SELECT * FROM plans WHERE user_id=? ORDER BY created DESC LIMIT 1", (u,))
    if not r:
        return None
    try:
        out = json.loads(r[0]["data"])
        out["_exam"], out["_created"] = r[0]["exam"], r[0]["created"]
        return out
    except Exception:
        return None


def latest_plan(u=None):
    return _c_plan(_u(u), _writes)


@st.cache_data(ttl=120, show_spinner=False, max_entries=500)
def _c_events(u, w, day):
    r = rows("SELECT kind, COUNT(*) AS n FROM events WHERE user_id=? AND substr(created,1,10)=? GROUP BY kind", (u, day))
    return {x["kind"]: int(x["n"]) for x in r}


def events_today(u=None):
    return _c_events(_u(u), _writes, today())


@st.cache_data(ttl=120, show_spinner=False, max_entries=500)
def _c_summary(u, w, day):
    r = rows(
        "SELECT "
        "(SELECT COUNT(*) FROM cards WHERE user_id=? AND due<=?) AS due, "
        "(SELECT COUNT(*) FROM cards WHERE user_id=?) AS total_cards, "
        "(SELECT COUNT(*) FROM reviews WHERE user_id=? AND substr(created,1,10)=?) AS reviewed_today, "
        "(SELECT COALESCE(SUM(minutes),0) FROM study_log WHERE user_id=? AND day=?) AS mins_today, "
        "(SELECT COUNT(*) FROM mistakes WHERE user_id=? AND resolved=0 AND substr(created,1,10)>=?) AS retry_week",
        (u, day, u, u, day, u, day, u, days_ago(7)))[0]
    return {k: int(v or 0) for k, v in r.items()}


def summary(u=None):
    return _c_summary(_u(u), _writes, today())


COUNT_TABLES = ["users", "requests", "login_log"] + DATA_TABLES


def table_counts():
    out = {}
    for t in COUNT_TABLES:
        out[t] = int(rows(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"])
    return out


def purge_user_data(user_id, tables):
    done = {}
    for t in tables:
        if t not in DATA_TABLES:
            continue
        n = int(rows(f"SELECT COUNT(*) AS n FROM {t} WHERE user_id=?", (user_id,))[0]["n"])
        run(f"DELETE FROM {t} WHERE user_id=?", (user_id,))
        done[t] = n
    return done


def purge_tables(tables):
    done = {}
    for t in tables:
        if t not in DATA_TABLES + ["login_log", "requests"]:
            continue
        n = int(rows(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"])
        run(f"DELETE FROM {t}")
        done[t] = n
    return done


def purge_older(table, days):
    if table not in ("events", "login_log", "reviews", "scans"):
        return 0
    cutoff = days_ago(days)
    n = int(rows(f"SELECT COUNT(*) AS n FROM {table} WHERE substr(created,1,10)<?", (cutoff,))[0]["n"])
    run(f"DELETE FROM {table} WHERE substr(created,1,10)<?", (cutoff,))
    return n


def wipe_all_students():
    ids = [r["id"] for r in rows("SELECT id FROM users WHERE role='user'")]
    for t in DATA_TABLES:
        run(f"DELETE FROM {t} WHERE user_id IN (SELECT id FROM users WHERE role='user')")
    run("DELETE FROM users WHERE role='user'")
    run("DELETE FROM requests")
    run("DELETE FROM login_log")
    return len(ids)
