import json
import random
import re
from core import nim

CARD_SYS = """You make high-quality Anki flashcards for exam prep.
Rules: one atomic fact per card, the question must be answerable from memory, no yes/no questions,
prefer 'why/how/what is the difference' over pure definitions when the material allows,
answers under 25 words. Return JSON: {"cards":[{"front":str,"back":str}]}"""


def make_cards(material, n=10):
    out = nim.chat_json(CARD_SYS, f"Make {n} cards from this material:\n{material[:6000]}", kind="fast", temperature=0.3)
    cards = out.get("cards", []) if isinstance(out, dict) else out
    return [c for c in cards if isinstance(c, dict) and c.get("front") and c.get("back")]


GRADE_SYS = """You grade a student's retry of a question they previously got wrong.
Return JSON: {"pass": true or false, "feedback": "1-2 sentences", "score": 0-10}.
Pass only if the core idea is correct."""


def grade_retry(question, correct, attempt):
    return nim.chat_json(GRADE_SYS, f"Question: {question}\nCorrect: {correct}\nStudent: {attempt or '(blank)'}", kind="fast")


LEVELS = {
    1: "Use plain English: short sentences, no jargon (put any unavoidable term in brackets with a 5-word meaning).",
    2: "Explain it to a curious 10-year-old using one vivid everyday analogy. Zero jargon.",
    3: "The student is an absolute beginner. Use tiny numbered baby steps, one idea per step, one concrete mini-example with real numbers or objects, then ask one check question and give its answer.",
}


def _simplify_messages(text, level, subject, attempt):
    system = ("You are the most patient tutor in the world. The student did NOT understand the text below. "
              + LEVELS[min(max(level, 1), 3)]
              + " Keep it under 160 words, use **bold** for key terms, and finish with one line starting 'Remember:'.")
    if attempt.strip():
        system += (" The student made their own attempt first. Start by naming what they got right, point out the one "
                   "misconception to fix, then build on their wording.")
    user = f"Subject: {subject or 'general'}\n\n{text[:4000]}"
    if attempt.strip():
        user += f"\n\nStudent's own attempt: {attempt.strip()[:600]}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def simplify(text, level=1, subject="", attempt=""):
    return nim.chat(_simplify_messages(text, level, subject, attempt), kind="teacher", temperature=0.4, max_tokens=700)


def simplify_stream(text, level=1, subject="", attempt=""):
    return nim.stream(_simplify_messages(text, level, subject, attempt), kind="teacher", temperature=0.4, max_tokens=700)


READ_SYS = """You are reading a photo of study material for a tutor. Transcribe faithfully. Do not solve or judge anything.
Return JSON: {"subject_guess": str, "topic_guess": str,
 "transcription": "all readable text and equations in order; write tables as rows separated by |",
 "visuals": "describe any diagram, graph or figure and what it shows, or an empty string"}"""


def read_image(image_bytes):
    out = nim.vision_json(READ_SYS, "Transcribe this page.", image_bytes)
    return out if isinstance(out, dict) else {"transcription": str(out)}


def image_to_text(image_bytes):
    r = read_image(image_bytes)
    parts = [str(r.get("transcription", "")).strip()]
    if r.get("visuals"):
        parts.append("[Figure: " + str(r["visuals"]).strip() + "]")
    return "\n".join(p for p in parts if p), r


REGIONS_SYS = READ_SYS.replace('"visuals"', '"visuals"') + """
Also add "regions": up to 8 key places a teacher would point at (equations, diagram parts, circled or highlighted text, graph features).
Each region: {"id": 1..8, "label": "max 6 words", "box": [x1, y1, x2, y2]} with integers from 0 to 1000,
where (0,0) is the top-left corner and (1000,1000) the bottom-right corner of the image."""


def read_image_regions(image_bytes):
    out = nim.vision_json(REGIONS_SYS, "Transcribe this page and mark the key regions.", image_bytes, max_tokens=3500)
    return out if isinstance(out, dict) else {"transcription": str(out), "regions": []}


EXPLAIN_SYS = """You are an exceptional teacher who makes hard material easy.
Return JSON:
{"title": str, "one_line": "the whole idea in one sentence",
 "simple": "plain-English explanation, max 120 words, no jargon",
 "analogy": "one vivid everyday analogy, max 80 words",
 "steps": ["tiny step", ...] (3 to 7 steps),
 "example": "one fully worked concrete mini-example",
 "traps": ["common mistake", ...] (2 to 4),
 "quick_check": [{"q": str, "a": str}] (exactly 3),
 "mind_map": {"nodes": [{"id": "a", "label": "max 5 words"}], "edges": [{"from": "a", "to": "b", "label": ""}]}}
The mind_map has ONE central node first, 4 to 7 branches, at most 2 leaves per branch."""


def explain_pack(text=None, image=None, subject=""):
    if image and not text:
        text, _ = image_to_text(image[0])
    return nim.chat_json(EXPLAIN_SYS, f"Subject: {subject or 'general'}\n{(text or '')[:6000]}", temperature=0.4, max_tokens=3500)


DIAGRAM_SYS = """You turn study material into a clear diagram.
Kinds: "mind" = one central idea with branches; "concept" = concepts linked by labelled relationships (verbs like causes, requires, is part of);
"flow" = an ordered process, first node is the start.
Return JSON: {"nodes":[{"id":"a","label":"max 5 words"}],"edges":[{"from":"a","to":"b","label":"max 3 words, may be empty"}]}
Use 6 to 12 nodes. Every node must be connected."""


def diagram(text, kind="concept"):
    out = nim.chat_json(DIAGRAM_SYS, f"Kind: {kind}\nMaterial:\n{text[:5000]}", temperature=0.3, max_tokens=1800)
    return out.get("nodes", []), out.get("edges", [])


def _esc(s):
    return str(s).replace("\\", "").replace('"', "'").replace("\n", " ")[:60]


def to_dot(nodes, edges, kind="mind"):
    nodes = [n for n in nodes if isinstance(n, dict) and n.get("label")]
    ids = {str(n.get("id", i)): f"n{i}" for i, n in enumerate(nodes)}
    rank = "LR" if kind == "mind" else "TB"
    lines = [
        "digraph G {", f"rankdir={rank};", 'bgcolor="transparent";', "pad=0.3;", "nodesep=0.35;", "ranksep=0.55;",
        'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=13, margin="0.2,0.12", '
        'color="#6366f1", fillcolor="#eef2ff", fontcolor="#1e1b4b"];',
        'edge [color="#94a3b8", fontname="Helvetica", fontsize=10, fontcolor="#94a3b8", arrowsize=0.7];',
    ]
    for i, n in enumerate(nodes):
        nid = ids[str(n.get("id", i))]
        extra = ""
        if i == 0 and kind in ("mind", "flow"):
            extra = ', fillcolor="#4f46e5", fontcolor="white", color="#4f46e5", fontsize=15'
        lines.append(f'{nid} [label="{_esc(n["label"])}"{extra}];')
    for e in edges:
        if not isinstance(e, dict):
            continue
        a, b = ids.get(str(e.get("from"))), ids.get(str(e.get("to")))
        if a and b:
            lab = _esc(e.get("label", "")) if e.get("label") else ""
            lines.append(f'{a} -> {b} [label="{lab}"];')
    lines.append("}")
    return "\n".join(lines)


def concept_map_dot(snap):
    nodes = [{"id": c["name"], "label": c["name"]} for c in snap.get("concepts", [])]
    known = {n["id"] for n in nodes}
    edges = []
    for q in snap.get("lock_in_questions", []):
        a, b = (q.get("between") or [None, None])[:2]
        for x in (a, b):
            if x and x not in known:
                nodes.append({"id": x, "label": x})
                known.add(x)
        if a and b:
            edges.append({"from": a, "to": b, "label": "links"})
    return to_dot(nodes, edges, "concept")


DEPTH = {
    1: "LEVEL 1, FOUNDATIONS ONLY: just the definitions and the key ideas. No mechanisms, no exceptions, no edge cases, nothing extra, so the student does not get confused.",
    2: "LEVEL 2, MECHANISMS: how and why it works, the main process step by step. Still no exceptions.",
    3: "LEVEL 3, RELATIONSHIPS: how it connects to neighbouring concepts, what it is easily confused with, and the key differences.",
    4: "LEVEL 4, APPLICATION: how it is used or tested in practice, one worked example, typical exam question styles.",
    5: "LEVEL 5, EDGE CASES: exceptions, limits, advanced details and misconceptions even good students hold.",
}


def _depth_messages(topic, level, focus, known):
    system = ("You are a world-class tutor teaching one topic in increasing levels of difficulty, at the pace the student sets. "
              + DEPTH[min(max(level, 1), 5)]
              + " Maximum 220 words, short bullets, **bold** key terms. End with two 'Check yourself' questions WITHOUT answers. "
                "If you are not fully certain of a fact, add (verify) right after it. Never invent statistics or citations.")
    user = (f"Topic: {topic}\nWhat the student already understands: {known or 'nothing yet'}\n"
            f"Go deeper on this specific part (if any): {focus or 'the whole topic'}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def depth_lesson(topic, level, focus="", known=""):
    return nim.chat(_depth_messages(topic, level, focus, known), kind="teacher", temperature=0.3, max_tokens=800)


def depth_lesson_stream(topic, level, focus="", known=""):
    return nim.stream(_depth_messages(topic, level, focus, known), kind="teacher", temperature=0.3, max_tokens=800)


TEACHBACK_SYS = """You are a rigorous but encouraging examiner. The student compressed a topic into ONE line and compared it to something else.
Do NOT flatter. Do NOT do their thinking for them: give critique and a hint, not a rewrite.
Return JSON:
{"verdict": "correct" | "partly" | "incorrect",
 "what_is_right": "1-2 sentences",
 "what_is_off": "1-2 sentences, or empty if nothing",
 "assumption_check": "the hidden assumption in their mental model that should be edited, or empty",
 "comparison_feedback": "is their comparison/analogy valid? where does it break down?",
 "probe": "one hard follow-up question that tests whether the model really works",
 "better_one_liner": "an improved one-line version (the student will only see this if they ask)"}"""


def teachback_verify(topic, lesson_context, one_liner, comparison):
    return nim.chat_json(TEACHBACK_SYS,
                         f"Topic: {topic}\nMaterial the student learned:\n{lesson_context[:3000]}\n\n"
                         f"Student's one-line version: {one_liner}\nStudent's comparison or analogy: {comparison or '(none given)'}",
                         temperature=0.2, max_tokens=1200)


DEBATE_SYS = """You are a sparring partner for a student testing their understanding. The student may push back.
If they are right, concede explicitly and say what changes in the picture. If they are wrong, defend with reasoning and one concrete example.
Never agree just to be pleasant. If you are unsure, say so and say how to check. Under 120 words. End with one probing question.
Topic and material:
"""


def debate_stream(topic, context, history):
    msgs = [{"role": "system", "content": DEBATE_SYS + f"{topic}\n{context[:2500]}"}] + history[-10:]
    return nim.stream(msgs, kind="teacher", temperature=0.4, max_tokens=600)


VERIFY_SYS = """List the 3-6 factual claims in this material that a student should double-check against real sources before trusting,
prioritising anything specific (numbers, guidelines, thresholds, named findings, exceptions) over common knowledge.
Return JSON: {"claims":[{"claim": str, "confidence": "high"|"medium"|"low", "risk": "why it could be wrong", "query": "a good search query for a scholarly search engine"}]}
Your confidence is only an estimate. Never invent citations or links."""


def verify_claims(text):
    out = nim.chat_json(VERIFY_SYS, text[:5000], temperature=0.2, max_tokens=1500)
    return out.get("claims", []) if isinstance(out, dict) else out


def parse_links(raw):
    nodes, edges, seen = [], [], {}

    def nid(name):
        k = name.strip()
        if k not in seen:
            seen[k] = f"c{len(seen)}"
            nodes.append({"id": seen[k], "label": k})
        return seen[k]
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3 and "->" in line:
            parts = [p.strip() for p in line.split("->")]
            if len(parts) == 2:
                parts = [parts[0], "", parts[1]]
        if len(parts) >= 3 and parts[0] and parts[2]:
            edges.append({"from": nid(parts[0]), "to": nid(parts[2]), "label": parts[1]})
        elif len(parts) == 1 and parts[0]:
            nid(parts[0])
    return nodes, edges


CRITIQUE_SYS = """You review a student's self-made concept map. The act of making links is the learning, so do not just hand over a finished map.
Return JSON: {"score": 0-10, "good": ["links that are correct and insightful"],
 "wrong": [{"link": "A -> B", "why": "what is wrong or misleading"}],
 "missing": [{"hint": "a pair of ideas that should be linked, phrased as a hint question", "why": "why it matters"}],
 "tip": "one sentence on how to improve the map"}"""


def critique_map(text, raw_links):
    return nim.chat_json(CRITIQUE_SYS, f"Source material:\n{text[:4000]}\n\nStudent's links (A | relationship | B):\n{raw_links[:2000]}",
                         temperature=0.2, max_tokens=1500)


CLASSIFY_SYS = """Assign each numbered exam question to exactly ONE topic. Use short, consistent topic names (2-4 words), reuse
existing names when they fit, and merge near-duplicates. Return JSON: {"topics":[{"i": int, "topic": str}]}"""


def classify_questions(lines, hint_topics=None, chunk=50):
    known = list(hint_topics or [])
    result = {}
    for start in range(0, len(lines), chunk):
        part = lines[start:start + chunk]
        numbered = "\n".join(f"{start + i}. {q[:300]}" for i, q in enumerate(part))
        out = nim.chat_json(CLASSIFY_SYS, f"Existing topic names: {known[:60]}\n\nQuestions:\n{numbered}", kind="fast", temperature=0.1, max_tokens=3000)
        for x in (out.get("topics", []) if isinstance(out, dict) else out):
            try:
                name = str(x["topic"]).strip().title()[:60]
                result[int(x["i"])] = name
                if name not in known:
                    known.append(name)
            except Exception:
                continue
    return result


STRATEGY_SYS = """You are an elite exam strategist. The goal is not to know everything equally well, it is to make the smartest possible
decision about where the next hour goes. Using the topic frequency tally from past exams, the syllabus, the student's weak topics and
their time budget, return JSON:
{"headline": "one-sentence strategy",
 "patterns": ["patterns in how the exam tests things, e.g. what repeats, whether it tests niche diseases or details of common things"],
 "priorities": [{"rank": 1, "topic": str, "frequency": int, "yield": "high"|"medium"|"low", "why": str, "hours": number, "how": "what to actually do, e.g. memorise a fixed set, drill the repeating station"}],
 "skip": [{"topic": str, "why": str}],
 "memorise_sets": ["fixed lists or sets that repeat and are worth memorising outright"],
 "schedule": [{"when": "e.g. Days 1-3", "focus": str}],
 "risks": ["what could go wrong with this plan"]}
Total hours across priorities must not exceed the budget. Order priorities exactly in the order the student should study them.
Be honest that skipping is a calculated risk and keep the plan evidence-based on the tally."""


def strategy(exam, tally, syllabus, days_left, hours_per_day, weak):
    payload = json.dumps({"exam": exam, "days_left": days_left, "hours_per_day": hours_per_day,
                          "total_hours_budget": round(days_left * hours_per_day, 1),
                          "frequency_tally": tally, "syllabus_topics": syllabus[:120], "student_weak_topics": weak})
    return nim.chat_json(STRATEGY_SYS, payload, temperature=0.3, max_tokens=4000)


PAPER_SYS = """You are reading a photo or scan of a student's exam paper or worksheet. Your job is TRANSCRIPTION, not judging.
Return JSON:
{"has_teacher_marks": true or false,
 "questions": [{"ref": "4a", "question": "short text of the question", "student_answer": "what the student wrote, short",
   "marks_awarded": number or null, "marks_available": number or null,
   "teacher_mark": "tick" | "cross" | "partial" | "none" | "unclear",
   "teacher_comment": "any written correction or comment, else empty string"}],
 "unreadable_parts": "what you could not read, else empty string"}
Rules: list only questions that are really visible. Never invent anything. marks_awarded and marks_available must come from numbers
you can actually see (like 2/3 or a circled score), otherwise null. If there are no ticks, crosses, scores or comments anywhere,
set has_teacher_marks to false and every teacher_mark to "none"."""

AUDIT_SYS = """Look ONLY at the marker's pen marks on this paper: ticks, crosses, circled or underlined errors, red corrections, written scores
such as 1/3, and short comments. Do not judge the student's answers yourself and do not solve anything.
Return JSON: {"mark_style": "what marking you see, for example red pen crosses, ticks only, scores in the margin, or none",
 "marks": [{"ref": "the question number nearest the mark, like 4a", "kind": "tick" | "cross" | "partial" | "score" | "correction" | "comment",
   "score_text": "for example 1/3, else empty", "comment": "short, else empty",
   "loss": true if this mark shows marks were lost (a cross, partial credit, a score below full marks, a correction), false for a tick or full marks}]}
If there is no marking at all, return {"mark_style": "none", "marks": []}."""

ENRICH_SYS = """You are a teacher. These questions are CONFIRMED to have lost marks. Do not add, remove or doubt any.
For each one explain it. Return JSON: {"subject": str, "items": [{"ref": str, "topic": "2-4 words",
 "correct_answer": "the correct answer or method, concise", "reason": "why this student lost the marks, from their answer and any marker comment",
 "category": "didnt_know" | "didnt_recognise" | "silly"}]}"""

JUDGE_SYS = """The paper has NO marker's marks. Solve each question yourself and compare with the student's answer.
List ONLY questions where the student's answer is wrong. Mark confidence "sure" only if you are certain, otherwise "likely".
If the student says they expect at most N mistakes, never list more than N. Return JSON: {"subject": str, "items": [{"ref": str, "topic": "2-4 words",
 "correct_answer": str, "reason": str, "category": "didnt_know" | "didnt_recognise" | "silly", "confidence": "sure" | "likely",
 "evidence": "exactly what is wrong in the student's answer"}]}"""


def _num(v):
    try:
        return float(v) if v is not None and str(v).strip() != "" else None
    except Exception:
        return None


def _key(ref):
    s = str(ref).lower().replace("question", "").strip()
    return re.sub(r"[^a-z0-9]", "", s.lstrip("q"))


def _fraction(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", str(text or ""))
    return (float(m.group(1)), float(m.group(2))) if m else None


def _transcript_flags(qs):
    out = {}
    for q in qs:
        aw, av = _num(q.get("marks_awarded")), _num(q.get("marks_available"))
        tm = str(q.get("teacher_mark", "none")).lower()
        if aw is not None and av is not None and aw < av:
            strength, ev = 2, f"{aw:g}/{av:g} marks"
        elif tm in ("cross", "partial"):
            strength, ev = 1, f"marked '{tm}'"
        else:
            continue
        if q.get("teacher_comment"):
            ev += f", comment: {q['teacher_comment']}"
        out[_key(q["ref"])] = {"ref": q["ref"], "strength": strength, "evidence": ev}
    return out


def _audit_flags(audit):
    out = {}
    for m in (audit.get("marks", []) if isinstance(audit, dict) else []):
        if not isinstance(m, dict) or not m.get("ref") or not m.get("loss"):
            continue
        frac = _fraction(m.get("score_text"))
        real = bool(frac and frac[0] < frac[1])
        ev = f"{m.get('score_text')} marks" if real else f"marker's {m.get('kind', 'mark')}"
        if m.get("comment"):
            ev += f", comment: {m['comment']}"
        out[_key(m["ref"])] = {"ref": str(m["ref"]), "strength": 2 if real else 1, "evidence": ev}
    return out


def enrich_items(items):
    if not items:
        return []
    payload = [{k: it.get(k, "") for k in ("ref", "question", "student_answer", "evidence")} for it in items]
    out = nim.chat_json(ENRICH_SYS, json.dumps({"questions": payload}), temperature=0.2, max_tokens=2500)
    info = {str(i.get("ref")): i for i in (out.get("items", []) if isinstance(out, dict) else out) if isinstance(i, dict)}
    subject = str(out.get("subject", "")) if isinstance(out, dict) else ""
    res = []
    for it in items:
        e = info.get(str(it["ref"]), {})
        res.append({**it, "topic": e.get("topic") or "General", "correct_answer": e.get("correct_answer", ""),
                    "reason": e.get("reason", it.get("evidence", "")), "category": e.get("category", "didnt_know"), "subject": subject})
    return res


def _read_paper(image_bytes, task):
    kind, model = task
    try:
        if kind == "read":
            out = nim.vision_json(PAPER_SYS, "Transcribe this paper.", image_bytes, models=[model], max_tokens=4000, max_side=2200)
        else:
            out = nim.vision_json(AUDIT_SYS, "List every marker's pen mark.", image_bytes, models=[model], max_tokens=2500, max_side=2200)
        return kind, model, out, None
    except Exception as e:
        return kind, model, None, str(e)[:200]


def extract_paper(image_bytes, expected=None, models=None):
    models = list(models or nim.chain("vision")[:2])
    tasks = [(k, m) for m in models for k in ("read", "audit")]
    results = nim.parallel(lambda t: _read_paper(image_bytes, t), tasks, workers=len(tasks))
    notes, transcripts, flags, any_marks, unreadable = [], [], [], False, ""
    for kind, model, out, err in results:
        name = model.split("/")[-1]
        if err:
            notes.append(f"{name} ({kind}) failed: {err}")
            continue
        if kind == "read":
            if isinstance(out, list):
                out = {"questions": out}
            qs = [q for q in out.get("questions", []) if isinstance(q, dict)]
            for i, q in enumerate(qs):
                q["ref"] = str(q.get("ref") or f"Q{i + 1}")
            transcripts.append((name, qs))
            flags.append((f"{name} read", _transcript_flags(qs)))
            any_marks = any_marks or bool(out.get("has_teacher_marks"))
            unreadable = unreadable or str(out.get("unreadable_parts", ""))
        else:
            audit = out if isinstance(out, dict) else {}
            any_marks = any_marks or bool(audit.get("marks"))
            flags.append((f"{name} audit", _audit_flags(audit)))
    if not transcripts:
        raise RuntimeError("No vision model could read the page. " + " | ".join(notes))
    best_name, qs = max(transcripts, key=lambda t: len(t[1]))
    by_key = {_key(q["ref"]): q for q in qs}
    votes = {}
    for src, fl in flags:
        for k, v in fl.items():
            e = votes.setdefault(k, {"ref": v["ref"], "strength": 0, "evidence": [], "sources": []})
            e["strength"] = max(e["strength"], v["strength"])
            e["sources"].append(src)
            e["evidence"].append(v["evidence"])
    marked = any_marks or bool(votes)
    items, subject, all_full = [], "", False
    if marked:
        cands = []
        for k, e in votes.items():
            q = by_key.get(k, {})
            cands.append({"ref": e["ref"], "question": q.get("question", ""), "student_answer": q.get("student_answer", ""),
                          "evidence": "; ".join(dict.fromkeys(e["evidence"])),
                          "confidence": "high" if len(e["sources"]) >= 2 or e["strength"] == 2 else "medium",
                          "agreement": f"{len(e['sources'])} of {len(flags)} checks"})
        cands.sort(key=lambda c: (c["confidence"] != "high", c["ref"]))
        items = enrich_items(cands)
        subject = next((i["subject"] for i in items if i.get("subject")), "")
        all_full = not items
    elif qs:
        payload = {"questions": [{k: q.get(k, "") for k in ("ref", "question", "student_answer")} for q in qs],
                   "student_expects_at_most": expected}
        out = nim.chat_json(JUDGE_SYS, json.dumps(payload), temperature=0.1, max_tokens=2500)
        subject = str(out.get("subject", "")) if isinstance(out, dict) else ""
        for it in (out.get("items", []) if isinstance(out, dict) else out):
            if isinstance(it, dict) and it.get("ref"):
                q = by_key.get(_key(it["ref"]), {})
                items.append({"ref": str(it["ref"]), "question": q.get("question", ""), "student_answer": q.get("student_answer", ""),
                              "evidence": it.get("evidence", ""), "confidence": "high" if it.get("confidence") == "sure" else "medium",
                              "agreement": "AI judged", "topic": it.get("topic") or "General", "correct_answer": it.get("correct_answer", ""),
                              "reason": it.get("reason", ""), "category": it.get("category", "didnt_know")})
        if expected:
            items = sorted(items, key=lambda x: x["confidence"] != "high")[:int(expected)]
    return {"marked": marked, "all_full": all_full, "subject": subject, "transcript": qs, "items": items, "unreadable": unreadable,
            "models": [m.split("/")[-1] for m in models], "read_by": best_name, "notes": notes}


def vision_bakeoff(image_bytes, models):
    import time

    def one(m):
        t = time.time()
        try:
            out = nim.vision_json(PAPER_SYS, "Transcribe this paper.", image_bytes, models=[m], max_tokens=4000, max_side=2200)
            if isinstance(out, list):
                out = {"questions": out}
            qs = [q for q in out.get("questions", []) if isinstance(q, dict)]
            for i, q in enumerate(qs):
                q["ref"] = str(q.get("ref") or f"Q{i + 1}")
            fl = _transcript_flags(qs)
            seen = sum(1 for q in qs if _num(q.get("marks_awarded")) is not None or str(q.get("teacher_mark", "none")).lower() not in ("none", "unclear", ""))
            return {"model": m, "works": "✅", "seconds": round(time.time() - t, 1), "questions read": len(qs),
                    "with marks seen": seen, "lost marks flagged": len(fl), "refs flagged": ", ".join(v["ref"] for v in fl.values()), "error": ""}
        except Exception as e:
            return {"model": m, "works": "❌", "seconds": round(time.time() - t, 1), "questions read": 0,
                    "with marks seen": 0, "lost marks flagged": 0, "refs flagged": "", "error": str(e)[:160]}
    return nim.parallel(one, list(models), workers=len(models))


OUTLINE_SYS = """You are an expert teacher who can make any topic click. The student says they do NOT understand something.
Return JSON:
{"topic": str, "subject": str,
 "diagnosis": "1-2 plain sentences naming the most likely misunderstanding",
 "prerequisites": ["short idea the student must already have"],
 "goal": "what the student will be able to do at the end",
 "stages": [{"title": str, "focus": "the single idea of this stage", "visual": "diagram" | "flow" | "chart" | "table" | "image_points" | "none", "regions": [ids of image regions to point at, or empty]}]}
Use 3 to 5 stages, from the simplest foundation up to the full picture. Choose the visual that shows each idea best: "flow" for processes,
"diagram" for relationships, "chart" for anything with numbers, functions or graphs, "table" for comparisons, "image_points" only when
image regions are provided. Respect the student's level."""

STAGE_SYS = """You are an expert teacher writing ONE stage of a lesson that makes a confusing topic click. Stay on this stage's single idea.
Return JSON:
{"explain": "markdown, max 130 words, plain words, one idea, uses a concrete example or analogy, **bold** key terms",
 "key_point": "one sentence the student must remember",
 "visual": VISUAL,
 "check": {"question": "tests UNDERSTANDING of this stage, not wording recall", "options": ["4 plain strings, no letter prefixes"],
           "answer": index 0-3 of the correct option, "why_right": "1-2 sentences",
           "why_wrong": ["for each option, a short reason it is wrong (a real misconception), empty string for the correct one"]},
 "card": {"front": "a flashcard question", "back": "short answer"}}
VISUAL is exactly one of:
 {"type":"diagram","kind":"mind" or "concept","nodes":[{"id":"a","label":"max 5 words"}],"edges":[{"from":"a","to":"b","label":"max 3 words"}]}
 {"type":"flow","nodes":[{"id":"a","label":"max 5 words","note":"what happens in this step, one sentence"}]} (3 to 7 ordered steps)
 {"type":"chart","title":str,"x_label":str,"y_label":str,"x_min":number,"x_max":number,"series":[{"name":str,"expr":"formula in x using + - * / ** sin cos tan exp log sqrt abs pi e"}]}
 {"type":"table","columns":[str],"rows":[[str]]}
 {"type":"image_points","regions":[ids],"caption":"what to look at"}
 {"type":"none"}
Use the visual type the outline asked for. The wrong options in the check must be plausible."""

FINAL_SYS = """You write the FINAL mastery test for a lesson. It must show whether the student truly understands, so use NEW situations, not the stage checks.
Return JSON: {"questions": [
 {"type":"mcq","question":str,"options":["4 plain strings"],"answer":0-3,"why_right":str},
 {"type":"mcq","question":str,"options":["4 plain strings"],"answer":0-3,"why_right":str},
 {"type":"apply","question":"a new problem that needs the idea applied","model_answer":str,"rubric":["2-4 points a good answer contains"]},
 {"type":"teach","question":"Explain the idea in your own words to a friend who has never seen it","model_answer":str,"rubric":["3-4 points"]}]}"""

GRADE_SHORT_SYS = """You grade a short answer against a rubric, strictly but kindly.
Return JSON: {"score": number from 0 to 1, "feedback": "1-2 sentences", "missed": ["rubric points the answer lacked"]}"""

REEXPLAIN_SYS = """The student got a check question wrong, so your first explanation did not land. Explain the SAME idea a completely different way:
a new analogy or example, different wording, even simpler. Under 120 words, **bold** key terms. Address the specific misconception they showed.
Finish with one line starting 'Remember:'."""


def dnu_outline(confusion, subject, level, source_text, region_labels):
    payload = {"student_says": confusion, "subject": subject, "student_level": level,
               "material_from_photo": source_text[:3500], "image_regions": region_labels}
    out = nim.chat_json(OUTLINE_SYS, json.dumps(payload), temperature=0.3, max_tokens=1400)
    stages = [s for s in out.get("stages", []) if isinstance(s, dict) and s.get("title")][:5]
    if len(stages) < 2:
        raise ValueError("The lesson plan came back too short.")
    out["stages"] = stages
    return out


def fix_check(c, seed=0):
    if not isinstance(c, dict) or not c.get("question"):
        return None
    opts = [re.sub(r"^\s*[A-Da-d][\).:]\s+", "", str(o).strip()) for o in c.get("options", []) if str(o).strip()][:4]
    if len(opts) < 2:
        return None
    ans = c.get("answer")
    if isinstance(ans, str):
        ans = "ABCD".find(ans.strip().upper()[:1]) if not ans.strip().isdigit() else int(ans)
    try:
        ans = int(ans)
    except Exception:
        return None
    if not 0 <= ans < len(opts):
        return None
    ww = [str(x) for x in (c.get("why_wrong") or [])]
    ww = (ww + [""] * len(opts))[:len(opts)]
    order = list(range(len(opts)))
    random.Random(seed).shuffle(order)
    return {"question": str(c["question"]), "options": [opts[i] for i in order], "answer": order.index(ans),
            "why_right": str(c.get("why_right", "")), "why_wrong": [ww[i] for i in order]}


def dnu_stage(ctx, idx):
    stage = ctx["outline"]["stages"][idx]
    payload = {"student_says": ctx["confusion"], "subject": ctx["subject"], "student_level": ctx["level"],
               "lesson_goal": ctx["outline"].get("goal", ""), "all_stage_titles": [s["title"] for s in ctx["outline"]["stages"]],
               "this_stage_number": idx + 1, "this_stage": stage, "material_from_photo": ctx["source_text"][:2500],
               "image_regions": ctx["region_labels"]}
    last = None
    for attempt in range(2):
        out = nim.chat_json(STAGE_SYS, json.dumps(payload), temperature=0.3 + 0.1 * attempt, max_tokens=2500)
        if not isinstance(out, dict):
            continue
        chk = fix_check(out.get("check"), seed=idx + 7)
        if chk and out.get("explain"):
            card = out.get("card") if isinstance(out.get("card"), dict) else {}
            return {"title": stage["title"], "explain": str(out["explain"]), "key_point": str(out.get("key_point", "")),
                    "visual": out.get("visual") if isinstance(out.get("visual"), dict) else {"type": "none"},
                    "check": chk, "card": {"front": str(card.get("front", "")), "back": str(card.get("back", ""))}}
        last = out
    raise ValueError(f"Could not build stage {idx + 1}: {str(last)[:120]}")


def dnu_final(ctx):
    payload = {"student_says": ctx["confusion"], "subject": ctx["subject"], "student_level": ctx["level"],
               "lesson_goal": ctx["outline"].get("goal", ""), "stages": [{"title": s["title"], "focus": s.get("focus", "")} for s in ctx["outline"]["stages"]],
               "material_from_photo": ctx["source_text"][:1500]}
    out = nim.chat_json(FINAL_SYS, json.dumps(payload), temperature=0.4, max_tokens=2500)
    qs = []
    for i, q in enumerate(out.get("questions", []) if isinstance(out, dict) else out):
        if not isinstance(q, dict):
            continue
        if q.get("type") == "mcq":
            chk = fix_check(q, seed=100 + i)
            if chk:
                qs.append({"type": "mcq", **chk})
        elif q.get("question") and q.get("model_answer"):
            qs.append({"type": q.get("type", "apply"), "question": str(q["question"]), "model_answer": str(q["model_answer"]),
                       "rubric": [str(r) for r in q.get("rubric", [])][:5]})
    if len(qs) < 2:
        raise ValueError("The final test came back too short.")
    return qs


def dnu_grade_short(q, answer):
    if not str(answer).strip():
        return {"score": 0.0, "feedback": "No answer given.", "missed": q.get("rubric", [])}
    out = nim.chat_json(GRADE_SHORT_SYS, json.dumps({"question": q["question"], "model_answer": q["model_answer"],
                                                    "rubric": q.get("rubric", []), "student_answer": str(answer)[:1500]}),
                        kind="fast", temperature=0.1, max_tokens=500)
    try:
        score = max(0.0, min(1.0, float(out.get("score", 0))))
    except Exception:
        score = 0.0
    return {"score": score, "feedback": str(out.get("feedback", "")), "missed": out.get("missed", [])}


def dnu_reexplain_stream(stage, source_text, wrong_picks):
    msgs = [{"role": "system", "content": REEXPLAIN_SYS},
            {"role": "user", "content": json.dumps({"stage_title": stage["title"], "first_explanation": stage["explain"],
                                                    "question": stage["check"]["question"],
                                                    "wrong_answers_chosen": wrong_picks, "material": source_text[:1500]})}]
    return nim.stream(msgs, kind="teacher", temperature=0.6, max_tokens=500)
