import streamlit as st
from core import ai, db, nim, ui

ui.setup("Snap & Think", "📸")
st.caption("Photo → key concepts → think *between* the concepts → cards & mistakes feed the system.")

SYS_ANALYZE = """You are an elite exam coach. Look at the student's page.
Identify the 3-6 MOST IMPORTANT concepts (things that actually get tested), not trivia.
Return JSON:
{"subject": str, "topic": str, "summary": "2 sentences",
 "concepts": [{"name": str, "explanation": "plain language, max 2 sentences",
               "why_it_matters": str, "common_trap": str}],
 "lock_in_questions": [{"between": [conceptA, conceptB],
    "question": "forces the student to explain HOW/WHY the two connect or differ",
    "ideal_answer": str}]}
Make 4-6 lock_in_questions requiring reasoning, not recall."""

SYS_GRADE = """Grade the student's answer strictly but kindly. Return JSON:
{"score": 0-10 integer, "feedback": "2 sentences", "missing": "what a perfect answer had that theirs lacked",
 "category": "didnt_know" | "didnt_recognise" | "silly"}"""

src = st.radio("Input", ["📷 Camera", "🖼 Upload"], horizontal=True)
img = st.camera_input("Snap your page") if src == "📷 Camera" else st.file_uploader("Upload", type=["png", "jpg", "jpeg"])
extra = st.text_input("Optional context (course, exam type, what you're stuck on)")

if img and st.button("🔍 Extract concepts", type="primary"):
    with st.spinner("NIM vision model reading your page..."):
        try:
            st.session_state.snap = nim.vision_json(SYS_ANALYZE, f"Context: {extra or 'none'}", img.getvalue(), img.type or "image/jpeg")
            st.session_state.snap_img = (img.getvalue(), img.type or "image/jpeg")
            st.session_state.snap_graded = None
        except Exception as e:
            st.error(f"Failed: {e}")

snap = st.session_state.get("snap")
if snap:
    st.success(f"**{snap.get('subject')} · {snap.get('topic')}**: {snap.get('summary')}")
    a, b = st.columns(2)
    if a.button("💾 Save photo to Subject Hub"):
        data, mime = st.session_state.snap_img
        db.run("INSERT INTO scans(created,subject,topic,label,mime,data) VALUES(?,?,?,?,?,?)",
               (db.now(), snap["subject"].title(), snap["topic"].title(), "Snap & Think", mime, data))
        st.toast("Saved")
    if b.button("🃏 Turn concepts into flashcards"):
        with st.spinner("Writing cards..."):
            mat = "\n".join(f"{c['name']}: {c['explanation']} Trap: {c['common_trap']}" for c in snap["concepts"])
            cards = ai.make_cards(mat, 8)
            for c in cards:
                db.add_card(snap["subject"], snap["topic"], c["front"], c["back"], "snap")
            st.success(f"Added {len(cards)} cards to your daily reviews.")

    st.subheader("🧠 Key concepts")
    for c in snap["concepts"]:
        with st.expander(c["name"], expanded=True):
            st.write(c["explanation"])
            st.markdown(f"**Why it matters:** {c['why_it_matters']}")
            st.warning(f"Trap: {c['common_trap']}")

    st.subheader("🔒 Lock in: think between the concepts")
    st.caption("No peeking. Answer from memory (retrieval, not re-reading).")
    with st.form("lockin"):
        answers = []
        for i, q in enumerate(snap["lock_in_questions"]):
            st.markdown(f"**Q{i+1}.** `{q['between'][0]}` ↔ `{q['between'][1]}`")
            answers.append(st.text_area(q["question"], key=f"ans{i}", height=90))
        go = st.form_submit_button("Grade me", type="primary")

    if go:
        def grade(i):
            q = snap["lock_in_questions"][i]
            try:
                return nim.chat_json(SYS_GRADE, f"Question: {q['question']}\nIdeal: {q['ideal_answer']}\nStudent: {answers[i] or '(blank)'}", kind="fast")
            except Exception as e:
                return {"score": 0, "feedback": str(e), "missing": "", "category": "didnt_know"}
        with st.spinner("Grading all answers in parallel..."):
            st.session_state.snap_graded = nim.parallel(grade, range(len(answers)))
            st.session_state.snap_answers = answers

    res = st.session_state.get("snap_graded")
    if res:
        st.metric("Understanding", f"{sum(r['score'] for r in res) / (10 * len(res)) * 100:.0f}%")
        for i, r in enumerate(res):
            q = snap["lock_in_questions"][i]
            icon = "🟢" if r["score"] >= 7 else "🟠" if r["score"] >= 4 else "🔴"
            with st.expander(f"{icon} Q{i+1}: {r['score']}/10"):
                st.write(r["feedback"]); st.info(f"Missing: {r['missing']}"); st.caption(f"Ideal: {q['ideal_answer']}")
        if st.button("💾 Log answers under 7 as mistakes"):
            cmap = {"didnt_know": db.CATS[0], "didnt_recognise": db.CATS[1], "silly": db.CATS[2]}
            n = 0
            for i, r in enumerate(res):
                q = snap["lock_in_questions"][i]
                if r["score"] >= 7:
                    db.record_result(snap["subject"], snap["topic"], True)
                else:
                    db.add_mistake(snap["subject"], snap["topic"], q["question"], st.session_state.snap_answers[i],
                                   q["ideal_answer"], r["missing"], cmap.get(r.get("category"), db.CATS[0]), "", "snap_and_think")
                    n += 1
            st.success(f"Logged {n} mistakes.")
