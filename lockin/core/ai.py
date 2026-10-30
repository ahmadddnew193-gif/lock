from core import nim

CARD_SYS = """You make high-quality Anki flashcards for exam prep.
Rules: one atomic fact per card, question must be answerable from memory, no yes/no questions,
prefer 'why/how/what is the difference' over pure definitions when the material allows,
answers under 25 words. Return JSON: {"cards":[{"front":str,"back":str}]}"""


def make_cards(material, n=10):
    out = nim.chat_json(CARD_SYS, f"Make {n} cards from this material:\n{material[:6000]}", temperature=0.3)
    return out["cards"] if isinstance(out, dict) else out


GRADE_SYS = """You grade a student's retry of a question they previously got wrong.
Return JSON: {"pass": true/false, "feedback": "1-2 sentences", "score": 0-10}.
Pass only if the core idea is correct."""


def grade_retry(question, correct, attempt):
    return nim.chat_json(GRADE_SYS, f"Question: {question}\nCorrect: {correct}\nStudent: {attempt or '(blank)'}", kind="fast")


LEVELS = {
    1: "Use plain English: short sentences, no jargon (put any unavoidable term in brackets with a 5-word meaning).",
    2: "Explain it to a curious 10-year-old using one vivid everyday analogy. Zero jargon.",
    3: "The student is an absolute beginner. Use tiny numbered baby steps, one idea per step, one concrete mini-example with real numbers or objects, then ask one check question and give its answer.",
}


def simplify(text, level=1, subject="", attempt=""):
    system = ("You are the most patient tutor in the world. The student did NOT understand the text below. "
              + LEVELS[min(max(level, 1), 3)]
              + " Keep it under 160 words, use **bold** for key terms, and finish with one line starting 'Remember:'.")
    if attempt.strip():
        system += (" The student made their own attempt first. Start by naming what they got right, point out the one "
                   "misconception to fix, then build on their wording.")
    user = f"Subject: {subject or 'general'}\n\n{text[:4000]}"
    if attempt.strip():
        user += f"\n\nStudent's own attempt: {attempt.strip()[:600]}"
    return nim.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                    temperature=0.4, max_tokens=900)


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
    prompt = f"Subject: {subject or 'general'}\n"
    if image:
        return nim.vision_json(EXPLAIN_SYS, prompt + "Explain what is on this page.", image[0], image[1])
    return nim.chat_json(EXPLAIN_SYS, prompt + text[:6000], temperature=0.4, max_tokens=4096)


DIAGRAM_SYS = """You turn study material into a clear diagram.
Kinds: "mind" = one central idea with branches; "concept" = concepts linked by labelled relationships (verbs like causes, requires, is part of);
"flow" = an ordered process, first node is the start.
Return JSON: {"nodes":[{"id":"a","label":"max 5 words"}],"edges":[{"from":"a","to":"b","label":"max 3 words, may be empty"}]}
Use 6 to 12 nodes. Every node must be connected."""


def diagram(text, kind="concept"):
    out = nim.chat_json(DIAGRAM_SYS, f"Kind: {kind}\nMaterial:\n{text[:5000]}", temperature=0.3, max_tokens=2000)
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


def depth_lesson(topic, level, focus="", known=""):
    system = ("You are a world-class tutor teaching one topic in increasing levels of difficulty, at the pace the student sets. "
              + DEPTH[min(max(level, 1), 5)]
              + " Maximum 220 words, short bullets, **bold** key terms. End with two 'Check yourself' questions WITHOUT answers. "
                "If you are not fully certain of a fact, add (verify) right after it. Never invent statistics or citations.")
    user = (f"Topic: {topic}\nWhat the student already understands: {known or 'nothing yet'}\n"
            f"Go deeper on this specific part (if any): {focus or 'the whole topic'}")
    return nim.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], temperature=0.3, max_tokens=900)


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
Topic and material:\n"""


def debate(topic, context, history):
    return nim.chat([{"role": "system", "content": DEBATE_SYS + f"{topic}\n{context[:2500]}"}] + history[-10:],
                    temperature=0.4, max_tokens=700)


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


def classify_questions(lines, hint_topics=None, chunk=40):
    known = list(hint_topics or [])
    result = {}
    for start in range(0, len(lines), chunk):
        part = lines[start:start + chunk]
        numbered = "\n".join(f"{start + i}. {q[:300]}" for i, q in enumerate(part))
        out = nim.chat_json(CLASSIFY_SYS, f"Existing topic names: {known[:60]}\n\nQuestions:\n{numbered}", temperature=0.1, max_tokens=3000)
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
    import json
    payload = json.dumps({"exam": exam, "days_left": days_left, "hours_per_day": hours_per_day,
                          "total_hours_budget": round(days_left * hours_per_day, 1),
                          "frequency_tally": tally, "syllabus_topics": syllabus[:120], "student_weak_topics": weak})
    return nim.chat_json(STRATEGY_SYS, payload, temperature=0.3, max_tokens=5000)
