import pandas as pd
import streamlit as st
from core import db, nim, ui

ui.setup("Subject Hub", "🗂")
st.caption("Everything in one place → zero friction → no procrastination.")

q = st.text_input("🔎 Search everything (notes, mistakes, flashcards)")
if q:
    like = f"%{q}%"
    n = db.rows("SELECT subject,topic,body FROM notes WHERE body LIKE ? OR topic LIKE ?", (like, like))
    m = db.rows("SELECT subject,topic,question,correct_answer FROM mistakes WHERE question LIKE ? OR correct_answer LIKE ? OR topic LIKE ?", (like,) * 3)
    c = db.rows("SELECT subject,topic,front,back FROM cards WHERE front LIKE ? OR back LIKE ?", (like, like))
    st.write(f"**{len(n)}** notes · **{len(m)}** mistakes · **{len(c)}** cards")
    for r in n: st.markdown(f"🗒 **{r['subject']} / {r['topic']}**: {r['body'][:300]}")
    for r in m: st.markdown(f"❌ **{r['subject']} / {r['topic']}**: {r['question'][:200]}")
    for r in c: st.markdown(f"🃏 **{r['subject']} / {r['topic']}**: {r['front']} → {r['back']}")
    st.divider()

subj = ui.subject_picker("Subject", "hub")
t1, t2, t3, t4 = st.tabs(["📊 Overview", "🗒 Notes", "🧪 Topic tests", "📎 Scans"])

with t1:
    weak = db.weak_topics(20, subj)
    if weak:
        st.dataframe(pd.DataFrame(weak), hide_index=True)
    else:
        st.info("No open mistakes in this subject. Nice, or you haven't logged any yet.")
    sp = db.rows("SELECT created,paper,score_pct FROM sprints WHERE subject=? ORDER BY created", (subj.title(),))
    if sp:
        st.subheader("Past-paper trend")
        st.line_chart(pd.DataFrame(sp).set_index("created")["score_pct"])

with t2:
    with st.form("note", clear_on_submit=True):
        topic = st.text_input("Topic")
        body = st.text_area("Note", height=150)
        if st.form_submit_button("Save note") and body:
            db.run("INSERT INTO notes(created,subject,topic,body) VALUES(?,?,?,?)", (db.now(), subj.title(), topic.title(), body))
    for n in db.rows("SELECT * FROM notes WHERE subject=? ORDER BY created DESC", (subj.title(),)):
        with st.expander(f"{n['topic']} · {n['created'][:10]}"):
            st.write(n["body"])

with t3:
    with st.form("tt", clear_on_submit=True):
        topic = st.text_input("Topic tested")
        score = st.slider("Score %", 0, 100, 70)
        if st.form_submit_button("Log topic test") and topic:
            db.run("INSERT INTO topic_tests(created,subject,topic,score_pct) VALUES(?,?,?,?)", (db.now(), subj.title(), topic.title(), score))
    tt = db.rows("SELECT created,topic,score_pct FROM topic_tests WHERE subject=? ORDER BY created DESC", (subj.title(),))
    if tt:
        df = pd.DataFrame(tt)
        df["level"] = df.score_pct.apply(lambda s: "🟢" if s >= 80 else "🟠" if s >= 60 else "🔴")
        st.dataframe(df, hide_index=True)

with t4:
    up = st.file_uploader("Upload a scan of a marked exam / worksheet", type=["png", "jpg", "jpeg"])
    label = st.text_input("Label", placeholder="2024 Paper 2 (marked)")
    if up and st.button("Save scan"):
        db.run("INSERT INTO scans(created,subject,topic,label,mime,data) VALUES(?,?,?,?,?,?)",
               (db.now(), subj.title(), "", label, up.type, up.getvalue()))
        st.rerun()
    for s in db.rows("SELECT * FROM scans WHERE subject=? ORDER BY created DESC", (subj.title(),)):
        with st.expander(f"{s['label'] or 'scan'} · {s['created'][:10]}"):
            st.image(s["data"])
            if st.button("🤖 Extract my mistakes from this marked scan", key=f"x{s['id']}"):
                with st.spinner("Reading marks..."):
                    try:
                        out = nim.vision_json(
                            "You read marked student work. Find every question where marks were lost.\n"
                            'Return {"mistakes":[{"topic":str,"question":str,"correct_answer":str,'
                            '"reason":"why marks were lost",'
                            '"category":"didnt_know"|"didnt_recognise"|"silly"}]}',
                            "List the mistakes.", s["data"], s["mime"] or "image/jpeg")
                        cmap = {"didnt_know": db.CATS[0], "didnt_recognise": db.CATS[1], "silly": db.CATS[2]}
                        for x in out.get("mistakes", []):
                            db.add_mistake(subj, x.get("topic", "General"), x.get("question", ""), "",
                                           x.get("correct_answer", ""), x.get("reason", ""),
                                           cmap.get(x.get("category"), db.CATS[0]), s["label"] or "", "scan")
                        st.success(f"Logged {len(out.get('mistakes', []))} mistakes.")
                    except Exception as e:
                        st.error(e)
