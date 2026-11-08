import base64
import io
import json
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dotenv import load_dotenv
from openai import APIStatusError, BadRequestError, OpenAI

load_dotenv()

PRIMARY = "mistralai/mistral-large-4-1t-a52b"
DEFAULTS = {
    "teacher": [PRIMARY, "nvidia/nemotron-3.5-super-vl-120b-a12b", "nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3.5-lightning-30b-a3b"],
    "fast": [PRIMARY, "nvidia/nemotron-3.5-lightning-30b-a3b", "nvidia/nemotron-3.5-super-vl-120b-a12b"],
    "vision": [PRIMARY, "nvidia/nemotron-3.5-super-vl-120b-a12b"],
}
ENV = {"teacher": "NIM_TEACHER_MODEL", "fast": "NIM_FAST_MODEL", "vision": "NIM_VISION_MODEL"}
ROLE_ALIAS = {"text": "teacher", "teacher": "teacher", "fast": "fast", "vision": "vision"}
TIMEOUT = {"teacher": 120, "fast": 90, "vision": 120}

_good = {}
_bad = {}
_variant = {}
_clients = {}
_lock = threading.Lock()
STATS = deque(maxlen=300)


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
    v = os.getenv("NIM_REASONING", "low").strip().lower()
    return v if v in ("low", "medium", "high") else "low"


def headroom(model, max_tokens):
    return max_tokens + 1500 if model.startswith("mistralai/") else max_tokens


def content_text(message):
    c = getattr(message, "content", None)
    if isinstance(c, list):
        c = "".join(x.get("text", "") if isinstance(x, dict) else str(getattr(x, "text", "")) for x in c)
    return _clean(c)


def json_mode_enabled():
    return os.getenv("NIM_JSON_MODE", "on").strip().lower() not in ("off", "0", "false", "no")


def _variants(model, json_mode):
    json_mode = json_mode and json_mode_enabled()
    extras = []
    if model.startswith("mistralai/"):
        extras.append({"extra_body": {"reasoning_effort": reasoning_effort()}})
    elif not thinking_on():
        extras.append({"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}})
    extras.append({})
    out = []
    for e in extras:
        if json_mode:
            out.append({**e, "response_format": {"type": "json_object"}})
        out.append(dict(e))
    return out


def _is_gone(e):
    return e.status_code in (404, 410)


def _detail(e):
    try:
        t = e.response.text.strip()
    except Exception:
        t = ""
    return (t or str(getattr(e, "message", e)))[:220]


def _summary(role, errs):
    lines = [f"{m.split('/')[-1]}: {st if st else 'error'} {d}".strip() for m, st, d in errs]
    msg = f"No model answered ({role}). " + " | ".join(lines)
    if errs and all(st == 410 for _, st, _ in errs):
        silent = any("end of life" not in d.lower() for _, _, d in errs)
        if silent:
            msg += (" || Every model returned 410 with no explanation. This usually means your NVIDIA API key does not have the "
                    "'Public API Endpoints' service enabled. Create a new key at build.nvidia.com or in NGC (Setup, API Keys, Generate Personal Key) "
                    "and tick Public API Endpoints, then put it in the NVIDIA_API_KEY secret.")
        else:
            msg += " || Every model has been retired. Set NIM_TEACHER_MODEL and NIM_VISION_MODEL to a current model from build.nvidia.com."
    return msg


def _clean(text):
    text = text or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return text.split("</think>")[-1].strip()


def _call(role, model, messages, temperature, max_tokens, json_mode, stream=False):
    c = client(role)
    last = None
    variants = _variants(model, json_mode)
    start = min(_variant.get((model, json_mode), 0), len(variants) - 1)
    for i in list(range(start, len(variants))) + list(range(0, start)):
        try:
            r = c.chat.completions.create(model=model, messages=messages, temperature=max(temperature, 0.1),
                                          max_tokens=headroom(model, max_tokens), stream=stream, **variants[i])
            _variant[(model, json_mode)] = i
            return r
        except APIStatusError as e:
            if e.status_code in (400, 422):
                last = e
                continue
            raise
    raise last


def hedge_seconds(role):
    try:
        base = float(os.getenv("NIM_HEDGE_SECONDS", "6") or 0)
    except ValueError:
        base = 6.0
    return base * (2 if role == "vision" else 1)


def _hedged(role, model, messages, temperature, max_tokens, json_mode):
    delay = hedge_seconds(role)
    if delay <= 0:
        return _call(role, model, messages, temperature, max_tokens, json_mode), False
    ex = ThreadPoolExecutor(max_workers=2)
    futs = [ex.submit(_call, role, model, messages, temperature, max_tokens, json_mode)]
    done, _ = wait(futs, timeout=delay)
    hedged = False
    if not done:
        futs.append(ex.submit(_call, role, model, messages, temperature, max_tokens, json_mode))
        hedged = True
    pending, err = set(futs), None
    while pending:
        done, pending = wait(pending, return_when=FIRST_COMPLETED)
        for f in done:
            try:
                r = f.result()
                ex.shutdown(wait=False, cancel_futures=True)
                return r, hedged
            except Exception as e:
                err = e
    ex.shutdown(wait=False)
    raise err


def _run(kind, messages, temperature, max_tokens, json_mode=False, retries=1):
    role = role_of(kind)
    errs = []
    for model in chain(kind):
        status, detail = None, ""
        mt = max_tokens
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                r, hedged = _hedged(role, model, messages, temperature, mt, json_mode)
                choice = r.choices[0]
                text = content_text(choice.message)
                if not text:
                    if choice.finish_reason == "length":
                        mt = min(mt * 2, 8000)
                    raise RuntimeError("empty reply" + (" (token limit)" if choice.finish_reason == "length" else ""))
                _good[role] = model
                STATS.append({"time": time.strftime("%H:%M:%S"), "role": role, "model": model.split("/")[-1],
                              "seconds": round(time.time() - t0, 1), "hedged": hedged, "ok": True})
                return text
            except APIStatusError as e:
                status, detail = e.status_code, _detail(e)
                STATS.append({"time": time.strftime("%H:%M:%S"), "role": role, "model": model.split("/")[-1],
                              "seconds": round(time.time() - t0, 1), "hedged": False, "ok": False})
                if e.status_code == 401:
                    raise RuntimeError("NVIDIA rejected the API key (401). Check NVIDIA_API_KEY in the secrets.") from None
                if _is_gone(e):
                    _bad[model] = time.time() + 600
                    break
                if e.status_code == 429 or e.status_code >= 500:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
            except Exception as e:
                status, detail = None, str(e)[:120]
                time.sleep(0.5)
        errs.append((model, status, detail))
    raise RuntimeError(_summary(role, errs))


def chat(messages, kind="teacher", temperature=0.3, max_tokens=3000, json_mode=False):
    return _run(kind, messages, temperature, max_tokens, json_mode)


def stream(messages, kind="teacher", temperature=0.4, max_tokens=1500):
    role = role_of(kind)
    errs = []
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
            errs.append((model, e.status_code, _detail(e)))
            if e.status_code == 401:
                raise RuntimeError("NVIDIA rejected the API key (401).") from None
            if _is_gone(e):
                _bad[model] = time.time() + 600
        except Exception as e:
            errs.append((model, None, str(e)[:120]))
            if started:
                return
    raise RuntimeError(_summary(role, errs))


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
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]}]


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


def _test_messages(role):
    if role == "vision":
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (240, 90), "white")
        ImageDraw.Draw(im).text((20, 35), "HELLO 42", fill="black")
        buf = io.BytesIO()
        im.save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return [{"role": "user", "content": [
            {"type": "text", "text": "What text is written in the image? Reply with only that text."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}]
    return [{"role": "user", "content": "Reply with the single word OK."}]


def test_model(model, role="teacher"):
    t = time.time()
    try:
        r = _call(role, model, _test_messages(role), 0.1, 300, False)
        text = content_text(r.choices[0].message)
        return bool(text), round(time.time() - t, 1), text[:60] or "(empty reply)"
    except Exception as e:
        return False, round(time.time() - t, 1), f"{getattr(e, 'status_code', '')} {_detail(e)}".strip()[:220]


def diagnose(model, role="teacher"):
    out = []
    c = client(role).with_options(timeout=90)
    msgs = _test_messages(role)
    json_msgs = [{"role": "user", "content": "Return a JSON object with a key 'topics' holding a list of three short study tips about memory."}]
    low = {"extra_body": {"reasoning_effort": "low"}}
    plans = [("warm-up (not counted)", msgs, {}),
             ("low, plain", msgs, low),
             ("low + JSON mode, 1st try", json_msgs, {**low, "response_format": {"type": "json_object"}}),
             ("low + JSON mode, 2nd try", json_msgs, {**low, "response_format": {"type": "json_object"}}),
             ("low, same prompt without JSON mode", json_msgs, low),
             ("medium, plain", msgs, {"extra_body": {"reasoning_effort": "medium"}}),
             ("high (NVIDIA default), plain", msgs, {"extra_body": {"reasoning_effort": "high"}}),
             ("none (documented as unsupported)", msgs, {"extra_body": {"reasoning_effort": "none"}})]
    for label, m, extra in plans:
        t = time.time()
        try:
            r = c.chat.completions.create(model=model, messages=m, max_tokens=headroom(model, 300), temperature=0.1, **extra)
            text = content_text(r.choices[0].message)
            out.append({"request style": label, "works": "✅" if text else "⚠️ empty", "seconds": round(time.time() - t, 1), "reply / error": text[:70]})
        except Exception as e:
            out.append({"request style": label, "works": "❌", "seconds": round(time.time() - t, 1),
                        "reply / error": f"{getattr(e, 'status_code', '')} {_detail(e)}".strip()[:200]})
    if role == "teacher":
        t = time.time()
        try:
            res = chat_json("Return JSON with a key 'tips' holding a list of three short study tips.", "go", max_tokens=300)
            out.append({"request style": "the app's own JSON call (what pages use)", "works": "✅", "seconds": round(time.time() - t, 1), "reply / error": str(res)[:70]})
        except Exception as e:
            out.append({"request style": "the app's own JSON call (what pages use)", "works": "❌", "seconds": round(time.time() - t, 1), "reply / error": str(e)[:200]})
    return out