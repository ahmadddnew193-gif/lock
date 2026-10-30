import datetime as dt
import os
import streamlit as st
from core import ai, auth, db


def header(title, icon=""):
    st.title(f"{icon} {title}".strip())


def subject_picker(label="Subject", key="subj"):
    opts = db.subjects() + ["➕ New subject…"]
    pick = st.selectbox(label, opts, key=f"{key}_sel")
    if pick == "➕ New subject…":
        return st.text_input("New subject name", key=f"{key}_new").strip() or "General"
    return pick


def heatmap(minutes_by_day, weeks=16):
    today = dt.date.today()
    start = today - dt.timedelta(days=today.weekday()) - dt.timedelta(weeks=weeks - 1)

    def color(m):
        return ("#2d333b" if m == 0 else "#0e4429" if m < 30 else "#006d32" if m < 90
                else "#26a641" if m < 180 else "#39d353")
    cols = []
    for w in range(weeks):
        cells = []
        for d in range(7):
            day = start + dt.timedelta(weeks=w, days=d)
            if day > today:
                cells.append('<div style="width:16px;height:16px;margin-bottom:3px"></div>')
                continue
            m = minutes_by_day.get(day.isoformat(), 0)
            cells.append(f'<div title="{day}: {m} min" style="width:16px;height:16px;border-radius:3px;'
                         f'margin-bottom:3px;background:{color(m)}"></div>')
        cols.append('<div style="margin-right:3px">' + "".join(cells) + "</div>")
    st.markdown('<div style="display:flex">' + "".join(cols) + "</div>", unsafe_allow_html=True)


def _bump(text, key, subject, level):
    try:
        st.session_state[f"ou_{key}"] = ai.simplify(text, level, subject, st.session_state.get(f"at_{key}", ""))
        st.session_state[f"lv_{key}"] = level
        st.session_state.pop(f"er_{key}", None)
        db.log_event("simplify", subject)
    except Exception as e:
        st.session_state[f"er_{key}"] = str(e)


def explain_box(text, key, subject=""):
    lv = st.session_state.get(f"lv_{key}", 0)
    labels = ["🤔 I don't get this", "🧒 Still lost? Explain like I'm 10", "🪜 Baby steps, please"]
    if lv < 3:
        if lv == 0:
            st.text_area("Your best guess first (optional, but it makes it stick)", key=f"at_{key}", height=70)
        st.button(labels[lv], key=f"eb_{key}", on_click=_bump, args=(text, key, subject, lv + 1))
    if st.session_state.get(f"er_{key}"):
        st.error(st.session_state[f"er_{key}"])
    if st.session_state.get(f"ou_{key}"):
        st.info(st.session_state[f"ou_{key}"])


def principle():
    st.caption("🧠 Rule: AI should **challenge** your thinking, never **replace** it. Cognitive effort is what makes it stick.")


def map_builder(key, text, concepts=None, subject="", ref_dot=None):
    st.markdown("**Your turn: build the map yourself.** Making the links is the learning, so the AI's version stays locked until you try.")
    if concepts:
        st.caption("Concepts to connect: " + " · ".join(concepts))
    raw = st.text_area("Your links, one per line: `A | relationship | B`", key=f"mb_{key}", height=150,
                       placeholder="Current | is the rate of flow of | Charge\nVoltage | pushes | Current")
    nodes, edges = ai.parse_links(raw)
    if nodes:
        st.graphviz_chart(ai.to_dot(nodes, edges, "concept"))
    if st.button("🧐 Critique my map", key=f"mbc_{key}"):
        if len(edges) < 2:
            st.warning("Add at least two links first.")
        else:
            with st.spinner("Reviewing your map..."):
                try:
                    st.session_state[f"mbk_{key}"] = ai.critique_map(text, raw)
                    db.log_event("map", subject)
                except Exception as e:
                    st.error(e)
    c = st.session_state.get(f"mbk_{key}")
    if c:
        st.metric("Your map", f"{c.get('score', 0)}/10")
        for g in c.get("good", []):
            st.success(g)
        for w in c.get("wrong", []):
            st.error(f"{w.get('link', '')}: {w.get('why', '')}")
        for m in c.get("missing", []):
            st.warning(f"Think about: {m.get('hint', '')}  \n_{m.get('why', '')}_")
        if c.get("tip"):
            st.info(c["tip"])
        if st.button("👀 Reveal the AI's reference map", key=f"mbr_{key}"):
            try:
                if ref_dot:
                    st.session_state[f"mbd_{key}"] = ref_dot
                else:
                    n, e = ai.diagram(text, "concept")
                    st.session_state[f"mbd_{key}"] = ai.to_dot(n, e, "concept")
            except Exception as ex:
                st.error(ex)
    if st.session_state.get(f"mbd_{key}"):
        st.caption("AI reference map (compare it with yours and note what you missed):")
        st.graphviz_chart(st.session_state[f"mbd_{key}"])


def sidebar():
    u = auth.current()
    with st.sidebar:
        st.markdown(f"**{u['display_name']}**" + (" · 🛡️ admin" if auth.is_admin() else ""))
        st.caption(f"🔥 Streak: **{db.streak()}** days")
        with st.expander("🔑 Change password"):
            with st.form("chg_pw", clear_on_submit=True):
                a = st.text_input("New password", type="password")
                b = st.text_input("Repeat", type="password")
                if st.form_submit_button("Update") and u["role"] == "user":
                    ok, msg = auth.validate_pw(a, b)
                    if ok:
                        auth.change_password(u["id"], a)
                        st.success("Password updated.")
                    else:
                        st.error(msg)
            if u["role"] == "admin":
                st.caption("The admin password is the MASTER_KEY secret. Change it in Streamlit Settings → Secrets.")
        if st.button("Log out"):
            auth.logout()
            st.rerun()
        st.caption(f"Model: `{os.getenv('NIM_MODEL', 'nvidia/nemotron-3.5-super-vl-120b-a12b')}`")
