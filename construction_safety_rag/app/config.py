from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
CLEAN = DATA / "clean"
PROCESSED = DATA / "processed"

for path in (RAW, CLEAN, PROCESSED):
    path.mkdir(parents=True, exist_ok=True)


def load_env() -> None:
    """读取项目 .env；如果没有则兼容复用父 RAG 项目的 .env。"""
    candidates = [
        ROOT / ".env",
        ROOT.parent / ".env",
        Path(os.environ.get("ORIGINAL_RAG_ROOT", r"D:\Desktop\job\RAG")) / ".env",
    ]
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


load_env()

OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", os.getenv("OPENAI_BASE_URL", ""))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", os.getenv("DEFAULT_CHAT_MODEL", "deepseek-chat"))
_rag_use_llm = os.getenv("RAG_USE_LLM")
RAG_USE_LLM = (
    bool(OPENAI_API_KEY and OPENAI_API_BASE)
    if _rag_use_llm is None
    else _rag_use_llm.lower() in {"1", "true", "yes"}
)

CHUNK_SIZE = 650
CHUNK_OVERLAP = 100
TOP_K = 6

SOURCE_CATALOG = DATA / "source_catalog.json"
CHUNKS_FILE = PROCESSED / "chunks.jsonl"
INDEX_FILE = PROCESSED / "index.json"
GRAPH_FILE = PROCESSED / "graph.json"
