"""轻量 OpenAI 兼容客户端；没有密钥时返回 None，保证本地流程可运行。"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict, Optional

from .config import LLM_MODEL, OPENAI_API_BASE, OPENAI_API_KEY, RAG_USE_LLM


def enabled() -> bool:
    return bool(RAG_USE_LLM and OPENAI_API_KEY and OPENAI_API_BASE)


def chat(messages: list[dict[str, str]], max_tokens: int = 1000) -> Optional[str]:
    if not enabled():
        return None
    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_API_BASE.rstrip("/") + "/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # pragma: no cover - 外部服务失败路径
        print(f"[LLM] 调用失败，使用本地答案: {exc}")
        return None


def extract_json(prompt: str, system: str) -> Optional[Dict[str, Any]]:
    raw = chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}], 1200)
    if not raw:
        return None
    try:
        start, end = raw.find("{"), raw.rfind("}")
        return json.loads(raw[start:end + 1]) if start >= 0 and end > start else None
    except (ValueError, json.JSONDecodeError):
        return None
