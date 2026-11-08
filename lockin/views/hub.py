import pandas as pd
import streamlit as st
from core import ai, db, nim, ui

ui.header("Subject Hub", "🗂")
u = db.uid()
st.caption("Everything in one place → zero friction → no procrastination.")

q = st.text_input("🔎 Search everything (notes, mistakes, flashcards)")
if q:
    like = f"%{q.lower()}%"
    n = db.rows("SELECT subject,topic,body FROM notes WHERE user_id=? AND (LOWER(body) LIKE ? OR LOWER(topic) LIKE ?)", (u, like, like))
    m = db.rows("SELECT subject,topic,question,correct_answer FROM mistakes WHERE user_id=? AND (LOWER(question) LIKE ? OR LOWER(correct_answer) LIKE ? OR LOWER(topic) LIKE ?)", (u, like, like, like))
    c = db.rows("SELECT subject,topic,front,back FROM cards WHERE user_id=? AND (LOWER(front) LIKE ? OR LOWER(back) LIKE ?)", (u, like, like))
    st.write(f"**{len(n)}** notes · **{len(m)}** mistakes · **{len(c)}** cards")
    for r in n:
        st.markdown(f"🗒 **{r['subject']} / {r['topic']}**: {r['body'][:300]}")
    for r in m:
        st.markdown(f"❌ **{r['subject']} / {r['topic']}**: {r['question'][:200]}")
    for r in c:
        st.markdown(f"🃏 **{r['subject']} / {r['topic']}**: {r['front']} → {r['back']}")
    st.divider()

subj = ui.subject_picker("Subject", "hub")
sn = subj.strip().title()
t1, t2, t3, t4 = st.tabs(["📊 Overview", "🗒 Notes", "🧪 Topic tests", "📎 Scans"])

with t1:
    weak = db.weak_topics(20, subj)
    if weak:
        st.dataframe(pd.DataFrame(weak), hide_index=True)
    else:
        st.info("No open mistakes in this subject. Nice, or you haven't logged any yet.")
    sp = db.rows("SELECT substr(created,1,10) d, paper, score_pct FROM sprints WHERE user_id=? AND subject=? ORDER BY created", (u, sn))
    if sp:
        st.subheader("Past-paper trend")
        st.line_chart(pd.DataFrame(sp).set_index("d")["score_pct"])

with t2:
    with st.form("note", clear_on_submit=True):
        topic = st.text_input("Topic")
        body = st.text_area("Note", height=150)
        if st.form_submit_button("Save note") and body:
            db.add_note(subj, topic, body)
            st.rerun()
    for nrow in db.rows("SELECT * FROM notes WHERE user_id=? AND subject=? ORDER BY created DESC", (u, sn)):
        with st.expander(f"{nrow['topic']} · {nrow['created'][:10]}"):
            st.write(nrow["body"])
            ui.explain_box(nrow["body"], f"note{nrow['id']}", subj)

with t3:
    with st.form("tt", clear_on_submit=True):
        topic = st.text_input("Topic tested")
        score = st.slider("Score %", 0, 100, 70)
        if st.form_submit_button("Log topic test") and topic:
            db.add_topic_test(subj, topic, score)
            st.rerun()
    tt = db.rows("SELECT created,topic,score_pct FROM topic_tests WHERE user_id=? AND subject=? ORDER BY created DESC", (u, sn))
    if tt:
        df = pd.DataFrame(tt)
        df["level"] = df.score_pct.apply(lambda s: "🟢" if s >= 80 else "🟠" if s >= 60 else "🔴")
        st.dataframe(df, hide_index=True)

with t4:
    up = st.file_uploader("Upload a scan or photo of a marked paper or worksheet", type=["png", "jpg", "jpeg"])
    label = st.text_input("Label", placeholder="2024 Paper 2 (marked)")
    if up and st.button("Save scan"):
        data, mime = nim.prep_image(up.getvalue())
        db.add_scan(subj, "", label, mime, data)
        st.rerun()
    cmap = {"didnt_know": db.CATS[0], "didnt_recognise": db.CATS[1], "silly": db.CATS[2]}
    for s in db.rows("SELECT id,created,label,mime,data FROM scans WHERE user_id=? AND subject=? ORDER BY created DESC", (u, sn)):
        sid = s["id"]
        with st.expander(f"{s['label'] or 'scan'} · {s['created'][:10]}"):
            st.image(s["data"])
            exp = st.number_input("How many questions did you lose marks on? (0 = not sure)", 0, 50, 0, key=f"exp{sid}")
            if st.button("🤖 Scan this paper for mistakes", key=f"x{sid}"):
                with st.spinner("The vision model is reading the paper, then the teacher checks it..."):
                    try:
                        st.session_state[f"ext{sid}"] = ai.extract_paper(s["data"], int(exp) or None)
                    except Exception as e:
                        st.error(str(e))
            ext = st.session_state.get(f"ext{sid}")
            if not ext:
                continue
            if ext["marked"]:
                st.success("Teacher marks detected. Only questions with lost marks, a cross, or a partial mark are listed.")
            else:
                st.warning("No teacher marks found, so the AI had to judge your answers itself. Only tick what you agree is wrong.")
            if ext["unreadable"]:
                st.caption(f"Couldn't read: {ext['unreadable']}")
            if ext["transcript"]:
                with st.expander(f"What was read from the page ({len(ext['transcript'])} questions)"):
                    st.dataframe(pd.DataFrame([{"ref": q["ref"], "question": str(q.get("question", ""))[:60],
                                                "student answer": str(q.get("student_answer", ""))[:60],
                                                "awarded": q.get("marks_awarded"), "available": q.get("marks_available"),
                                                "mark": q.get("teacher_mark"), "comment": q.get("teacher_comment")}
                                               for q in ext["transcript"]]), hide_index=True)
            items = ext["items"]
            if not items:
                st.success("No lost marks found on this page.")
                continue
            if int(exp) and len(items) != int(exp):
                st.warning(f"You said {int(exp)} but {len(items)} were found. Untick any that are wrong.")
            picks = []
            for j, it in enumerate(items):
                on = st.checkbox(f"**{it['ref']}** · {it['topic']}: {str(it['question'])[:90]}", value=it["confidence"] == "high", key=f"ck{sid}_{j}")
                st.caption(f"Why: {it['reason']}  |  Evidence: {it['evidence']}  |  Correct: {it['correct_answer']}")
                if on:
                    picks.append(it)
            if st.button(f"💾 Save {len(picks)} selected as mistakes", key=f"sv{sid}", disabled=not picks):
                for it in picks:
                    db.add_mistake(subj or ext.get("subject") or "General", it["topic"], f"{it['ref']}: {it['question']}",
                                   it["student_answer"], it["correct_answer"], it["reason"],
                                   cmap.get(it["category"], db.CATS[0]), s["label"] or "", "scan")
                st.session_state.pop(f"ext{sid}", None)
                st.success(f"Saved {len(picks)} mistakes.")
