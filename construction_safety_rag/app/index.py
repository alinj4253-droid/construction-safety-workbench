from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np

from .config import CHUNKS_FILE, INDEX_FILE, TOP_K


def tokenize(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", text.lower())


def hashed_vector(text: str, dim: int = 256) -> np.ndarray:
    vector = np.zeros(dim, dtype=np.float32)
    grams = tokenize(text)
    for i, token in enumerate(grams):
        vector[hash(token) % dim] += 1.0
        if i + 1 < len(grams):
            vector[hash(token + grams[i + 1]) % dim] += 0.5
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


class HybridIndex:
    def __init__(self, chunks: list[dict], vectors: list[list[float]] | None = None):
        self.chunks = chunks
        self.vectors = np.array(vectors if vectors is not None else [hashed_vector(c["text"]).tolist() for c in chunks], dtype=np.float32)
        self.doc_freq: Counter[str] = Counter()
        self.term_freq: list[Counter[str]] = []
        for chunk in chunks:
            tf = Counter(tokenize(chunk["text"]))
            self.term_freq.append(tf)
            self.doc_freq.update(tf.keys())
        self.avg_len = sum(sum(tf.values()) for tf in self.term_freq) / max(1, len(chunks))

    def _bm25(self, query: str, idx: int) -> float:
        terms = tokenize(query)
        tf = self.term_freq[idx]
        length = sum(tf.values()) or 1
        score = 0.0
        for term in terms:
            if not tf.get(term):
                continue
            idf = math.log(1 + (len(self.chunks) - self.doc_freq.get(term, 0) + 0.5) / (self.doc_freq.get(term, 0) + 0.5))
            score += idf * (tf[term] * 2.2) / (tf[term] + 1.2 * (0.75 + 0.25 * length / max(1, self.avg_len)))
        return score

    def search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        qvec = hashed_vector(query)
        dense = self.vectors @ qvec if len(self.vectors) else np.array([])
        bm25 = [self._bm25(query, i) for i in range(len(self.chunks))]
        max_bm25 = max(bm25, default=1.0) or 1.0
        scored = []
        for i, chunk in enumerate(self.chunks):
            score = 0.55 * float(dense[i]) + 0.45 * (bm25[i] / max_bm25)
            row = dict(chunk)
            row.update({"score": round(score, 6), "dense_score": round(float(dense[i]), 6), "bm25_score": round(bm25[i], 6)})
            scored.append(row)
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:top_k]

    def save(self) -> None:
        payload = {"vectors": self.vectors.tolist(), "chunks": self.chunks}
        INDEX_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls) -> "HybridIndex":
        payload = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        return cls(payload["chunks"], payload["vectors"])


def build_index(chunks: list[dict]) -> HybridIndex:
    index = HybridIndex(chunks)
    index.save()
    CHUNKS_FILE.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n", encoding="utf-8")
    return index
