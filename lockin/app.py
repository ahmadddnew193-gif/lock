import datetime as dt
import pandas as pd
import streamlit as st
from core import db, ui

ui.setup("Command Center", "🎯")
wk = db.week_start()

if dt.date.today().weekday() == 6 and not db.rows("SELECT 1 FROM checkins WHERE week_start=?", (wk,)):
    st.warning("📅 It's Sunday: do your **Weekly Check-in** before Monday starts.")

due = len(db.due_cards())
reviewed_today = db.rows("SELECT COUNT(*) n FROM reviews WHERE substr(created,1,10)=?", (db.today(),))[0]["n"]
mins_today = db.rows("SELECT COALESCE(SUM(minutes),0) m FROM study_log WHERE day=?", (db.today(),))[0]["m"]
retry = len(db.retry_queue("week"))

c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Streak", f"{db.streak()} days")
c2.metric("🃏 Cards due", due, f"{reviewed_today} done today")
c3.metric("🔁 Mistakes to retry (7d)", retry)
c4.metric("⏱ Studied today", f"{mins_today} min")

st.subheader("Today's non-negotiables")
st.checkbox("At least 1 flashcard session (do it on autopilot, e.g. morning commute)", value=reviewed_today > 0, disabled=True)
st.checkbox("Log your study time", value=mins_today > 0, disabled=True)
st.checkbox("Retry some mistakes", value=False, disabled=True)

left, right = st.columns([2, 1])
with left:
    st.subheader("Study heatmap (protect the streak)")
    ui.heatmap(db.heat_minutes())
with right:
    st.subheader("Log study time")
    with st.form("log", clear_on_submit=True):
        s = ui.subject_picker("Subject", "dash")
        m = st.number_input("Minutes", 5, 600, 60, step=5)
        if st.form_submit_button("Log it", type="primary"):
            db.log_study(s, m)
            st.rerun()

st.subheader("Weakest topics (colour-coded, feeds your weekly exam)")
weak = db.weak_topics()
if weak:
    df = pd.DataFrame(weak)
    st.dataframe(df, hide_index=True)
else:
    st.info("Nothing yet. Log a mistake or snap a page.")

with st.expander("How the system works"):
    st.markdown("""
**Learning happens in the background (flashcards). Studying is just testing (past papers + mistakes).**
1. **Subject Hub** is the one place everything lives (notes, topic tests, exam scans).
2. **Mistakes** are logged with a reason (*didn't know / knew but didn't recognise / silly*) and **retried** weekly, monthly, and before tests.
3. **Flashcards** run daily with spaced repetition. Mistakes feed back in as cards.
4. **Past Paper Sprints** every weekend, timed, tracked.
5. **Weekly Check-in** every Sunday, with real numbers and a plan.
6. **Weekly Exam** (AI): built from your mistakes + weak topics so you're always tested on what hurts.
""")
