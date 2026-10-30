import base64, json, os, re, time
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from openai import APIStatusError, BadRequestError, OpenAI

load_dotenv()

DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"


def _models():
    base = os.getenv("NIM_MODEL", DEFAULT_MODEL)
    return {
        "text": os.getenv("NIM_TEXT_MODEL", base),
        "fast": os.getenv("NIM_FAST_MODEL", base),
        "vision": os.getenv("NIM_VISION_MODEL", base),
    }


def client() -> OpenAI:
    key = os.getenv("NVIDIA_API_KEY")
    if not key:
        raise RuntimeError("Set NVIDIA_API_KEY in Secrets, .env, or the sidebar.")
    return OpenAI(base_url=os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"), api_key=key, timeout=120)


def _clean(text):
    text = text or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return text.split("</think>")[-1].strip()


def _create(model, messages, temperature, max_tokens, **extra):
    c = client()
    kw = dict(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens, **extra)
    try:
        return c.chat.completions.create(extra_body={"chat_template_kwargs": {"enable_thinking": False}}, **kw)
    except BadRequestError:
        return c.chat.completions.create(**kw)


def chat(messages, kind="text", temperature=0.3, max_tokens=4096, retries=2):
    model = _models()[kind]
    last = None
    for i in range(retries + 1):
        try:
            r = _create(model, messages, temperature, max_tokens)
            return _clean(r.choices[0].message.content)
        except APIStatusError as e:
            last = RuntimeError(f"NVIDIA API error {e.status_code} for model '{model}': {e.message}")
            if e.status_code != 429 and e.status_code < 500:
                raise last from None
            time.sleep(2 * (i + 1))
        except Exception as e:
            last = RuntimeError(f"Request failed for model '{model}': {e}")
            time.sleep(2 * (i + 1))
    raise last


def stream(messages, kind="text", temperature=0.5, max_tokens=2000):
    s = _create(_models()[kind], messages, temperature, max_tokens, stream=True)
    for chunk in s:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def parse_json(text: str):
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    end = max(text.rfind("}"), text.rfind("]"))
    if start == -1 or end == -1:
        raise ValueError("Model did not return JSON:\n" + text[:300])
    return json.loads(text[start:end + 1])


def chat_json(system, user, kind="text", **kw):
    msgs = [{"role": "system", "content": system + "\nReturn ONLY valid JSON. No prose, no markdown."},
            {"role": "user", "content": user}]
    for _ in range(2):
        out = chat(msgs, kind=kind, **kw)
        try:
            return parse_json(out)
        except Exception:
            msgs.append({"role": "assistant", "content": out})
            msgs.append({"role": "user", "content": "That was not valid JSON. Return ONLY the JSON."})
    raise ValueError("Could not get valid JSON from model.")


def vision_json(system, user, image_bytes: bytes, mime="image/jpeg"):
    b64 = base64.b64encode(image_bytes).decode()
    msgs = [
        {"role": "system", "content": system + "\nReturn ONLY valid JSON."},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": user},
        ]},
    ]
    return parse_json(chat(msgs, kind="vision", max_tokens=4096))


def parallel(fn, items, workers=6):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))
