import time
import uuid
import streamlit as st
from core import ai, db, nim, ui, visual

ui.header("Don't Understand", "🤔")
st.caption("Tell me what's confusing, or show me a photo. I'll teach it in small steps with visuals, and you prove each step before the next one unlocks.")
ui.principle()

LEVELS = ["Complete beginner", "I know the basics", "Fairly advanced but stuck"]


def build(confusion, subj, level, img):
    img_bytes, source_text, regions = None, "", []
    with st.status("Building your lesson...", expanded=True) as status:
        try:
            if img is not None:
                st.write("📷 The vision model is reading your photo...")
                img_bytes, _ = nim.prep_image(img.getvalue())
                try:
                    info = ai.read_image_regions(img_bytes)
                    source_text = str(info.get("transcription", ""))
                    if info.get("visuals"):
                        source_text += "\n[Figure: " + str(info["visuals"]) + "]"
                    regions = visual.valid_regions(info.get("regions"))
                    subj = subj or str(info.get("subject_guess", ""))
                    confusion = confusion or f"I don't understand this: {info.get('topic_guess', '')}"
                except Exception as e:
                    st.write(f"⚠️ Couldn't read the photo ({str(e)[:120]}). Continuing with your words only.")
                    img_bytes = None
            if not confusion.strip() and not source_text.strip():
                raise ValueError("Tell me what you don't understand, or upload a clearer photo.")
            st.write("🧠 The teacher model is planning the lesson...")
            labels = [{"id": r["id"], "label": r["label"]} for r in regions]
            outline = ai.dnu_outline(confusion, subj, level, source_text, labels)
            ctx = {"outline": outline, "confusion": confusion, "subject": subj or outline.get("subject", ""),
                   "level": level, "source_text": source_text, "region_labels": labels}
            n = len(outline["stages"])
            st.write(f"✍️ Writing {n} steps and the final test in parallel...")

            def work(t):
                try:
                    return ("ok", ai.dnu_final(ctx) if t == "final" else ai.dnu_stage(ctx, t))
                except Exception as e:
                    return ("err", str(e))
            results = nim.parallel(work, list(range(n)) + ["final"], workers=6)
            stages = []
            for i in range(n):
                kind, val = results[i]
                if kind == "err":
                    kind, val = work(i)
                if kind == "err":
                    raise ValueError(val)
                ids = {r["id"] for r in regions}
                pointer = [int(x) for x in outline["stages"][i].get("regions", []) if str(x).lstrip("-").isdigit() and int(x) in ids]
                if not pointer and val["visual"].get("type") == "image_points":
                    pointer = [int(x) for x in val["visual"].get("regions", []) if str(x).lstrip("-").isdigit() and int(x) in ids]
                val["pointer"] = pointer
                stages.append(val)
            final = results[-1][1] if results[-1][0] == "ok" else None
            st.session_state.dnu = {
                "id": uuid.uuid4().hex[:8], "topic": outline.get("topic", confusion[:60]), "subject": ctx["subject"] or "General",
                "outline": outline, "stages": stages, "final": final, "passed": 0, "tries": {}, "picks": {}, "fb": {}, "alt": {},
                "img": img_bytes, "regions": regions, "source_text": source_text, "confusion": confusion, "level": level,
                "ctx": ctx, "result": None, "cards_saved": False, "ann": {}}
            db.log_event("dnu_start", outline.get("topic", ""))
            status.update(label="Your lesson is ready", state="complete", expanded=False)
        except Exception as e:
            status.update(label="Could not build the lesson", state="error")
            st.error(str(e))
            return False
    return True


D = st.session_state.get("dnu")

if not D:
    with st.container(border=True):
        confusion = st.text_area("What don't you understand?", height=110,
                                 placeholder="e.g. Why does a bigger current not mean faster electrons? / I don't get how this integral works")
        c1, c2 = st.columns(2)
        subj = c1.text_input("Subject (optional)")
        level = c2.selectbox("Your level", LEVELS)
        src = st.radio("Add a photo (optional)", ["No photo", "📷 Camera", "🖼 Upload"], horizontal=True)
        img = None
        if src == "📷 Camera":
            img = st.camera_input("Snap the thing you don't understand")
        elif src == "🖼 Upload":
            img = st.file_uploader("Upload a photo or screenshot", type=["png", "jpg", "jpeg"])
        go = st.button("🚀 Teach me", type="primary")
    if go:
        if not confusion.strip() and img is None:
            st.warning("Write what you don't understand, or add a photo.")
        elif build(confusion, subj, level, img):
            st.rerun()
    st.stop()

stages, n = D["stages"], len(D["stages"])
top1, top2 = st.columns([4, 1])
top1.subheader(f"🎯 {D['topic']}")
if top2.button("🆕 New lesson"):
    del st.session_state["dnu"]
    st.rerun()

st.info(f"**What's probably tripping you up:** {D['outline'].get('diagnosis', '')}")
g1, g2 = st.columns(2)
g1.markdown(f"**By the end you'll be able to:** {D['outline'].get('goal', '')}")
if D["outline"].get("prerequisites"):
    g2.markdown("**You should already know:** " + "; ".join(str(p) for p in D["outline"]["prerequisites"][:4]))

done = min(D["passed"], n)
st.progress(done / (n + 1), text=f"{done} of {n} steps passed" + (" · final test next" if done == n else ""))


def show_stage_visuals(i, s):
    if D["img"] and D["regions"] and s["pointer"]:
        if i not in D["ann"]:
            try:
                D["ann"][i] = visual.annotate(D["img"], D["regions"], s["pointer"])
            except Exception:
                D["ann"][i] = None
        if D["ann"][i]:
            labels = ", ".join(f"{r['id']}: {r['label']}" for r in D["regions"] if r["id"] in s["pointer"])
            st.image(D["ann"][i], caption=f"Look here → {labels}")
            return
    if s["visual"].get("type") != "image_points":
        visual.render(s["visual"], f"{D['id']}_{i}")


for i, s in enumerate(stages):
    if i < D["passed"]:
        with st.expander(f"✅ Step {i + 1}: {s['title']}", expanded=False):
            st.markdown(s["explain"])
            show_stage_visuals(i, s)
            st.success(f"Remember: {s['key_point']}")
        continue
    if i > D["passed"]:
        break

    st.markdown(f"### Step {i + 1} of {n}: {s['title']}")
    if D["alt"].get(i):
        st.markdown(D["alt"][i])
        with st.expander("Show the first explanation again"):
            st.markdown(s["explain"])
    else:
        st.markdown(s["explain"])
    show_stage_visuals(i, s)

    st.markdown("#### ✋ Prove it before moving on")
    chk = s["check"]
    pick = st.radio(chk["question"], chk["options"], index=None, key=f"dnu_{D['id']}_{i}")
    if st.button("Check my answer", type="primary", key=f"dnuchk_{D['id']}_{i}"):
        if pick is None:
            st.warning("Pick an answer first.")
        else:
            idx = chk["options"].index(pick)
            if idx == chk["answer"]:
                D["passed"] += 1
                D["fb"].pop(i, None)
                db.record_result(D["subject"], D["topic"], True)
                db.log_event("dnu_step", f"{D['topic']} {i + 1}/{n}")
                st.toast(f"✅ Correct! {s['key_point']}")
                st.rerun()
            else:
                D["tries"][i] = D["tries"].get(i, 0) + 1
                D["picks"].setdefault(i, []).append(pick)
                D["fb"][i] = f"❌ Not quite. {chk['why_wrong'][idx] or 'That is a common mix-up.'}"
                db.record_result(D["subject"], D["topic"], False)
    if D["fb"].get(i):
        st.error(D["fb"][i])
    if D["tries"].get(i, 0) >= 2 and not D["alt"].get(i):
        st.warning("Still not clicking? Let me explain it a different way.")
        if st.button("🔁 Explain it differently", key=f"dnualt_{D['id']}_{i}"):
            try:
                D["alt"][i] = st.write_stream(ai.dnu_reexplain_stream(s, D["source_text"], D["picks"].get(i, [])))
                D["fb"].pop(i, None)
                db.log_event("dnu_reexplain", D["topic"])
                st.rerun()
            except Exception as e:
                st.error(str(e))
    break

if D["passed"] < n:
    st.stop()

st.markdown("### 🏁 Final test: show you really got it")
if D["final"] is None:
    with st.spinner("Writing a fresh test..."):
        try:
            D["final"] = ai.dnu_final(D["ctx"])
        except Exception as e:
            st.error(f"Could not write the test: {e}")
            if st.button("Try again"):
                st.rerun()
            st.stop()

final = D["final"]
if not D["result"]:
    with st.form(f"final_{D['id']}"):
        answers = {}
        for j, q in enumerate(final):
            st.markdown(f"**{j + 1}. {q['question']}**")
            if q["type"] == "mcq":
                answers[j] = st.radio("Choose", q["options"], index=None, key=f"fin_{D['id']}_{j}", label_visibility="collapsed")
            else:
                answers[j] = st.text_area("Your answer", key=f"fin_{D['id']}_{j}", height=100, label_visibility="collapsed")
        submitted = st.form_submit_button("Submit the test", type="primary")
    if submitted:
        def grade(j):
            q, a = final[j], answers.get(j)
            if q["type"] == "mcq":
                ok = a is not None and q["options"].index(a) == q["answer"]
                return {"score": 1.0 if ok else 0.0, "feedback": q["why_right"], "answer": q["options"][q["answer"]]}
            try:
                r = ai.dnu_grade_short(q, a or "")
            except Exception as e:
                r = {"score": 0.0, "feedback": f"Grading failed: {e}", "missed": []}
            r["answer"] = q["model_answer"]
            return r
        with st.spinner("Marking your test..."):
            res = nim.parallel(grade, range(len(final)))
        score = sum(r["score"] for r in res) / len(res)
        D["result"] = {"score": score, "items": res, "answers": {j: answers.get(j) for j in range(len(final))}}
        db.log_event("dnu_done", f"{D['topic']} {score * 100:.0f}%")
        if score >= 0.75:
            db.record_result(D["subject"], D["topic"], True)
        else:
            for j, r in enumerate(res):
                if r["score"] < 0.6:
                    db.add_mistake(D["subject"], D["topic"], final[j]["question"], str(answers.get(j) or ""), r["answer"],
                                   r["feedback"], db.CATS[1], "", "dont_understand")
        if not D["cards_saved"]:
            for s in stages:
                if s["card"]["front"] and s["card"]["back"]:
                    db.add_card(D["subject"], D["topic"], s["card"]["front"], s["card"]["back"], "dont_understand")
            D["cards_saved"] = True
        st.rerun()
    st.stop()

R = D["result"]
score = R["score"]
st.metric("Your score", f"{score * 100:.0f}%")
if score >= 0.75:
    st.success("🎉 Mastered. You understand this now, and the key ideas are in your flashcards so it stays that way.")
    st.balloons()
else:
    st.warning("Not mastered yet, and that's useful to know. Your missed questions went into your mistake tracker. Redo the steps with a fresh test.")
for j, (q, r) in enumerate(zip(final, R["items"])):
    icon = "🟢" if r["score"] >= 0.75 else "🟠" if r["score"] >= 0.4 else "🔴"
    with st.expander(f"{icon} Question {j + 1}", expanded=r["score"] < 0.75):
        st.markdown(q["question"])
        st.write(f"**Your answer:** {R['answers'].get(j) or '(blank)'}")
        st.write(r["feedback"])
        st.caption(f"Model answer: {r['answer']}")
        if r["score"] < 0.75:
            ui.explain_box(f"{q['question']}\nCorrect: {r['answer']}", f"dnuq{D['id']}{j}", D["subject"])

b1, b2 = st.columns(2)
if b1.button("🔁 Redo the steps with a fresh test"):
    D.update({"id": uuid.uuid4().hex[:8], "passed": 0, "tries": {}, "picks": {}, "fb": {}, "alt": {}, "final": None, "result": None})
    st.rerun()
if b2.button("🆕 Start a new lesson"):
    del st.session_state["dnu"]
    st.rerun()
