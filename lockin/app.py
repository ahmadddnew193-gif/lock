import streamlit as st

st.set_page_config(page_title="LockIn", page_icon="🔒", layout="wide")

from core import auth, config, db, ui

config.load_env()

try:
    db.init()
except Exception as e:
    st.error(f"Could not connect to the database: {e}")
    st.info("Check the DATABASE_URL secret. If the password has special characters, URL-encode them.")
    st.stop()

if not auth.logged_in():
    auth.login_screen()
    st.stop()

if auth.current().get("must_change"):
    auth.force_change_screen()
    st.stop()

pages = {
    "Study": [
        st.Page("views/dashboard.py", title="Command Center", icon=":material/dashboard:", default=True),
        st.Page("views/dont_understand.py", title="Don't Understand", icon=":material/help:"),
        st.Page("views/explain.py", title="Explain Simply", icon=":material/lightbulb:"),
        st.Page("views/teachback.py", title="Teach-Back Lab", icon=":material/science:"),
        st.Page("views/snap.py", title="Snap & Think", icon=":material/photo_camera:"),
        st.Page("views/flashcards.py", title="Flashcards", icon=":material/style:"),
        st.Page("views/mistakes.py", title="Mistakes", icon=":material/error:"),
    ],
    "Practice": [
        st.Page("views/strategist.py", title="Exam Strategist", icon=":material/flag:"),
        st.Page("views/sprint.py", title="Past Paper Sprint", icon=":material/timer:"),
        st.Page("views/exam.py", title="Weekly Exam", icon=":material/quiz:"),
    ],
    "Track": [
        st.Page("views/hub.py", title="Subject Hub", icon=":material/folder:"),
        st.Page("views/insights.py", title="Insights", icon=":material/bar_chart:"),
        st.Page("views/checkin.py", title="Sunday Check-in", icon=":material/task_alt:"),
    ],
}
if auth.is_admin():
    pages["Admin"] = [st.Page("views/admin.py", title="Admin Panel", icon=":material/shield:")]

nav = st.navigation(pages)
ui.sidebar()
nav.run()
