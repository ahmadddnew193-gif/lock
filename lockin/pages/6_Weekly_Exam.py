import json
import streamlit as st
from core import db, nim, ui

ui.setup("Weekly Exam", "📝")
st.caption("An AI exam built from your mistakes and weak topics. Different every week.")

SYS_EXAM = """You write exams that target a student's specific weaknesses.
Return JSON: {"title": str, "questions": [
 {"id": int, "type": "mcq" or "short", "subject": str, "topic": str, "question": str,
  "options": ["A. ..","B. ..","C. ..","D. .."] (mcq only),
  "answer": "letter for mcq, model answer for short", "explanation": str}]}
Rules: ~60% NEW variations of the same underlying concept as the mistakes (do NOT copy the originals).
For mistakes categorised "Knew it, didn't recognise the question", disguise the concept in an unfamiliar
context or format. For "Silly mistake", include a tempting trap. ~25% mix two weak concepts.
~15% fresh topics from the notes. Mix mcq and short. Exam-board difficulty, plausible distractors."""

SYS_GRADE = 'Grade a short answer against the model answer. Return JSON: {"score": number 0-1, "feedback": "1-2 sentences"}'

n_q = st.slider("Number of questions", 5, 20, 10)

if st.button("⚡ Generate this week's exam", type="primary"):
    mistakes = db.mistakes_since(7) or db.rows("SELECT * FROM mistakes WHERE resolved=0 ORDER BY created DESC LIMIT 20")
    notes = db.rows("SELECT subject,topic,body FROM notes ORDER BY created DESC LIMIT 8")
    if not mistakes and not notes:
        st.warning("Log some mistakes or notes first.")
    else:
        payload = json.dumps({"n_questions": n_q,
            "mistakes": [{k: m[k] for k in ("subject", "topic", "question", "correct_answer", "reason", "category")} for m in mistakes[:25]],
            "weak_topics": db.weak_topics(), "notes": notes})
        with st.spinner("NIM is building your exam..."):
            exam = nim.chat_json(SYS_EXAM, payload, temperature=0.5, max_tokens=4000)
        st.session_state.exam, st.session_state.exam_id, st.session_state.exam_res = exam, db.save_exam(db.week_start(), exam), None

exam = st.session_state.get("exam")
if exam:
    st.subheader(exam.get("title", "Weekly Exam"))
    with st.form("exam"):
        ans = {}
        for q in exam["questions"]:
            st.markdown(f"**{q['id']}. {q['question']}**  \n`{q['subject']} · {q['topic']}`")
            if q["type"] == "mcq":
                ans[q["id"]] = st.radio("", q["options"], key=f"q{q['id']}", index=None, label_visibility="collapsed")
            else:
                ans[q["id"]] = st.text_area("", key=f"q{q['id']}", label_visibility="collapsed")
        sub = st.form_submit_button("Submit exam", type="primary")

    if sub:
        def grade(q):
            a = ans.get(q["id"]) or ""
            if q["type"] == "mcq":
                ok = bool(a) and a.strip()[0].upper() == str(q["answer"]).strip()[0].upper()
                return {"score": 1.0 if ok else 0.0, "feedback": q["explanation"]}
            try:
                return nim.chat_json(SYS_GRADE, f"Q: {q['question']}\nModel: {q['answer']}\nStudent: {a or '(blank)'}", kind="fast")
            except Exception:
                return {"score": 0, "feedback": "Grading failed."}
        with st.spinner("Grading in parallel..."):
            res = nim.parallel(grade, exam["questions"])
        score = sum(r["score"] for r in res) / len(res) * 100
        db.finish_exam(st.session_state.exam_id, score)
        for q, r in zip(exam["questions"], res):
            if r["score"] >= 0.7:
                db.record_result(q["subject"], q["topic"], True)
            else:
                db.add_mistake(q["subject"], q["topic"], q["question"], str(ans.get(q["id"]) or ""), str(q["answer"]),
                               q["explanation"], db.CATS[0], f"Weekly exam {db.week_start()}", "weekly_exam")
        st.session_state.exam_res = (score, res)

    if st.session_state.get("exam_res"):
        score, res = st.session_state.exam_res
        st.metric("Score", f"{score:.0f}%")
        for q, r in zip(exam["questions"], res):
            with st.expander(f"{'🟢' if r['score'] >= 0.7 else '🔴'} Q{q['id']} · {q['topic']}"):
                st.write(r["feedback"]); st.caption(f"Answer: {q['answer']}")
        st.info("Missed questions went into your retry queue.")

hist = db.rows("SELECT created,score FROM exams WHERE taken=1 ORDER BY created")
if hist:
    st.divider(); st.subheader("Score history")
    st.line_chart({h["created"][:10]: h["score"] for h in hist})
