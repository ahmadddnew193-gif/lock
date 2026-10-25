from core import nim

CARD_SYS = """You make high-quality Anki flashcards for exam prep.
Rules: one atomic fact per card, question must be answerable from memory, no yes/no questions,
prefer 'why/how/what is the difference' over pure definitions when the material allows,
answers under 25 words. Return JSON: {"cards":[{"front":str,"back":str}]}"""


def make_cards(material: str, n=10):
    out = nim.chat_json(CARD_SYS, f"Make {n} cards from this material:\n{material[:6000]}", temperature=0.3)
    return out["cards"] if isinstance(out, dict) else out


GRADE_SYS = """You grade a student's retry of a question they previously got wrong.
Return JSON: {"pass": true/false, "feedback": "1-2 sentences", "score": 0-10}.
Pass only if the core idea is correct."""


def grade_retry(question, correct, attempt):
    return nim.chat_json(GRADE_SYS, f"Question: {question}\nCorrect: {correct}\nStudent: {attempt or '(blank)'}", kind="fast")
