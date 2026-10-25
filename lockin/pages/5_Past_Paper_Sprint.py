import time
import pandas as pd
import streamlit as st
from core import db, ui

ui.setup("Past Paper Sprint", "⏱")
st.caption("Every weekend: a full timed paper, no breaks, exam conditions. Track the trend.")

subj = ui.subject_picker("Subject", "sp")
paper = st.text_input("Paper", placeholder="2024 Paper 2")
dur = st.number_input("Time allowed (minutes)", 10, 240, 120, step=5)
if st.button("▶ Start sprint", type="primary"):
    st.session_state.sprint = {"start": time.time(), "dur": dur, "subject": subj, "paper": paper}


@st.fragment(run_every=1)
def clock():
    s = st.session_state.get("sprint")
    if not s:
        return
    left = s["dur"] * 60 - (time.time() - s["start"])
    if left > 0:
        st.metric(f"⏳ {s['paper'] or 'Paper'} · {s['subject']}", f"{int(left // 60):02d}:{int(left % 60):02d}")
    else:
        st.error("⏰ Time's up. Pens down.")


clock()

s = st.session_state.get("sprint")
if s:
    st.subheader("Finish & log")
    with st.form("fin"):
        score = st.slider("Score % (after marking)", 0, 100, 60)
        lost = st.text_area("Questions I lost marks on (one per line: `4a, chain rule`)")
        cat = st.radio("Mostly because…", db.CATS, horizontal=True)
        if st.form_submit_button("✅ Log sprint", type="primary"):
            mins = max(1, round((time.time() - s["start"]) / 60))
            db.run("INSERT INTO sprints(created,subject,paper,minutes,score_pct) VALUES(?,?,?,?,?)",
                   (db.now(), s["subject"].title(), s["paper"], mins, score))
            db.log_study(s["subject"], mins)
            for line in filter(None, (l.strip() for l in lost.splitlines())):
                ref, _, topic = line.partition(",")
                db.add_mistake(s["subject"], topic.strip() or "General", f"{s['paper']} {ref.strip()}", category=cat,
                               paper_ref=f"{s['paper']} {ref.strip()}", source="past_paper")
            del st.session_state["sprint"]
            st.success("Logged. Mistakes are now in your retry queue.")
            st.rerun()

hist = db.rows("SELECT created,subject,paper,minutes,score_pct FROM sprints ORDER BY created")
if hist:
    df = pd.DataFrame(hist)
    st.subheader("Progress")
    df["date"] = df.created.str[:10]
    st.line_chart(df.pivot_table(index="date", columns="subject", values="score_pct"))
    st.dataframe(df.drop(columns="date").sort_values("created", ascending=False), hide_index=True)
