import urllib.parse
import streamlit as st
from core import ai, db, ui

ui.header("Teach-Back Lab", "🧪")
st.caption("Learn one topic in layers, then prove you understand it by compressing it, comparing it, and arguing with the AI.")
ui.principle()

tb = st.session_state.get("tb")

c1, c2 = st.columns([3, 1])
topic = c1.text_input("Topic", placeholder="e.g. electric current vs drift speed", key="tb_topic_in")
subj = c2.text_input("Subject", key="tb_subj_in")
if st.button("▶ Start at Level 1", type="primary") and topic.strip():
    with st.spinner("Level 1: foundations only..."):
        try:
            lesson = ai.depth_lesson(topic, 1)
            st.session_state.tb = {"topic": topic.strip(), "subject": subj.strip(), "lessons": [(1, "", lesson)], "chat": [], "claims": None, "check": None}
            db.log_event("teachback_start", topic)
            st.rerun()
        except Exception as e:
            st.error(f"Failed: {e}")

if not tb:
    st.info("Tip: you set the depth. Level 1 gives only definitions and key ideas so nothing confuses you. Go deeper when you're ready.")
    st.stop()

LEVEL_NAMES = {1: "Foundations", 2: "Mechanisms", 3: "Relationships", 4: "Application", 5: "Edge cases"}
st.subheader(f"1 · Depth ladder: {tb['topic']}")
for i, (lv, focus, text) in enumerate(tb["lessons"]):
    with st.expander(f"Level {lv}: {LEVEL_NAMES[lv]}" + (f" · focus: {focus}" if focus else ""), expanded=(i == len(tb["lessons"]) - 1)):
        st.markdown(text)
        ui.explain_box(text, f"tbl{i}", tb["subject"])

cur = tb["lessons"][-1][0]
if cur < 5:
    f1, f2 = st.columns([3, 1])
    focus = f1.text_input("Want to dig into one specific concept? (optional)", key="tb_focus")
    if f2.button(f"⬇ Go deeper (Level {cur + 1})"):
        known = "\n".join(t for _, _, t in tb["lessons"])[-1500:]
        with st.spinner(f"Level {cur + 1}..."):
            try:
                tb["lessons"].append((cur + 1, focus.strip(), ai.depth_lesson(tb["topic"], cur + 1, focus, known)))
                db.log_event("teachback_deeper", f"L{cur + 1}")
                st.rerun()
            except Exception as e:
                st.error(e)
else:
    st.success("You've reached the deepest level.")

context = "\n\n".join(t for _, _, t in tb["lessons"])

st.subheader("2 · Teach it back")
st.caption("Compress it into one line, then compare it to something. Wrong ideas get caught here, not in the exam.")
one = st.text_input("My one-line version", key="tb_one")
cmp_ = st.text_area("What is it similar to or different from? (analogy or comparison)", key="tb_cmp", height=80,
                    placeholder="Is current the same as speed? Does a bigger current mean faster charge?")
if st.button("🔍 Check my model") and one.strip():
    with st.spinner("Examining your model..."):
        try:
            tb["check"] = ai.teachback_verify(tb["topic"], context, one, cmp_)
            tb["show_better"] = False
            db.log_event("teachback", tb["topic"])
        except Exception as e:
            st.error(e)

chk = tb.get("check")
if chk:
    v = chk.get("verdict", "partly")
    {"correct": st.success, "partly": st.warning, "incorrect": st.error}.get(v, st.info)(f"Verdict: **{v}**")
    st.markdown(f"**What's right:** {chk.get('what_is_right', '')}")
    if chk.get("what_is_off"):
        st.markdown(f"**What's off:** {chk['what_is_off']}")
    if chk.get("assumption_check"):
        st.markdown(f"**Assumption to edit:** {chk['assumption_check']}")
    if chk.get("comparison_feedback"):
        st.markdown(f"**Your comparison:** {chk['comparison_feedback']}")
    st.info(f"🎯 Now answer this: {chk.get('probe', '')}")
    b1, b2 = st.columns(2)
    if b1.button("Show a better one-liner (try fixing yours first)"):
        tb["show_better"] = True
    if tb.get("show_better"):
        st.code(chk.get("better_one_liner", ""))
    if b2.button("🃏 Save my one-liner as a flashcard"):
        db.add_card(tb["subject"] or "General", tb["topic"], f"In one line: {tb['topic']}?", one, "teachback")
        st.success("Saved.")

st.subheader("3 · Argue back")
st.caption("Push back on the AI. Ask why it made an assumption. It must concede when you're right and defend when you're wrong.")
for m in tb["chat"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
msg = st.chat_input("Challenge it or ask a question")
if msg:
    tb["chat"].append({"role": "user", "content": msg})
    with st.spinner("Thinking..."):
        try:
            tb["chat"].append({"role": "assistant", "content": ai.debate(tb["topic"], context, tb["chat"])})
            db.log_event("debate", tb["topic"])
        except Exception as e:
            tb["chat"].append({"role": "assistant", "content": f"That failed: {e}"})
    st.rerun()

st.subheader("4 · Verify before you trust it")
st.caption("AI can sound certain and be wrong. Check anything specific against real sources.")
if st.button("📋 List claims worth double-checking"):
    with st.spinner("Scanning for risky claims..."):
        try:
            tb["claims"] = ai.verify_claims(context)
            db.log_event("verify", tb["topic"])
        except Exception as e:
            st.error(e)
for i, c in enumerate(tb.get("claims") or []):
    q = urllib.parse.quote_plus(c.get("query") or c.get("claim", ""))
    icon = {"high": "🟢", "medium": "🟠", "low": "🔴"}.get(c.get("confidence"), "⚪")
    with st.container(border=True):
        st.markdown(f"{icon} **{c.get('claim', '')}**  \n_{c.get('risk', '')}_")
        l1, l2, l3 = st.columns(3)
        l1.link_button("Consensus", f"https://consensus.app/search/?q={q}")
        l2.link_button("Google Scholar", f"https://scholar.google.com/scholar?q={q}")
        l3.link_button("PubMed", f"https://pubmed.ncbi.nlm.nih.gov/?term={q}")
if tb.get("claims"):
    st.caption("The confidence icons are the AI's own guess, not proof. Always read the actual studies.")
