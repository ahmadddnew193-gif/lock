import streamlit as st
from core import db, ui, viz

ui.header("Insights", "📊")
u = db.uid()
st.caption("See where you're strong, where you're leaking marks, and what's coming up.")


def show(fig, msg="Not enough data yet."):
    if fig:
        st.plotly_chart(fig)
    else:
        st.info(msg)


c1, c2 = st.columns(2)
with c1:
    show(viz.subject_radar(u), "Practice a few subjects to see your mastery radar.")
with c2:
    show(viz.mistake_causes(u), "Log mistakes to see why you lose marks.")

show(viz.topic_treemap(u), "Do some flashcards or retries to build your knowledge map.")

c3, c4 = st.columns(2)
with c3:
    show(viz.mastery_bars(u), "No topic accuracy yet.")
with c4:
    show(viz.forecast(u), "Add flashcards to see your review forecast.")

show(viz.retention(u), "Review some flashcards to see retention.")

c5, c6 = st.columns(2)
with c5:
    show(viz.study_by_subject(u), "Log study time to see the split.")
with c6:
    show(viz.study_daily(u), "Log study time to see your daily minutes.")

c7, c8 = st.columns(2)
with c7:
    show(viz.sprint_trend(u), "Log a past-paper sprint.")
with c8:
    show(viz.exam_trend(u), "Take a weekly exam.")
