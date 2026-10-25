import streamlit as st
from core import ai, db, ui

ui.setup("Flashcards", "🃏")
st.caption("Learning happens here, in the background, daily. Studying then is just testing. Minimum: 1 session every day.")
t1, t2, t3 = st.tabs(["📖 Review", "✨ Generate with AI", "➕ Add / browse"])

with t1:
    if "queue" not in st.session_state:
        st.session_state.queue = [c["id"] for c in db.due_cards()]
        st.session_state.show = False
    q = st.session_state.queue
    if not q:
        st.success("🎉 All caught up for today. Streak protected.")
        if st.button("Reload queue"):
            del st.session_state["queue"]; st.rerun()
    else:
        card = db.rows("SELECT * FROM cards WHERE id=?", (q[0],))[0]
        st.progress(0.0, text=f"{len(q)} left · {card['subject']} / {card['topic']}")
        st.markdown(f"### {card['front']}")
        if not st.session_state.show:
            if st.button("Show answer", type="primary"):
                st.session_state.show = True; st.rerun()
        else:
            st.info(card["back"])
            cols = st.columns(4)
            for g, (label, col) in enumerate(zip(["❌ Again", "😬 Hard", "✅ Good", "⚡ Easy"], cols)):
                if col.button(label, key=f"g{g}"):
                    db.review_card(card, g)
                    q.pop(0)
                    if g == 0:
                        q.append(card["id"])
                    st.session_state.show = False
                    st.rerun()

with t2:
    subj = ui.subject_picker("Subject", "cg")
    topic = st.text_input("Topic")
    mat = st.text_area("Paste notes / textbook text", height=200)
    if st.button("Use my saved notes for this subject"):
        mat = "\n".join(n["body"] for n in db.rows("SELECT body FROM notes WHERE subject=?", (subj.title(),)))
        st.session_state.cg_mat = mat
    mat = mat or st.session_state.get("cg_mat", "")
    n = st.slider("Cards", 5, 25, 10)
    if mat and st.button("Generate", type="primary"):
        with st.spinner("NIM is writing cards..."):
            st.session_state.preview = ai.make_cards(mat, n)
    for c in st.session_state.get("preview", []):
        st.markdown(f"**Q:** {c['front']}  \n**A:** {c['back']}")
    if st.session_state.get("preview") and st.button("💾 Save all to deck"):
        for c in st.session_state.preview:
            db.add_card(subj, topic, c["front"], c["back"], "ai")
        st.session_state.preview = []
        st.success("Saved. They're due today.")

with t3:
    with st.form("card", clear_on_submit=True):
        subj = ui.subject_picker("Subject", "cm")
        topic = st.text_input("Topic ")
        f = st.text_input("Front"); b = st.text_input("Back")
        if st.form_submit_button("Add") and f and b:
            db.add_card(subj, topic, f, b)
    tot = db.rows("SELECT COUNT(*) n, SUM(lapses) l FROM cards")[0]
    st.caption(f"{tot['n']} cards in deck")
    for r in db.rows("SELECT subject,topic,front,back,interval,due FROM cards ORDER BY created DESC LIMIT 50"):
        st.markdown(f"`{r['subject']}/{r['topic']}` **{r['front']}** → {r['back']} _(next in {r['interval']}d, due {r['due']})_")
