import hashlib
import streamlit as st
from core import ai, db, nim, ui

ui.header("Explain Simply", "🧒")
st.caption("Paste anything you don't understand, or snap it. Get it in plain English, an analogy and tiny steps. Then go deeper in the Teach-Back Lab.")
ui.principle()

mode = st.radio("Source", ["✍️ Paste text", "📷 Photo", "🗒 From my notes"], horizontal=True)
subj = st.text_input("Subject (optional)", key="x_subj")
text, image = None, None

if mode.startswith("✍️"):
    text = st.text_area("What's confusing?", height=160, placeholder="Paste a paragraph, a question, a definition...")
elif mode.startswith("📷"):
    src = st.radio("Photo input", ["Camera", "Upload"], horizontal=True, key="x_src")
    img = st.camera_input("Snap it") if src == "Camera" else st.file_uploader("Upload", type=["png", "jpg", "jpeg"])
    if img:
        image = (img.getvalue(), img.type or "image/jpeg")
else:
    notes = db.rows("SELECT id,subject,topic,body FROM notes WHERE user_id=? ORDER BY created DESC LIMIT 50", (db.uid(),))
    if notes:
        pick = st.selectbox("Pick a note", notes, format_func=lambda n: f"{n['subject']} · {n['topic']} · {n['body'][:40]}")
        text = pick["body"]
    else:
        st.info("No notes yet. Add some in Subject Hub.")

if st.button("✨ Explain it", type="primary") and (text or image):
    with st.spinner("Breaking it down..."):
        try:
            pack = ai.explain_pack(text=text, image=image, subject=subj)
            st.session_state.xp = pack
            st.session_state.xp_src = text or f"{pack.get('title', '')}\n{pack.get('simple', '')}"
            st.session_state.xp_key = hashlib.md5(st.session_state.xp_src.encode()).hexdigest()[:8]
            st.session_state.xp_chat = []
            db.log_event("explain", subj or pack.get("title", ""))
        except Exception as e:
            st.error(f"Failed: {e}")

pack = st.session_state.get("xp")
if pack:
    key = st.session_state.xp_key
    st.success(f"**{pack.get('title', 'Explained')}**: {pack.get('one_line', '')}")
    t1, t2, t3, t4, t5, t6 = st.tabs(["🧒 Simple", "🔗 Analogy", "🪜 Steps", "🗺 Build a map", "⚠️ Traps", "✅ Check yourself"])

    with t1:
        st.markdown(pack.get("simple", ""))
        st.markdown("**Worked example**")
        st.markdown(pack.get("example", ""))
        st.divider()
        st.caption("Still not clicking? Keep pressing, each level is simpler.")
        ui.explain_box(st.session_state.xp_src, f"xp{key}", subj)

    with t2:
        st.markdown(pack.get("analogy", ""))

    with t3:
        for i, s in enumerate(pack.get("steps", []), 1):
            st.markdown(f"**{i}.** {s}")

    with t4:
        mm = pack.get("mind_map") or {}
        ref = ai.to_dot(mm.get("nodes", []), mm.get("edges", []), "mind") if mm.get("nodes") else None
        ui.map_builder(f"xp{key}", st.session_state.xp_src, subject=subj, ref_dot=ref)

    with t5:
        for t in pack.get("traps", []):
            st.warning(t)

    with t6:
        for i, qa in enumerate(pack.get("quick_check", []), 1):
            with st.expander(f"Q{i}. {qa['q']}"):
                st.text_area("Your answer", key=f"x_ans{i}", height=70)
                st.success(qa["a"])
        if st.button("🃏 Turn this into flashcards"):
            n = 0
            for qa in pack.get("quick_check", []):
                db.add_card(subj or "General", pack.get("title", "Explained"), qa["q"], qa["a"], "explain")
                n += 1
            db.add_card(subj or "General", pack.get("title", "Explained"), f"In one sentence: {pack.get('title', '')}?", pack.get("one_line", ""), "explain")
            st.success(f"Added {n + 1} cards.")

    st.divider()
    st.subheader("💬 Ask a follow-up")
    for m in st.session_state.xp_chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
    q = st.chat_input("Ask anything about this topic")
    if q:
        st.session_state.xp_chat.append({"role": "user", "content": q})
        sys = ("You are a patient tutor. Answer simply, with short sentences and concrete examples. "
               f"Material the student is studying:\n{st.session_state.xp_src[:3000]}")
        with st.spinner("Thinking..."):
            try:
                ans = nim.chat([{"role": "system", "content": sys}] + st.session_state.xp_chat[-8:], temperature=0.4, max_tokens=900)
            except Exception as e:
                ans = f"Sorry, that failed: {e}"
        st.session_state.xp_chat.append({"role": "assistant", "content": ans})
        db.log_event("explain_chat", subj)
        st.rerun()
