import datetime as dt
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from core import db

PAL = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7", "#ec4899", "#84cc16"]
RYG = ["#ef4444", "#f59e0b", "#22c55e"]
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _df(sql, args=()):
    return pd.DataFrame(db.rows(sql, args))


def _style(fig, h=340):
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=50, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", y=-0.15), colorway=PAL)
    return fig


def _day_range(n):
    today = dt.date.today()
    return [(today - dt.timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def mastery_bars(u):
    d = _df("SELECT subject,topic,attempts,correct FROM topic_stats WHERE user_id=? AND attempts>0", (u,))
    if d.empty:
        return None
    d["acc"] = (d.correct / d.attempts * 100).round()
    d["label"] = d.subject + " · " + d.topic
    d = d.sort_values("acc").head(15)
    fig = px.bar(d, x="acc", y="label", orientation="h", color="acc", color_continuous_scale=RYG,
                 range_color=(0, 100), title="Weakest topics (accuracy %)", hover_data=["attempts"])
    fig.update_layout(coloraxis_showscale=False, yaxis_title=None, xaxis_title=None)
    fig.update_xaxes(range=[0, 100])
    return _style(fig, max(300, 60 + 30 * len(d)))


def subject_radar(u):
    d = _df("SELECT subject, SUM(attempts) a, SUM(correct) c FROM topic_stats WHERE user_id=? GROUP BY subject HAVING SUM(attempts)>0", (u,))
    if d.empty:
        return None
    d["acc"] = (d.c / d.a * 100).round()
    if len(d) < 3:
        fig = px.bar(d, x="subject", y="acc", title="Mastery by subject (%)", color="acc",
                     color_continuous_scale=RYG, range_color=(0, 100))
        fig.update_layout(coloraxis_showscale=False, xaxis_title=None, yaxis_title=None)
        return _style(fig)
    th = list(d.subject) + [d.subject.iloc[0]]
    r = list(d.acc) + [d.acc.iloc[0]]
    fig = go.Figure(go.Scatterpolar(r=r, theta=th, fill="toself", line_color=PAL[0]))
    fig.update_layout(title="Mastery radar (accuracy by subject)", polar=dict(radialaxis=dict(range=[0, 100])))
    return _style(fig)


def topic_treemap(u):
    d = _df("SELECT subject,topic,attempts,correct FROM topic_stats WHERE user_id=? AND attempts>0", (u,))
    if d.empty:
        return None
    d["acc"] = (d.correct / d.attempts * 100).round()
    fig = px.treemap(d, path=[px.Constant("All subjects"), "subject", "topic"], values="attempts", color="acc",
                     color_continuous_scale=RYG, range_color=(0, 100), title="Knowledge map (size = practice, colour = accuracy)")
    return _style(fig, 420)


def forecast(u, days=14):
    d = _df("SELECT due, COUNT(*) n FROM cards WHERE user_id=? GROUP BY due", (u,))
    if d.empty:
        return None
    today = dt.date.today()
    labels, counts = [], []
    for i in range(days):
        day = today + dt.timedelta(days=i)
        if i == 0:
            n = d[d.due <= day.isoformat()].n.sum()
        else:
            n = d[d.due == day.isoformat()].n.sum()
        labels.append(day.strftime("%a %d"))
        counts.append(int(n))
    fig = px.bar(x=labels, y=counts, title="Flashcards due (next 14 days)")
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    return _style(fig, 280)


def mistake_causes(u):
    d = _df("SELECT category, COUNT(*) n FROM mistakes WHERE user_id=? GROUP BY category", (u,))
    if d.empty:
        return None
    fig = px.pie(d, names="category", values="n", hole=0.55, title="Why you lose marks",
                 color_discrete_sequence=["#ef4444", "#f59e0b", "#6366f1"])
    return _style(fig, 320)


def study_by_subject(u, days=30):
    d = _df("SELECT subject, SUM(minutes) m FROM study_log WHERE user_id=? AND day>=? GROUP BY subject", (u, db.days_ago(days)))
    if d.empty:
        return None
    fig = px.pie(d, names="subject", values="m", hole=0.55, title=f"Study time by subject (last {days} days)")
    return _style(fig, 320)


def study_daily(u, days=30):
    d = _df("SELECT day, subject, SUM(minutes) m FROM study_log WHERE user_id=? AND day>=? GROUP BY day, subject", (u, db.days_ago(days)))
    if d.empty:
        return None
    fig = px.bar(d, x="day", y="m", color="subject", title="Daily study minutes")
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    fig.update_xaxes(range=[db.days_ago(days), db.today()])
    return _style(fig)


def retention(u, days=30):
    d = _df("SELECT substr(created,1,10) d, COUNT(*) n, SUM(ok) good FROM reviews WHERE user_id=? AND substr(created,1,10)>=? GROUP BY d",
            (u, db.days_ago(days)))
    if d.empty:
        return None
    d["acc"] = (d.good / d.n * 100).round()
    fig = go.Figure()
    fig.add_bar(x=d.d, y=d.n, name="Cards reviewed", marker_color="#c7d2fe")
    fig.add_scatter(x=d.d, y=d.acc, name="Accuracy %", yaxis="y2", line=dict(color="#22c55e", width=3))
    fig.update_layout(title="Flashcard volume and accuracy",
                      yaxis2=dict(overlaying="y", side="right", range=[0, 100], showgrid=False))
    return _style(fig)


def sprint_trend(u):
    d = _df("SELECT substr(created,1,10) d, subject, score_pct FROM sprints WHERE user_id=? ORDER BY created", (u,))
    if d.empty:
        return None
    fig = px.line(d, x="d", y="score_pct", color="subject", markers=True, title="Past-paper scores")
    fig.update_layout(xaxis_title=None, yaxis_title="%")
    fig.update_yaxes(range=[0, 100])
    return _style(fig)


def exam_trend(u):
    d = _df("SELECT substr(created,1,10) d, score FROM exams WHERE user_id=? AND taken=1 ORDER BY created", (u,))
    if d.empty:
        return None
    fig = px.line(d, x="d", y="score", markers=True, title="Weekly exam scores")
    fig.update_layout(xaxis_title=None, yaxis_title="%")
    fig.update_yaxes(range=[0, 100])
    return _style(fig, 280)


def _names():
    return {r["id"]: r["username"] for r in db.rows("SELECT id, username FROM users")}


def admin_dau(days=30):
    d = _df("SELECT user_id, substr(created,1,10) d FROM events WHERE kind<>'login' AND substr(created,1,10)>=?", (db.days_ago(days),))
    rng = _day_range(days)
    s = d.groupby("d").user_id.nunique() if not d.empty else pd.Series(dtype=int)
    vals = [int(s.get(x, 0)) for x in rng]
    fig = px.bar(x=rng, y=vals, title="Daily active students")
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    return _style(fig, 300)


def admin_events_kind(days=30):
    d = _df("SELECT substr(created,1,10) d, kind, COUNT(*) n FROM events WHERE kind<>'login' AND substr(created,1,10)>=? GROUP BY d, kind",
            (db.days_ago(days),))
    if d.empty:
        return None
    fig = px.bar(d, x="d", y="n", color="kind", title="What students are doing")
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    return _style(fig, 340)


def admin_user_activity(days=30):
    d = _df("SELECT user_id, COUNT(*) n FROM events WHERE kind<>'login' AND substr(created,1,10)>=? GROUP BY user_id", (db.days_ago(days),))
    if d.empty:
        return None
    names = _names()
    d["user"] = d.user_id.map(lambda x: names.get(x, str(x)))
    fig = px.bar(d.sort_values("n"), x="n", y="user", orientation="h", title=f"Actions per user (last {days} days)")
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    return _style(fig, max(260, 50 + 32 * len(d)))


def admin_study_users(days=30):
    d = _df("SELECT user_id, SUM(minutes) m FROM study_log WHERE day>=? GROUP BY user_id", (db.days_ago(days),))
    if d.empty:
        return None
    names = _names()
    d["user"] = d.user_id.map(lambda x: names.get(x, str(x)))
    d["hours"] = (d.m / 60).round(1)
    fig = px.bar(d.sort_values("hours"), x="hours", y="user", orientation="h", title=f"Study hours per user (last {days} days)")
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    return _style(fig, max(260, 50 + 32 * len(d)))


def admin_hour_heat(days=60):
    d = _df("SELECT created FROM events WHERE kind<>'login' AND substr(created,1,10)>=?", (db.days_ago(days),))
    if d.empty:
        return None
    t = pd.to_datetime(d.created)
    z = pd.DataFrame({"wd": t.dt.dayofweek, "h": t.dt.hour}).groupby(["wd", "h"]).size().unstack(fill_value=0)
    z = z.reindex(index=range(7), columns=range(24), fill_value=0)
    fig = go.Figure(go.Heatmap(z=z.values, x=list(range(24)), y=WD, colorscale="Viridis"))
    fig.update_layout(title="When students study (hour of day, server time)", yaxis=dict(autorange="reversed"))
    return _style(fig, 320)


def admin_signups():
    d = _df("SELECT substr(created,1,10) d FROM users WHERE role='user' ORDER BY created")
    if d.empty:
        return None
    s = d.groupby("d").size().cumsum()
    fig = px.line(x=s.index, y=s.values, markers=True, title="Total accounts over time")
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    return _style(fig, 280)


def admin_logins(days=30):
    d = _df("SELECT substr(created,1,10) d, ok, COUNT(*) n FROM login_log WHERE substr(created,1,10)>=? GROUP BY d, ok", (db.days_ago(days),))
    if d.empty:
        return None
    d["result"] = d.ok.map(lambda x: "success" if int(x) == 1 else "failed")
    fig = px.bar(d, x="d", y="n", color="result", title="Logins",
                 color_discrete_map={"success": "#22c55e", "failed": "#ef4444"})
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    return _style(fig, 280)


def admin_causes():
    d = _df("SELECT category, COUNT(*) n FROM mistakes GROUP BY category")
    if d.empty:
        return None
    fig = px.pie(d, names="category", values="n", hole=0.55, title="Why students lose marks (all users)",
                 color_discrete_sequence=["#ef4444", "#f59e0b", "#6366f1"])
    return _style(fig, 320)


def admin_weak_topics():
    d = _df("SELECT subject, topic, COUNT(*) n FROM mistakes WHERE resolved=0 GROUP BY subject, topic")
    if d.empty:
        return None
    d["label"] = d.subject + " · " + d.topic
    d = d.sort_values("n").tail(12)
    fig = px.bar(d, x="n", y="label", orientation="h", title="Most common open weak spots (all users)")
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    return _style(fig, max(280, 50 + 30 * len(d)))
