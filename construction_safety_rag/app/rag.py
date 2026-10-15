from __future__ import annotations

import json
from pathlib import Path

from .config import GRAPH_FILE, INDEX_FILE, TOP_K
from .index import HybridIndex
from .llm import chat


class SafetyRAG:
    def __init__(self, index: HybridIndex | None = None, graph: dict | None = None):
        self.index = index or HybridIndex.load()
        self.graph = graph or json.loads(GRAPH_FILE.read_text(encoding="utf-8"))

    def retrieve(self, question: str, top_k: int = TOP_K) -> list[dict]:
        return self.index.search(question, top_k)

    @staticmethod
    def _local_answer(question: str, evidence: list[dict]) -> str:
        if not evidence:
            return "根据当前知识库没有找到足够的施工安全资料，建议补充项目制度或具体作业场景后再检索。"
        lines = ["根据当前施工安全知识库，检索到以下证据："]
        for i, item in enumerate(evidence[:3], 1):
            citation = f"《{item['title']}》"
            if item.get("document_no"):
                citation += f"（{item['document_no']}）"
            lines.append(f"{i}. {citation}：{item['text'][:260]}")
        lines.append("建议：由项目安全员结合现场照片、作业环境和项目专项方案进行人工复核，再形成整改、复查和留痕记录。")
        return "\n".join(lines)

    def answer(self, question: str) -> dict:
        evidence = self.retrieve(question)
        context = "\n\n".join(
            f"[{i}] {e['title']} | {e['issuer']} | {e.get('document_no','')} | {e['status']}\n{e['text']}"
            for i, e in enumerate(evidence, 1)
        )
        generated = chat([
            {"role": "system", "content": "你是施工安全资料助手，只能根据给定证据回答。必须保留法规名称、发布部门和条款线索；证据不足时明确说明，不得编造。"},
            {"role": "user", "content": f"证据：\n{context}\n\n问题：{question}\n请给出风险解释和可执行整改建议。"},
        ], max_tokens=900)
        answer = generated or self._local_answer(question, evidence)
        references = [{k: item.get(k, "") for k in ("chunk_id", "title", "issuer", "document_no", "status", "source_url", "section", "score")} for item in evidence]
        return {"answer": answer, "references": references, "evidence_count": len(evidence)}
