from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import GRAPH_FILE
from app.graph import build_graph
from app.index import build_index
from app.ingest import chunk_documents, clean_sources


def main() -> None:
    parser = argparse.ArgumentParser(description="构建施工安全 RAG 知识库")
    parser.add_argument("--with-llm", action="store_true", help="使用 OpenAI 兼容模型抽取图谱；默认规则抽取")
    args = parser.parse_args()
    documents = clean_sources()
    chunks = chunk_documents(documents)
    build_index(chunks)
    graph = build_graph(chunks, use_llm=args.with_llm)
    GRAPH_FILE.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"文档：{len(documents)}，切块：{len(chunks)}，实体：{len(graph['entities'])}，关系：{len(graph['relations'])}")


if __name__ == "__main__":
    main()
