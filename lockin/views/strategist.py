import datetime as dt
from collections import Counter
import pandas as pd
import plotly.express as px
import streamlit as st
from core import ai, db, ui

ui.header("Exam Strategist", "🎯")
u = db.uid()
st.caption("You're not meant to know everything equally well. Find the highest-yield topics, the right order, and what to skip.")

with st.expander("How this works", expanded=False):
    st.markdown("""
1. Paste past exam questions (one per line). The AI sorts each into a topic and **the app tallies them itself**, so the counts are real.
2. It combines the tally with your syllabus, time budget and weak spots into an ordered plan.
3. Read the skip list critically. Skipping is a calculated risk, so only skip what the data supports.
""")

c1, c2, c3 = st.columns(3)
exam = c1.text_input("Exam", placeholder="Biology Paper 2")
date = c2.date_input("Exam date", dt.date.today() + dt.timedelta(days=21))
hpd = c3.number_input("Study hours per day", 0.5, 14.0, 3.0, step=0.5)
questions = st.text_area("Past exam questions (one per line, as many years as you have)", height=220,
                         placeholder="Explain the role of ATP in muscle contraction\nCalculate the rate of reaction from the graph\n...")
syllabus = st.text_area("Syllabus topics (optional, one per line)", height=100)
use_mine = st.checkbox("Factor in my own weak topics", value=True)

if st.button("🧠 Build my strategy", type="primary"):
    lines = [l.strip() for l in questions.splitlines() if len(l.strip()) > 8][:200]
    syl = [l.strip() for l in syllabus.splitlines() if l.strip()]
    days_left = max(1, (date - dt.date.today()).days)
    if len(lines) < 5:
        st.warning("Add at least 5 past questions so there's a pattern to find. 20+ is better.")
    else:
        with st.spinner(f"Sorting {len(lines)} questions into topics..."):
            try:
                assign = ai.classify_questions(lines, syl)
                tally = Counter(assign.values())
            except Exception as e:
                st.error(f"Classification failed: {e}")
                st.stop()
        weak = [{"subject": w["subject"], "topic": w["topic"]} for w in db.weak_topics(10)] if use_mine else []
        with st.spinner("Working out your plan..."):
            try:
                plan = ai.strategy(exam, dict(tally.most_common(40)), syl, days_left, hpd, weak)
                budget = days_left * hpd
                total = sum(float(p.get("hours", 0) or 0) for p in plan.get("priorities", []))
                if total > budget and total > 0:
                    k = budget / total
                    for p in plan["priorities"]:
                        p["hours"] = round(float(p.get("hours", 0)) * k, 1)
                plan["tally"] = dict(tally.most_common(40))
                plan["n_questions"] = len(lines)
                plan["days_left"], plan["hours_per_day"] = days_left, hpd
                db.save_plan(exam or "Exam", plan)
                st.rerun()
            except Exception as e:
                st.error(f"Strategy failed: {e}")

plan = db.latest_plan(u)
if not plan:
    st.info("No plan yet. Paste some past questions above.")
    st.stop()

st.subheader(f"Your plan: {plan.get('_exam', '')}")
st.success(plan.get("headline", ""))
m1, m2, m3 = st.columns(3)
m1.metric("Questions analysed", plan.get("n_questions", "-"))
m2.metric("Days left (when built)", plan.get("days_left", "-"))
m3.metric("Hours budget", round(plan.get("days_left", 0) * plan.get("hours_per_day", 0), 1))

left, right = st.columns(2)
with left:
    tally = plan.get("tally", {})
    if tally:
        d = pd.DataFrame({"topic": list(tally), "questions": list(tally.values())}).sort_values("questions").tail(15)
        fig = px.bar(d, x="questions", y="topic", orientation="h", title="How often each topic appears")
        fig.update_layout(height=max(300, 40 + 30 * len(d)), yaxis_title=None, xaxis_title=None, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig)
with right:
    pr = plan.get("priorities", [])
    if pr:
        d = pd.DataFrame(pr)
        d["hours"] = pd.to_numeric(d["hours"], errors="coerce").fillna(0)
        fig = px.pie(d, names="topic", values="hours", hole=0.5, title="Where your hours go")
        fig.update_layout(height=400, paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig)

if plan.get("patterns"):
    st.subheader("🔎 Patterns in the exam")
    for p in plan["patterns"]:
        st.markdown(f"- {p}")

st.subheader("📚 Study in this order")
for p in plan.get("priorities", []):
    icon = {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(p.get("yield"), "⚪")
    with st.expander(f"{p.get('rank', '')}. {p.get('topic', '')}  ·  {icon} {p.get('yield', '')} yield  ·  {p.get('hours', 0)}h  ·  seen {p.get('frequency', 0)}×"):
        st.markdown(f"**Why:** {p.get('why', '')}")
        st.markdown(f"**How:** {p.get('how', '')}")

if plan.get("memorise_sets"):
    st.subheader("🧠 Worth memorising outright")
    for s in plan["memorise_sets"]:
        st.markdown(f"- {s}")

if plan.get("skip"):
    st.subheader("⏭ Calculated skips")
    st.caption("Sanity-check each one yourself before you drop it.")
    for s in plan["skip"]:
        st.warning(f"**{s.get('topic', '')}**: {s.get('why', '')}")

if plan.get("schedule"):
    st.subheader("🗓 Schedule")
    st.dataframe(pd.DataFrame(plan["schedule"]), hide_index=True)

if plan.get("risks"):
    st.subheader("⚠️ Risks")
    for r in plan["risks"]:
        st.markdown(f"- {r}")
