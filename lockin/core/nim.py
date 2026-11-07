import base64
import io
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from openai import APIStatusError, BadRequestError, OpenAI

load_dotenv()

PRIMARY = "mistralai/mistral-large-4-1t-a52b"
DEFAULTS = {
    "teacher": [PRIMARY, "nvidia/nemotron-3-super-120b-a12b", "qwen/qwen3.5-397b-a17b", "meta/llama-3.3-70b-instruct"],
    "fast": [PRIMARY, "nvidia/nemotron-3-nano-30b-a3b", "meta/llama-3.1-8b-instruct"],
    "vision": [PRIMARY, "meta/llama-4-maverick-17b-128e-instruct", "nvidia/nemotron-nano-12b-v2-vl", "qwen/qwen3.5-397b-a17b"],
}
ENV = {"teacher": "NIM_TEACHER_MODEL", "fast": "NIM_FAST_MODEL", "vision": "NIM_VISION_MODEL"}
ROLE_ALIAS = {"text": "teacher", "teacher": "teacher", "fast": "fast", "vision": "vision"}
TIMEOUT = {"teacher": 120, "fast": 90, "vision": 120}

_good = {}
_bad = {}
_variant = {}
_clients = {}
_lock = threading.Lock()


def role_of(kind):
    return ROLE_ALIAS.get(kind, "teacher")


def chain(kind):
    role = role_of(kind)
    names = []
    custom = os.getenv(ENV[role], "")
    names += [m.strip() for m in custom.split(",") if m.strip()]
    names += DEFAULTS[role]
    legacy = os.getenv("NIM_MODEL", "").strip()
    if legacy and role in ("teacher", "fast"):
        names.append(legacy)
    out, now = [], time.time()
    for m in names:
        if m not in out and _bad.get(m, 0) < now:
            out.append(m)
    return out or list(DEFAULTS[role])


def client(role="teacher"):
    key = os.getenv("NVIDIA_API_KEY")
    if not key:
        raise RuntimeError("NVIDIA_API_KEY is missing. Add it in the Streamlit secrets.")
    base = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    k = (key, base, role)
    with _lock:
        if k not in _clients:
            _clients[k] = OpenAI(base_url=base, api_key=key, timeout=TIMEOUT[role], max_retries=0)
        return _clients[k]


def thinking_on():
    return os.getenv("NIM_THINK", "").strip().lower() in ("1", "true", "yes", "on")


def reasoning_effort():
    return (os.getenv("NIM_REASONING", "none").strip().lower() or "none")


def _variants(model, json_mode):
    if model.startswith("mistralai/"):
        base = {"extra_body": {"reasoning_effort": reasoning_effort()}}
    elif thinking_on():
        base = {}
    else:
        base = {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
    v = []
    if json_mode:
        v.append({**base, "response_format": {"type": "json_object"}})
    v.append(dict(base))
    if base:
        v.append({})
    return v


def _is_gone(e):
    msg = str(getattr(e, "message", e))
    if e.status_code in (404, 410):
        return True
    return e.status_code in (400, 403) and bool(re.search(
        r"not found|does not exist|unknown model|not available|deprecated|end of life|eol|no access|not authorized|not entitled", msg, re.I))


def _clean(text):
    text = text or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return text.split("</think>")[-1].strip()


def _call(role, model, messages, temperature, max_tokens, json_mode, stream=False):
    c = client(role)
    last = None
    variants = _variants(model, json_mode)
    start = min(_variant.get((model, json_mode), 0), len(variants) - 1)
    for i in range(start, len(variants)):
        try:
            r = c.chat.completions.create(model=model, messages=messages, temperature=temperature,
                                          max_tokens=max_tokens, stream=stream, **variants[i])
            _variant[(model, json_mode)] = i
            return r
        except BadRequestError as e:
            if _is_gone(e):
                raise
            last = e
    raise last


def _run(kind, messages, temperature, max_tokens, json_mode=False, retries=1):
    role = role_of(kind)
    tried, last = [], None
    for model in chain(kind):
        for attempt in range(retries + 1):
            try:
                r = _call(role, model, messages, temperature, max_tokens, json_mode)
                choice = r.choices[0]
                text = _clean(choice.message.content)
                if not text:
                    raise RuntimeError("empty reply" + (" (token limit)" if choice.finish_reason == "length" else ""))
                _good[role] = model
                return text
            except APIStatusError as e:
                last = e
                if e.status_code == 401:
                    raise RuntimeError("NVIDIA rejected the API key (401). Check NVIDIA_API_KEY in the secrets.") from None
                if _is_gone(e):
                    _bad[model] = time.time() + 1800
                    break
                if e.status_code == 429 or e.status_code >= 500:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
            except Exception as e:
                last = e
                time.sleep(0.5)
        tried.append(model)
    detail = str(getattr(last, "message", last))[:300]
    raise RuntimeError(f"No model answered ({role}). Tried: {', '.join(tried)}. Last error: {detail}")


def chat(messages, kind="teacher", temperature=0.3, max_tokens=3000, json_mode=False):
    return _run(kind, messages, temperature, max_tokens, json_mode)


def stream(messages, kind="teacher", temperature=0.4, max_tokens=1500):
    role = role_of(kind)
    last = None
    for model in chain(kind):
        started = False
        try:
            s = _call(role, model, messages, temperature, max_tokens, False, stream=True)
            for chunk in s:
                if not chunk.choices:
                    continue
                piece = chunk.choices[0].delta.content
                if piece:
                    started = True
                    yield piece
            if started:
                _good[role] = model
                return
        except APIStatusError as e:
            last = e
            if e.status_code == 401:
                raise RuntimeError("NVIDIA rejected the API key (401).") from None
            if _is_gone(e):
                _bad[model] = time.time() + 1800
        except Exception as e:
            last = e
            if started:
                return
    raise RuntimeError(f"No model answered. Last error: {str(getattr(last, 'message', last))[:300]}")


def _extract(text):
    text = _clean(text)
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence and re.search(r"[\[{]", fence.group(1)):
        text = fence.group(1)
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError("The model did not return JSON: " + text[:200])
    return text[min(starts):]


def _repair(s):
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = re.sub(r"}\s*{", "},{", s)
    s = re.sub(r",\s*([}\]])", r"\1", s)
    stack, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    if in_str:
        s += '"'
    s = re.sub(r",\s*$", "", s)
    return s + "".join(reversed(stack))


def parse_json(text):
    s = _extract(text)
    dec = json.JSONDecoder(strict=False)
    try:
        return dec.raw_decode(s)[0]
    except json.JSONDecodeError:
        return dec.raw_decode(_repair(s))[0]


def chat_json(system, user, kind="teacher", temperature=0.2, max_tokens=3000):
    msgs = [{"role": "system", "content": system + "\nReturn ONLY one valid JSON value. No prose, no markdown fences."},
            {"role": "user", "content": user}]
    err = None
    for attempt in range(3):
        out = chat(msgs, kind=kind, temperature=temperature, max_tokens=int(max_tokens * (1 + 0.5 * attempt)), json_mode=True)
        try:
            return parse_json(out)
        except Exception as e:
            err = e
            msgs = msgs[:2] + [{"role": "assistant", "content": out[:6000]},
                               {"role": "user", "content": f"That was not valid JSON ({str(e)[:120]}). Return the COMPLETE answer again as valid JSON only."}]
    raise ValueError(f"Could not get valid JSON from the model: {err}")


def prep_image(data, max_side=1568):
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return data, "image/jpeg"


def vision_messages(system, user, image_bytes):
    data, mime = prep_image(image_bytes)
    b64 = base64.b64encode(data).decode()
    return [{"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": user}]}]


def vision_json(system, user, image_bytes, mime="image/jpeg", max_tokens=3000):
    msgs = vision_messages(system + "\nReturn ONLY one valid JSON value. No prose, no markdown fences.", user, image_bytes)
    err = None
    for attempt in range(2):
        out = chat(msgs, kind="vision", temperature=0.1, max_tokens=int(max_tokens * (1 + 0.5 * attempt)), json_mode=True)
        try:
            return parse_json(out)
        except Exception as e:
            err = e
            msgs = msgs[:2] + [{"role": "assistant", "content": out[:6000]},
                               {"role": "user", "content": "That was not valid JSON. Return the complete answer again as valid JSON only."}]
    raise ValueError(f"Could not get valid JSON from the vision model: {err}")


def parallel(fn, items, workers=6):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def list_models():
    r = client("fast").models.list()
    return sorted(m.id for m in r.data)


def test_model(model, role="teacher"):
    t = time.time()
    try:
        c = client(role)
        if role == "vision":
            from PIL import Image, ImageDraw
            im = Image.new("RGB", (240, 90), "white")
            ImageDraw.Draw(im).text((20, 35), "HELLO 42", fill="black")
            buf = io.BytesIO()
            im.save(buf, "PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            msgs = [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": "What text is written in the image? Reply with only that text."}]}]
        else:
            msgs = [{"role": "user", "content": "Reply with the single word OK."}]
        r = c.with_options(timeout=40).chat.completions.create(model=model, messages=msgs, max_tokens=24, temperature=0)
        return True, round(time.time() - t, 1), _clean(r.choices[0].message.content)[:60]
    except Exception as e:
        return False, round(time.time() - t, 1), str(getattr(e, "message", e))[:160]
