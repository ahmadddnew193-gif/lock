import base64, json, os, re, time
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()



def _models():
    return {
        "text": os.getenv("NIM_TEXT_MODEL", "meta/llama-3.3-70b-instruct"),
        "fast": os.getenv("NIM_FAST_MODEL", "meta/llama-3.1-8b-instruct"),
        "vision": os.getenv("NIM_VISION_MODEL", "meta/llama-3.2-90b-vision-instruct"),
    }


def client() -> OpenAI:
    key = os.getenv("NVIDIA_API_KEY")
    if not key:
        raise RuntimeError("Set NVIDIA_API_KEY in Secrets, .env, or the sidebar.")
    return OpenAI(base_url=os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"), api_key=key, timeout=90)


def chat(messages, kind="text", temperature=0.3, max_tokens=2500, retries=2):
    model = _models()[kind]
    last = None
    for i in range(retries + 1):
        try:
            r = client().chat.completions.create(
                model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens)
            return r.choices[0].message.content
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def stream(messages, kind="text", temperature=0.5, max_tokens=1500):
    s = client().chat.completions.create(
        model=_models()[kind], messages=messages, temperature=temperature,
        max_tokens=max_tokens, stream=True)
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
            {"type": "text", "text": user},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]},
    ]
    return parse_json(chat(msgs, kind="vision", max_tokens=3000))


def parallel(fn, items, workers=6):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))
