import datetime as dt
import pandas as pd
import streamlit as st
from core import auth, db, ui, viz

ui.header("Command Center", "🎯")
u = db.uid()
wk = db.week_start()
st.caption(f"Welcome back, {auth.current()['display_name']}. Protect the streak.")

if dt.date.today().weekday() == 6 and not db.rows("SELECT 1 FROM checkins WHERE user_id=? AND week_start=?", (u, wk)):
    st.warning("📅 It's Sunday: do your **Sunday Check-in** before Monday starts.")

sm = db.summary()
due, mins_today, retry = sm["due"], sm["mins_today"], sm["retry_week"]
ev = db.events_today()
plan = db.latest_plan()

c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Streak", f"{db.streak()} days")
c2.metric("🃏 Cards due", due, f"{sm['reviewed_today']} done today")
c3.metric("🔁 Mistakes to retry (7d)", retry)
c4.metric("⏱ Studied today", f"{mins_today} min")

tasks = []
total_cards = sm["total_cards"]
if due:
    tasks.append((f"Clear your {due} due flashcards (~{max(5, round(due * 0.5))} min)", False, "views/flashcards.py", ":material/style:"))
elif total_cards:
    tasks.append(("Flashcards cleared for today", True, "views/flashcards.py", ":material/style:"))
else:
    tasks.append(("Create your first flashcards from a page or notes", False, "views/snap.py", ":material/photo_camera:"))
if retry:
    tasks.append((f"Retry {min(5, retry)} open mistakes (~10 min)", ev.get("retry", 0) >= min(3, retry), "views/mistakes.py", ":material/error:"))
if plan and plan.get("priorities"):
    top = plan["priorities"][0].get("topic", "your top-priority topic")
    tasks.append((f"Teach-back on a high-yield topic: {top} (~15 min)", ev.get("teachback", 0) >= 1, "views/teachback.py", ":material/science:"))
else:
    tasks.append(("Build your exam strategy once, so every hour goes to the right topic", False, "views/strategist.py", ":material/flag:"))
if dt.date.today().weekday() >= 5:
    tasks.append(("Weekend timed past-paper sprint", ev.get("sprint", 0) >= 1, "views/sprint.py", ":material/timer:"))
tasks.append(("Log your study time", mins_today > 0, "views/dashboard.py", ":material/timer:"))

done = sum(1 for t in tasks if t[1])
st.subheader(f"Today's mission · {done}/{len(tasks)}")
st.progress(done / len(tasks))
for label, ok, page, icon in tasks:
    a, b = st.columns([5, 1])
    a.checkbox(label, value=ok, disabled=True, key=f"mission_{label}")
    if not ok and page != "views/dashboard.py":
        b.page_link(page, label="Go", icon=icon)

left, right = st.columns([2, 1])
with left:
    st.subheader("Study heatmap")
    ui.heatmap(db.heat_minutes())
    fig = viz.forecast(u)
    if fig:
        st.plotly_chart(fig)
with right:
    st.subheader("Log study time")
    with st.form("log", clear_on_submit=True):
        s = ui.subject_picker("Subject", "dash")
        m = st.number_input("Minutes", 5, 600, 60, step=5)
        if st.form_submit_button("Log it", type="primary"):
            db.log_study(s, m)
            st.rerun()

if plan and plan.get("priorities"):
    st.subheader(f"🎯 Priority topics for {plan.get('_exam', 'your exam')}")
    st.write(" → ".join(f"**{p.get('topic', '')}**" for p in plan["priorities"][:6]))

st.subheader("Weakest topics")
weak = db.weak_topics()
if weak:
    st.dataframe(pd.DataFrame(weak), hide_index=True)
else:
    st.info("Nothing yet. Log a mistake or snap a page.")

with st.expander("The system in one minute"):
    st.markdown("""
**Learning happens in the background (flashcards). Studying is testing and thinking.**
- **Exam Strategist:** don't learn everything equally. Find the high-yield topics, the order, and what to skip.
- **Teach-Back Lab:** learn in layers, compress it to one line, compare it, argue with the AI, verify it.
- **Explain Simply / Snap & Think:** get unstuck fast, then build the concept map yourself.
- **Mistakes + Flashcards:** every miss is logged with a reason, retried, and turned into spaced-repetition cards.
- **Past Paper Sprints + Weekly Exam:** timed practice and AI exams built from your weak spots.
- **Sunday Check-in + Insights:** review the numbers, recalibrate.

Rule: AI should challenge your thinking, never replace it.
""")
