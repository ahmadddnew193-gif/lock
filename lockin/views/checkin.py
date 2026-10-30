import json
import datetime as dt
import streamlit as st
from core import db, nim, ui

ui.header("Sunday Check-in", "✅")
u = db.uid()
wk = db.week_start()
prev_wk = (dt.date.fromisoformat(wk) - dt.timedelta(days=7)).isoformat()
st.caption(f"Week of {wk} · Don't wait for New Year to stop and think. Do it every week.")

cur, prev = db.week_stats(wk), db.week_stats(prev_wk)
c1, c2, c3, c4 = st.columns(4)
c1.metric("⏱ Study hours", f"{cur['study_minutes']/60:.1f}", f"{(cur['study_minutes']-prev['study_minutes'])/60:+.1f} vs last wk")
c2.metric("📅 Days studied", cur["days_studied"], cur["days_studied"] - prev["days_studied"])
c3.metric("🃏 Cards reviewed", cur["cards_reviewed"], cur["cards_reviewed"] - prev["cards_reviewed"])
c4.metric("🎯 Card accuracy", f"{cur['card_accuracy_%']}%" if cur["card_accuracy_%"] is not None else "-")
if cur["sprints"]:
    st.write("**Past-paper sprints:** " + " · ".join(f"{s['subject']} {s['paper']}: {s['score_pct']:.0f}%" for s in cur["sprints"]))
if cur["mistake_categories"]:
    st.write("**New mistakes by cause:** " + " · ".join(f"{k}: {v}" for k, v in cur["mistake_categories"].items()))

SYS = """You are a blunt but supportive study coach for a student using this system: central hub, mistakes notes
(didn't know / didn't recognise / silly), weekend timed past papers, daily Anki flashcards, streaks.
Using the numbers, return a markdown plan:
1) What the data says (compare to last week; diagnose by mistake category)
2) Top 3 changes for next week, each concrete (e.g. 'silly mistakes up, add a 2-min check pass')
3) Day-by-day schedule that includes: daily cards, Saturday/Sunday timed paper, mistake retries, the weak topics
4) One habit to drop, one to keep. Under 350 words."""

prev_ci = db.rows("SELECT * FROM checkins WHERE user_id=? AND week_start=?", (u, wk))
p = prev_ci[0] if prev_ci else {}
with st.form("ci"):
    energy = st.slider("Energy / focus this week (1-10)", 1, 10, int(p.get("energy") or 6))
    wins = st.text_area("What went well?", p.get("wins") or "")
    struggles = st.text_area("Where was I distracted / what did I avoid?", p.get("struggles") or "")
    goals = st.text_area("Goals, deadlines, and what I'll do differently", p.get("goals") or "")
    go = st.form_submit_button("Submit & recalibrate", type="primary")

if go:
    ctx = json.dumps({"this_week": cur, "last_week": prev, "energy": energy, "wins": wins, "distractions": struggles,
                      "goals": goals, "weak_topics": db.weak_topics(), "streak": db.streak(),
                      "open_mistakes": len(db.retry_queue("month"))})
    with st.spinner("Coach is thinking..."):
        try:
            plan = nim.chat([{"role": "system", "content": SYS}, {"role": "user", "content": ctx}], temperature=0.5)
            db.save_checkin(wk, cur["study_minutes"] / 60, energy, wins, struggles, goals, plan)
            st.rerun()
        except Exception as e:
            st.error(f"Failed: {e}")

if p.get("ai_plan"):
    st.subheader("Plan for next week")
    st.markdown(p["ai_plan"])

with st.expander("Weekly log (past check-ins)"):
    for r in db.rows("SELECT * FROM checkins WHERE user_id=? ORDER BY week_start DESC", (u,)):
        st.markdown(f"**{r['week_start']}** · {r['hours']:.1f}h · energy {r['energy']}/10  \n{r['wins'] or ''}")
