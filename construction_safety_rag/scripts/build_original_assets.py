"""把施工安全知识库转换为原 RAG Pipeline 所需的成熟索引格式。"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_PARENT_CANDIDATES = [
    ROOT.parent,
    Path(os.environ.get("ORIGINAL_RAG_ROOT", "")),
    Path(r"D:\Desktop\job\RAG"),
]
PARENT = next((path for path in _PARENT_CANDIDATES if path and (path / "src").is_dir()), ROOT.parent)
os.environ["RAG_DATA_DIR"] = str(ROOT / "data")
sys.path.insert(0, str(PARENT))


def prepare_jsonl() -> None:
    import shutil

    data = ROOT / "data"
    chunks_dir = data / "chunks"
    kg_dir = data / "kg"
    for path in (chunks_dir, kg_dir):
        path.mkdir(parents=True, exist_ok=True)

    chunks = [json.loads(line) for line in (data / "processed" / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    converted = []
    for chunk in chunks:
        converted.append({
            "chunk_id": chunk["chunk_id"],
            "book": chunk.get("title", "施工安全资料"),
            "chapter": chunk.get("section", "资料片段"),
            "text": chunk["text"],
            "char_count": len(chunk["text"]),
        })
    (chunks_dir / "chunks.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in converted) + "\n", encoding="utf-8")

    graph = json.loads((data / "processed" / "graph.json").read_text(encoding="utf-8"))
    entities = []
    for entity in graph.get("entities", []):
        entities.append({
            "name": entity["name"],
            "type": entity.get("type", "OTHER"),
            "description": entity.get("description", "施工安全知识库实体"),
            "aliases": entity.get("aliases", []),
            "source_chunks": entity.get("source_chunks", []),
            "chunk_count": len(entity.get("source_chunks", [])),
        })
    (kg_dir / "entities.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in entities) + "\n", encoding="utf-8")

    relations = []
    for relation in graph.get("relations", []):
        relations.append({
            "head": relation["head"], "relation": relation["relation"], "tail": relation["tail"],
            "description": "施工安全资料中的关系",
            "source_chunks": [relation["source_chunk"]] if relation.get("source_chunk") else [],
            "chunk_count": 1,
        })
    for name in ("triples.jsonl", "triples_raw.jsonl"):
        (kg_dir / name).write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in relations) + "\n", encoding="utf-8")


def build_indexes() -> None:
    from src.vector_store import build_vector_store
    from src.kg_indexer import build_all_indexes

    build_vector_store()
    build_all_indexes()


if __name__ == "__main__":
    prepare_jsonl()
    build_indexes()
    print("原 RAG 索引资产构建完成")
