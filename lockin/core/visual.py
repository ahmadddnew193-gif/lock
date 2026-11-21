import ast
import io
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from core import ai

FUNCS = {"sin": np.sin, "cos": np.cos, "tan": np.tan, "exp": np.exp, "log": np.log, "ln": np.log,
         "log10": np.log10, "sqrt": np.sqrt, "abs": np.abs, "asin": np.arcsin, "acos": np.arccos,
         "atan": np.arctan, "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh}
CONSTS = {"pi": np.pi, "e": np.e}
BINOPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide, ast.Pow: np.power, ast.Mod: np.mod}
COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7"]


def _ev(n, x):
    if isinstance(n, ast.Expression):
        return _ev(n.body, x)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return float(n.value)
    if isinstance(n, ast.Name):
        if n.id == "x":
            return x
        if n.id in CONSTS:
            return CONSTS[n.id]
        raise ValueError("unknown name")
    if isinstance(n, ast.BinOp) and type(n.op) in BINOPS:
        return BINOPS[type(n.op)](_ev(n.left, x), _ev(n.right, x))
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        v = _ev(n.operand, x)
        return -v if isinstance(n.op, ast.USub) else v
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and len(n.args) == 1 and not n.keywords:
        return FUNCS[n.func.id](_ev(n.args[0], x))
    raise ValueError("unsupported expression")


def safe_eval(expr, x):
    expr = str(expr).strip().replace("^", "**")
    if not expr or len(expr) > 120:
        raise ValueError("bad expression")
    with np.errstate(all="ignore"):
        y = _ev(ast.parse(expr, mode="eval"), x)
        y = np.broadcast_to(np.asarray(y, dtype=float), x.shape).copy()
    y[~np.isfinite(y)] = np.nan
    return y


def chart(v):
    try:
        lo, hi = float(v.get("x_min", -10)), float(v.get("x_max", 10))
    except Exception:
        lo, hi = -10.0, 10.0
    if hi <= lo:
        lo, hi = -10.0, 10.0
    x = np.linspace(lo, hi, 300)
    fig = go.Figure()
    drawn = 0
    for i, s in enumerate(v.get("series", [])[:5]):
        try:
            if s.get("expr"):
                fig.add_scatter(x=x, y=safe_eval(s["expr"], x), mode="lines", name=str(s.get("name", s["expr"]))[:40],
                                line=dict(color=COLORS[i % len(COLORS)], width=3))
                drawn += 1
            elif s.get("x") and s.get("y") and len(s["x"]) == len(s["y"]):
                fig.add_scatter(x=s["x"], y=s["y"], mode="lines+markers", name=str(s.get("name", ""))[:40],
                                line=dict(color=COLORS[i % len(COLORS)], width=3))
                drawn += 1
        except Exception:
            continue
    if not drawn:
        return None
    fig.update_layout(title=str(v.get("title", ""))[:80], xaxis_title=str(v.get("x_label", "x"))[:40],
                      yaxis_title=str(v.get("y_label", "y"))[:40], height=340, margin=dict(l=10, r=10, t=50, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=-0.2))
    return fig


def flow_dot(nodes, active):
    def esc(s):
        return str(s).replace("\\", "").replace('"', "'").replace("\n", " ")[:60]
    lines = ["digraph G {", "rankdir=LR;", 'bgcolor="transparent";', "pad=0.3;", "nodesep=0.4;", "ranksep=0.5;",
             'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=13, margin="0.2,0.12"];',
             'edge [color="#94a3b8", arrowsize=0.8];']
    for i, n in enumerate(nodes):
        if i < active:
            style = 'fillcolor="#dcfce7", color="#22c55e", fontcolor="#14532d"'
        elif i == active:
            style = 'fillcolor="#4f46e5", color="#4f46e5", fontcolor="white", penwidth=3'
        else:
            style = 'fillcolor="#f1f5f9", color="#cbd5e1", fontcolor="#64748b"'
        lines.append(f'n{i} [label="{esc(n.get("label", ""))}", {style}];')
    for i in range(len(nodes) - 1):
        lines.append(f"n{i} -> n{i + 1};")
    lines.append("}")
    return "\n".join(lines)


def annotate(image_bytes, regions, focus_ids):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGBA")
    im.thumbnail((1400, 1400))
    w, h = im.size
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.load_default(size=max(14, w // 40))
    except TypeError:
        font = ImageFont.load_default()
    focus = {int(i) for i in focus_ids if str(i).lstrip("-").isdigit()}
    for r in regions:
        x1, y1, x2, y2 = [c / 1000 for c in r["box"]]
        box = (x1 * w, y1 * h, x2 * w, y2 * h)
        if r["id"] in focus:
            d.rectangle(box, fill=(79, 70, 229, 55), outline=(79, 70, 229, 255), width=max(3, w // 300))
            cx, cy, rad = box[0], box[1], max(12, w // 55)
            d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=(239, 68, 68, 255), outline=(255, 255, 255, 255), width=2)
            d.text((cx - rad * 0.35, cy - rad * 0.7), str(r["id"]), fill=(255, 255, 255, 255), font=font)
        else:
            d.rectangle(box, outline=(148, 163, 184, 140), width=1)
    out = Image.alpha_composite(im, overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def valid_regions(raw):
    out = []
    for r in raw or []:
        try:
            b = [float(c) for c in r["box"]][:4]
            if len(b) == 4 and all(0 <= c <= 1000 for c in b) and b[2] > b[0] and b[3] > b[1]:
                out.append({"id": int(r["id"]), "label": str(r.get("label", ""))[:60], "box": b})
        except Exception:
            continue
    return out[:10]


def render(v, key, image=None, regions=None):
    if not isinstance(v, dict):
        return
    t = v.get("type", "none")
    if t == "diagram":
        nodes, edges = v.get("nodes", []), v.get("edges", [])
        if nodes:
            st.graphviz_chart(ai.to_dot(nodes, edges, "mind" if v.get("kind") == "mind" else "concept"))
    elif t == "flow":
        nodes = [n for n in v.get("nodes", []) if isinstance(n, dict) and n.get("label")]
        if nodes:
            step = st.slider("Step through it", 1, len(nodes), 1, key=f"flow_{key}") - 1 if len(nodes) > 1 else 0
            st.graphviz_chart(flow_dot(nodes, step))
            st.markdown(f"**Step {step + 1}: {nodes[step].get('label', '')}**  \n{nodes[step].get('note', '')}")
    elif t == "chart":
        fig = chart(v)
        if fig is not None:
            st.plotly_chart(fig)
    elif t == "table":
        cols, rows_ = v.get("columns", []), v.get("rows", [])
        if cols and rows_:
            fixed = [(list(r) + [""] * len(cols))[:len(cols)] for r in rows_ if isinstance(r, (list, tuple))]
            st.dataframe(pd.DataFrame(fixed, columns=[str(c) for c in cols]), hide_index=True)
    elif t == "image_points" and image and regions:
        ids = v.get("regions", [])
        try:
            st.image(annotate(image, regions, ids), caption=str(v.get("caption", ""))[:200])
        except Exception:
            st.image(image)
