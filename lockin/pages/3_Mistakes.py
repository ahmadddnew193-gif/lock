import pandas as pd
import streamlit as st
from core import ai, db, nim, ui

ui.setup("Mistakes", "❌")
st.caption("Log it, classify it, then go back and redo it. Weekly, monthly, and before tests.")
t1, t2, t3 = st.tabs(["➕ Log mistake", "🔁 Retry queue", "📋 All mistakes"])

with t1:
    with st.form("m", clear_on_submit=True):
        subj = ui.subject_picker("Subject", "mlog")
        topic = st.text_input("Topic", placeholder="Chain rule")
        ref = st.text_input("Where from?", placeholder="2024 Paper 2 Q4b")
        q = st.text_area("Question / what happened")
        mine = st.text_input("What I answered")
        right = st.text_input("Correct answer / approach")
        cat = st.radio("Why did I get it wrong?", db.CATS)
        why = st.text_input("Detail (optional)")
        if st.form_submit_button("Add mistake", type="primary") and q:
            db.add_mistake(subj, topic, q, mine, right, why, cat, ref)
            st.success("Logged.")

with t2:
    scope = st.radio("Scope", ["Weekly (last 7 days)", "Monthly (last 30 days)", "Before a test (a whole subject)"], horizontal=True)
    subj = ui.subject_picker("Subject", "mretry") if scope.startswith("Before") else None
    queue = db.retry_queue({"W": "week", "M": "month", "B": "test"}[scope[0]], subj)
    st.write(f"**{len(queue)}** open mistakes. Pass a retry twice and it's resolved.")

    didnt_know = [m for m in queue if m["category"] == db.CATS[0] and m["correct_answer"]]
    if didnt_know and st.button(f"🃏 Send {len(didnt_know)} 'didn't know' mistakes to flashcards"):
        have = {r["source_id"] for r in db.rows("SELECT source_id FROM cards WHERE source='mistake'")}
        n = 0
        for m in didnt_know:
            if m["id"] not in have:
                db.add_card(m["subject"], m["topic"], m["question"], m["correct_answer"], "mistake", m["id"]); n += 1
        st.success(f"Added {n} cards.")

    for m in queue[:15]:
        with st.expander(f"[{m['subject']} · {m['topic']}] {m['question'][:90]}  ·  {m['paper_ref'] or ''}"):
            st.caption(f"{m['category']} · retried {m['retries']}×")
            att = st.text_area("Your attempt", key=f"att{m['id']}")
            if st.button("Check", key=f"chk{m['id']}"):
                try:
                    r = ai.grade_retry(m["question"], m["correct_answer"], att)
                    db.mark_retry(m["id"], bool(r["pass"]))
                    db.record_result(m["subject"], m["topic"], bool(r["pass"]))
                    (st.success if r["pass"] else st.error)(f"{'✅ Pass' if r['pass'] else '❌ Not yet'} ({r['score']}/10): {r['feedback']}")
                    st.caption(f"Correct: {m['correct_answer']}")
                except Exception as e:
                    st.error(e)

with t3:
    data = db.rows("SELECT id,created,subject,topic,paper_ref,question,category,retries,resolved,source FROM mistakes ORDER BY created DESC")
    if data:
        df = pd.DataFrame(data)
        st.bar_chart(df.groupby("category").size())
        flt = st.multiselect("Filter category", db.CATS)
        st.dataframe(df[df.category.isin(flt)] if flt else df, hide_index=True)
        st.caption("Tip: lots of 'silly mistake'? Slow down & check. Lots of 'didn't recognise'? Do more varied past papers. Lots of 'didn't know'? More flashcards.")
