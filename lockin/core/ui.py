import datetime as dt
import os
import streamlit as st
from core import db


def load_secrets():
    for name in ("NVIDIA_API_KEY", "NIM_TEXT_MODEL", "NIM_FAST_MODEL", "NIM_VISION_MODEL", "NIM_BASE_URL"):
        if os.getenv(name):
            continue
        try:
            if name in st.secrets:
                os.environ[name] = str(st.secrets[name])
        except Exception:
            pass


def setup(title, icon="🔒"):
    st.set_page_config(page_title=f"LockIn · {title}", page_icon=icon, layout="wide")
    load_secrets()
    db.init()
    with st.sidebar:
        st.markdown("### 🔒 LockIn")
        if not os.getenv("NVIDIA_API_KEY"):
            key = st.text_input("NVIDIA API key", type="password", help="Free key at build.nvidia.com")
            if key:
                os.environ["NVIDIA_API_KEY"] = key
        st.caption(f"Text: `{os.getenv('NIM_TEXT_MODEL', 'meta/llama-3.3-70b-instruct')}`")
        st.caption(f"Vision: `{os.getenv('NIM_VISION_MODEL', 'meta/llama-3.2-90b-vision-instruct')}`")
        st.caption(f"🔥 Streak: **{db.streak()}** days")
        with st.expander("💾 Backup / restore"):
            if db.DB.exists():
                st.download_button("Download backup", db.DB.read_bytes(), "lockin.db")
            up = st.file_uploader("Restore a backup", type=["db"], key="restore_up")
            if up and st.button("Restore now"):
                db.DB.write_bytes(up.getvalue())
                st.rerun()
    st.title(f"{icon} {title}")


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
