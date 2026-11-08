import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

ENV_KEYS = ("NVIDIA_API_KEY", "NIM_MODEL", "NIM_TEACHER_MODEL", "NIM_FAST_MODEL", "NIM_VISION_MODEL", "NIM_BASE_URL", "NIM_THINK", "NIM_REASONING", "NIM_JSON_MODE", "NIM_HEDGE_SECONDS")


def secret(name, default=None):
    v = os.getenv(name)
    if v:
        return v
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default


def load_env():
    for k in ENV_KEYS:
        v = secret(k)
        if v and not os.getenv(k):
            os.environ[k] = v
