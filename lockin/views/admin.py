import io
import re
import zipfile
import pandas as pd
import streamlit as st
from core import auth, config, db, nim, ui, viz

if not auth.is_admin():
    st.error("Admins only.")
    st.stop()

ui.header("Admin Panel", "🛡️")
st.caption("You can see activity statistics for every student. Their notes and answers stay private.")

section = st.radio("Section", ["📊 Overview", "👥 Users", "📨 Requests", "🔍 Activity", "🧑‍🎓 Student drill-down", "🗑 Data", "⚙️ System"], horizontal=True)


def n(sql, args=()):
    r = db.rows(sql, args)
    return int(r[0]["n"] or 0) if r else 0


def students():
    return db.rows("SELECT id,username,display_name,active,must_change,created,last_login,note FROM users WHERE role='user' ORDER BY id")


def show_cred():
    c = st.session_state.get("new_cred")
    if c:
        st.success("Account ready. Copy this now, it is shown only once.")
        st.code(f"Username: {c[0]}\nTemporary password: {c[1]}")
        st.caption("They will be asked to choose their own password at first login.")
        if st.button("Done, hide it"):
            del st.session_state["new_cred"]
            st.rerun()


def leaderboard():
    since = db.days_ago(7)
    users = students()
    if not users:
        return pd.DataFrame()
    cards = {r["user_id"]: r["c"] for r in db.rows("SELECT user_id, COUNT(*) c FROM reviews WHERE substr(created,1,10)>=? GROUP BY user_id", (since,))}
    study = {r["user_id"]: r["m"] for r in db.rows("SELECT user_id, SUM(minutes) m FROM study_log WHERE day>=? GROUP BY user_id", (since,))}
    openm = {r["user_id"]: r["c"] for r in db.rows("SELECT user_id, COUNT(*) c FROM mistakes WHERE resolved=0 GROUP BY user_id")}
    act = {r["user_id"]: r for r in db.rows(
        "SELECT user_id, MAX(created) AS last_seen, COUNT(DISTINCT substr(created,1,10)) AS days FROM events WHERE kind<>'login' AND substr(created,1,10)>=? GROUP BY user_id", (since,))}
    out = []
    for u in users:
        a = act.get(u["id"], {})
        out.append({"student": u["username"], "status": "active" if u["active"] else "disabled",
                    "streak": db.streak(u["id"]), "active days (7d)": int(a.get("days", 0) or 0),
                    "cards (7d)": int(cards.get(u["id"], 0)), "study hrs (7d)": round(int(study.get(u["id"], 0)) / 60, 1),
                    "open mistakes": int(openm.get(u["id"], 0)), "last active": (a.get("last_seen") or "never")[:16],
                    "last login": (u["last_login"] or "never")[:16]})
    return pd.DataFrame(out)


def show(fig, msg="No data yet."):
    if fig:
        st.plotly_chart(fig)
    else:
        st.info(msg)


if section.startswith("📊"):
    today, wk = db.today(), db.days_ago(7)
    k = st.columns(6)
    k[0].metric("Students", n("SELECT COUNT(*) n FROM users WHERE role='user'"))
    k[1].metric("Active today", n("SELECT COUNT(DISTINCT user_id) n FROM events WHERE kind<>'login' AND substr(created,1,10)=?", (today,)))
    k[2].metric("Active 7d", n("SELECT COUNT(DISTINCT user_id) n FROM events WHERE kind<>'login' AND substr(created,1,10)>=?", (wk,)))
    k[3].metric("Cards 7d", n("SELECT COUNT(*) n FROM reviews WHERE substr(created,1,10)>=?", (wk,)))
    k[4].metric("Study hrs 7d", round(n("SELECT COALESCE(SUM(minutes),0) n FROM study_log WHERE day>=?", (wk,)) / 60, 1))
    k[5].metric("Pending requests", n("SELECT COUNT(*) n FROM requests WHERE status='pending'"))

    a, b = st.columns(2)
    with a:
        show(viz.admin_dau())
    with b:
        show(viz.admin_events_kind())
    a, b = st.columns(2)
    with a:
        show(viz.admin_user_activity())
    with b:
        show(viz.admin_study_users())
    a, b = st.columns(2)
    with a:
        show(viz.admin_causes())
    with b:
        show(viz.admin_weak_topics())
    st.subheader("Students at a glance")
    lb = leaderboard()
    if lb.empty:
        st.info("No students yet. Create one in the Users section.")
    else:
        st.dataframe(lb, hide_index=True)

elif section.startswith("👥"):
    st.subheader("Create an account")
    with st.form("create_user"):
        c1, c2 = st.columns(2)
        uname = c1.text_input("Username", help="Letters, numbers, dot, dash, underscore")
        dname = c2.text_input("Display name")
        note = st.text_input("Note (who is this, how to reach them)")
        custom = st.text_input("Custom password (leave blank to auto-generate)", type="password")
        if st.form_submit_button("Create account", type="primary"):
            ok, res = auth.create_user(uname, dname, note, custom or None)
            if ok:
                st.session_state.new_cred = (uname.strip().lower(), res if not custom else "(the password you typed)")
                db.log_event("admin_create_user", uname)
                st.rerun()
            else:
                st.error(res)
    show_cred()

    st.subheader("Manage accounts")
    us = students()
    if us:
        df = pd.DataFrame(us)
        df["active"] = df.active.map(lambda x: "yes" if int(x) else "no")
        st.dataframe(df.drop(columns=["must_change"]), hide_index=True)
        pick = st.selectbox("Select a student", us, format_func=lambda x: f"{x['username']} ({x['display_name']})")
        b1, b2, b3 = st.columns(3)
        if b1.button("🔑 Reset password"):
            st.session_state.new_cred = (pick["username"], auth.reset_password(pick["id"]))
            db.log_event("admin_reset_pw", pick["username"])
            st.rerun()
        if int(pick["active"]):
            if b2.button("⏸ Disable account"):
                auth.set_active(pick["id"], False)
                st.rerun()
        else:
            if b2.button("▶ Enable account"):
                auth.set_active(pick["id"], True)
                st.rerun()
        confirm = b3.checkbox("I understand deleting erases all their data")
        if b3.button("🗑 Delete account", disabled=not confirm):
            auth.delete_user(pick["id"])
            st.rerun()
    else:
        st.info("No students yet.")

elif section.startswith("📨"):
    pend = db.rows("SELECT * FROM requests WHERE status='pending' ORDER BY created")
    st.subheader(f"Pending requests ({len(pend)})")
    show_cred()
    for r in pend:
        with st.container(border=True):
            st.markdown(f"**{r['name']}** · {r['contact']} · {r['created'][:16]}")
            if r["message"]:
                st.write(r["message"])
            sug = re.sub(r"[^a-z0-9._-]", "", r["name"].lower().replace(" ", "."))[:30]
            c1, c2, c3 = st.columns([2, 1, 1])
            uname = c1.text_input("Username", sug, key=f"ru{r['id']}")
            if c2.button("✅ Create account", key=f"rc{r['id']}"):
                ok, res = auth.create_user(uname, r["name"], f"contact: {r['contact']}")
                if ok:
                    db.run("UPDATE requests SET status='approved', handled=? WHERE id=?", (db.now(), r["id"]))
                    st.session_state.new_cred = (uname.strip().lower(), res)
                    db.log_event("admin_create_user", uname)
                    st.rerun()
                else:
                    st.error(res)
            if c3.button("Dismiss", key=f"rd{r['id']}"):
                db.run("UPDATE requests SET status='dismissed', handled=? WHERE id=?", (db.now(), r["id"]))
                st.rerun()
    with st.expander("Handled requests"):
        hist = db.rows("SELECT created,name,contact,status,handled FROM requests WHERE status<>'pending' ORDER BY created DESC")
        if hist:
            st.dataframe(pd.DataFrame(hist), hide_index=True)

elif section.startswith("🔍"):
    a, b = st.columns(2)
    with a:
        show(viz.admin_hour_heat())
    with b:
        show(viz.admin_logins())
    show(viz.admin_signups())
    st.subheader("Recent activity")
    ev = db.rows("SELECT e.created, u.username, e.kind, e.detail FROM events e LEFT JOIN users u ON u.id=e.user_id ORDER BY e.created DESC LIMIT 150")
    if ev:
        st.dataframe(pd.DataFrame(ev), hide_index=True)
    st.subheader("Login log")
    ll = db.rows("SELECT created, username, role, ok FROM login_log ORDER BY created DESC LIMIT 100")
    if ll:
        d = pd.DataFrame(ll)
        d["result"] = d.ok.map(lambda x: "✅" if int(x) else "❌ failed")
        st.dataframe(d.drop(columns=["ok"]), hide_index=True)

elif section.startswith("🧑"):
    us = students()
    if not us:
        st.info("No students yet.")
        st.stop()
    pick = st.selectbox("Student", us, format_func=lambda x: f"{x['username']} ({x['display_name']})")
    uid_ = pick["id"]
    k = st.columns(5)
    k[0].metric("Streak", f"{db.streak(uid_)} days")
    k[1].metric("Open mistakes", n("SELECT COUNT(*) n FROM mistakes WHERE user_id=? AND resolved=0", (uid_,)))
    k[2].metric("Cards in deck", n("SELECT COUNT(*) n FROM cards WHERE user_id=?", (uid_,)))
    k[3].metric("Study hrs (30d)", round(n("SELECT COALESCE(SUM(minutes),0) n FROM study_log WHERE user_id=? AND day>=?", (uid_, db.days_ago(30))) / 60, 1))
    k[4].metric("Last login", (pick["last_login"] or "never")[:16])
    st.subheader("Study heatmap")
    ui.heatmap(db.heat_minutes(uid_))
    a, b = st.columns(2)
    with a:
        show(viz.subject_radar(uid_))
    with b:
        show(viz.mistake_causes(uid_))
    show(viz.topic_treemap(uid_))
    a, b = st.columns(2)
    with a:
        show(viz.study_daily(uid_))
    with b:
        show(viz.retention(uid_))
    a, b = st.columns(2)
    with a:
        show(viz.sprint_trend(uid_))
    with b:
        show(viz.exam_trend(uid_))
    st.subheader("Recent activity")
    ev = db.rows("SELECT created, kind, detail FROM events WHERE user_id=? ORDER BY created DESC LIMIT 60", (uid_,))
    if ev:
        st.dataframe(pd.DataFrame(ev), hide_index=True)

elif section.startswith("🗑"):
    st.warning("Deletions are permanent. Download an export first (System → Export everything).")
    counts = db.table_counts()
    st.dataframe(pd.DataFrame({"table": list(counts), "rows": list(counts.values())}), hide_index=True)

    st.subheader("1. Delete one student's data (keeps their account)")
    us = students()
    if us:
        pick = st.selectbox("Student", us, format_func=lambda x: f"{x['username']} ({x['display_name']})", key="del_user")
        tabs_ = st.multiselect("What to delete", db.DATA_TABLES, default=db.DATA_TABLES, key="del_user_tables")
        ok1 = st.checkbox("I understand this cannot be undone", key="del_user_ok")
        if st.button("Delete the selected data", disabled=not (ok1 and tabs_), key="del_user_btn"):
            res = db.purge_user_data(pick["id"], tabs_)
            gone = ", ".join(f"{t} ({n})" for t, n in res.items() if n)
            st.success(f"Deleted: {gone}" if gone else "Nothing to delete.")
    else:
        st.info("No students yet.")

    st.subheader("2. Delete whole tables for everyone")
    tables_ = st.multiselect("Tables", db.DATA_TABLES + ["login_log", "requests"], key="del_tables")
    typed = st.text_input("Type DELETE to confirm", key="del_confirm")
    if st.button("Delete these tables", disabled=not (tables_ and typed.strip() == "DELETE"), key="del_tables_btn"):
        res = db.purge_tables(tables_)
        st.success("Deleted: " + ", ".join(f"{t} ({n})" for t, n in res.items()))

    st.subheader("3. Clean up old records")
    c1, c2 = st.columns(2)
    tbl = c1.selectbox("Table", ["events", "login_log", "reviews", "scans"], key="old_tbl")
    days_ = c2.number_input("Delete records older than (days)", 1, 3650, 90, key="old_days")
    ok3 = st.checkbox("I understand this cannot be undone", key="old_ok")
    if st.button("Delete old records", disabled=not ok3, key="old_btn"):
        st.success(f"Deleted {db.purge_older(tbl, int(days_))} rows from {tbl}.")

    st.subheader("4. Danger zone: remove all students")
    st.caption("Deletes every student account and all their data, and clears requests and the login log. Your admin account is kept.")
    typed2 = st.text_input("Type WIPE ALL STUDENTS to confirm", key="wipe_confirm")
    if st.button("Wipe all students", disabled=typed2.strip() != "WIPE ALL STUDENTS", key="wipe_btn"):
        st.success(f"Removed {db.wipe_all_students()} student accounts and their data.")

else:
    st.subheader("System status")
    pg = db.backend() == "postgres"
    rows_ = [
        ("Database", "PostgreSQL (permanent)" if pg else "SQLite file (wiped when the server restarts)"),
        ("DATABASE_URL set", "✅" if db.database_url() else "❌"),
        ("MASTER_KEY set", "✅" if auth.master_key() else "❌"),
        ("NVIDIA_API_KEY set", "✅" if config.secret("NVIDIA_API_KEY") else "❌"),
        ("Teacher model", nim.chain("teacher")[0]),
        ("Vision model", nim.chain("vision")[0]),
    ]
    st.table(pd.DataFrame(rows_, columns=["Setting", "Value"]))
    if not pg:
        st.warning("You're on the temporary SQLite database. Add a DATABASE_URL secret (see the README) so accounts and progress are saved permanently.")

    st.subheader("AI models")
    st.table(pd.DataFrame([(r, " → ".join(m.split("/")[-1] for m in nim.chain(r))) for r in ("teacher", "vision", "fast")],
                          columns=["Role", "Tried in this order"]))
    st.caption("Change them with NIM_TEACHER_MODEL, NIM_VISION_MODEL and NIM_FAST_MODEL in the secrets (comma-separated for fallbacks).")
    m1, m2 = st.columns(2)
    if m1.button("🧪 Test the models (about a minute)"):
        out = []
        with st.spinner("Testing..."):
            for role in ("teacher", "vision", "fast"):
                for m in nim.chain(role)[:3]:
                    ok, secs, msg = nim.test_model(m, role)
                    out.append({"role": role, "model": m, "works": "✅" if ok else "❌", "seconds": secs, "reply / error": msg})
        st.session_state.model_test = out
    if st.session_state.get("model_test"):
        st.dataframe(pd.DataFrame(st.session_state.model_test), hide_index=True)
    if m2.button("📋 List models my key can use"):
        try:
            st.session_state.model_ids = nim.list_models()
        except Exception as e:
            st.error(str(e))
    if st.session_state.get("model_ids"):
        flt = st.text_input("Filter the list", "vl", key="model_filter")
        ids = [i for i in st.session_state.model_ids if flt.lower() in i.lower()]
        st.caption(f"{len(ids)} of {len(st.session_state.model_ids)} models")
        st.dataframe(pd.DataFrame({"model id": ids}), hide_index=True)

    st.markdown("**Change the admin password:** open the app in Streamlit Cloud → Settings → Secrets → edit `MASTER_KEY` → Save. "
                "The app restarts and the new key works immediately. Nothing else needs changing.")

    if st.button("🧪 Test the AI connection"):
        with st.spinner("Calling NVIDIA NIM..."):
            try:
                st.success(f"Model replied: {nim.chat([{'role': 'user', 'content': 'Reply with the single word OK.'}], max_tokens=20)}")
            except Exception as e:
                st.error(e)

    st.subheader("Export everything (CSV zip)")
    EXPORT = {"users": "id,username,display_name,role,active,created,last_login,note", "scans": "id,user_id,created,subject,topic,label,mime"}
    TABLES = ["users", "requests", "events", "login_log", "mistakes", "notes", "scans", "topic_tests", "sprints", "cards",
              "reviews", "study_log", "checkins", "topic_stats", "exams", "plans"]
    if st.button("Prepare export"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for t in TABLES:
                z.writestr(f"{t}.csv", pd.DataFrame(db.rows(f"SELECT {EXPORT.get(t, '*')} FROM {t}")).to_csv(index=False))
        st.session_state.export_zip = buf.getvalue()
    if st.session_state.get("export_zip"):
        st.download_button("⬇ Download export", st.session_state.export_zip, "lockin_export.zip", "application/zip")

    if not pg:
        st.subheader("SQLite backup / restore")
        if db.SQLITE_PATH.exists():
            st.download_button("Download database file", db.SQLITE_PATH.read_bytes(), "lockin.db")
        up = st.file_uploader("Restore a database file", type=["db"], key="restore_up")
        if up and st.button("Restore now"):
            db.SQLITE_PATH.write_bytes(up.getvalue())
            db.reset_ready()
            st.rerun()
