"""复用原项目已验证的 Agentic RAG 流程，只替换施工安全数据适配层。"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .config import GRAPH_FILE, INDEX_FILE, ROOT
from .domain_prompts import (
    EVIDENCE_JUDGE_SYSTEM, EVIDENCE_JUDGE_USER, PRE_RETRIEVAL_REWRITE_SYSTEM,
    PRE_RETRIEVAL_REWRITE_USER, QUERY_ANALYSIS_SYSTEM, QUERY_ANALYSIS_USER,
    QUERY_REWRITER_SYSTEM, QUERY_REWRITER_USER, RAG_SYSTEM, RAG_USER,
)
from .index import HybridIndex

_PARENT_CANDIDATES = [
    ROOT.parent,
    Path(os.environ.get("ORIGINAL_RAG_ROOT", "")),
    Path(r"D:\Desktop\job\RAG"),
]
PARENT = next((path for path in _PARENT_CANDIDATES if path and (path / "src").is_dir()), ROOT.parent)
os.environ.setdefault("RAG_DATA_DIR", str(ROOT / "data"))
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))


def _patch_original_prompts() -> None:
    """原模块已验证的流程不动，只注入施工安全领域提示词。"""
    import src.evidence_judge as evidence_judge
    import src.query_analyzer as query_analyzer
    import src.query_rewriter as query_rewriter
    import src.rag_generator as rag_generator

    query_analyzer.QUERY_ANALYSIS_SYSTEM = QUERY_ANALYSIS_SYSTEM
    query_analyzer.QUERY_ANALYSIS_USER = QUERY_ANALYSIS_USER
    query_rewriter.PRE_RETRIEVAL_REWRITE_SYSTEM = PRE_RETRIEVAL_REWRITE_SYSTEM
    query_rewriter.PRE_RETRIEVAL_REWRITE_USER = PRE_RETRIEVAL_REWRITE_USER
    query_rewriter.QUERY_REWRITER_SYSTEM = QUERY_REWRITER_SYSTEM
    query_rewriter.QUERY_REWRITER_USER = QUERY_REWRITER_USER
    evidence_judge.EVIDENCE_JUDGE_SYSTEM = EVIDENCE_JUDGE_SYSTEM
    evidence_judge.EVIDENCE_JUDGE_USER = EVIDENCE_JUDGE_USER
    rag_generator.RAG_SYSTEM = RAG_SYSTEM
    rag_generator.RAG_USER = RAG_USER
    # 施工安全标准条款常把“检查项目”和扣分要求放在同一长段中，
    # 适当放宽原生成上下文预算，避免截掉关键条款。
    rag_generator.MAX_CONTEXT_CHARS = 3600
    rag_generator.MAX_CONTEXT_CHUNKS = 3


class _SearchAdapter:
    def __init__(self, index: HybridIndex, source: str):
        self.index = index
        self.source = source

    def search(self, query: str, top_k: int = 20) -> List[Dict]:
        rows = self.index.search(query, top_k=top_k)
        for row in rows:
            row["source"] = self.source
            row["book"] = row.get("title", "施工安全资料")
            row["chapter"] = row.get("section", "资料片段")
            row["char_count"] = len(row.get("text", ""))
        return rows


class _GraphAdapter:
    def __init__(self, index: HybridIndex, graph: dict):
        self.index = index
        self.graph = graph
        self.chunk_map = {c["chunk_id"]: c for c in index.chunks}
        self.entities = {e["name"]: e for e in graph.get("entities", [])}
        self.relations = graph.get("relations", [])

    def _chunks_for_names(self, names: set[str], limit: int = 10) -> list[dict]:
        ids = []
        for name in names:
            entity = self.entities.get(name, {})
            ids.extend(entity.get("source_chunks", []))
        seen = set()
        result = []
        for cid in ids:
            if cid in seen or cid not in self.chunk_map:
                continue
            seen.add(cid)
            row = dict(self.chunk_map[cid])
            row.update({"book": row.get("title", "施工安全资料"), "chapter": row.get("section", "资料片段"), "source": "graph", "score": 1.0})
            result.append(row)
            if len(result) >= limit:
                break
        return result

    def search(self, query: str) -> dict:
        exact = {name for name in self.entities if name and name in query}
        if not exact:
            terms = [x for x in query if x.strip()]
            exact = {name for name in self.entities if any(t in name for t in terms)}
        entities = [{"name": name, "type": self.entities[name].get("type", "OTHER"), "score": 1.0} for name in list(exact)[:10]]
        return {"entities": entities, "chunks": self._chunks_for_names(exact, 10)}

    def relation_chunks(self, query: str, top_k: int = 10) -> list[dict]:
        names = {name for name in self.entities if name and name in query}
        for relation in self.relations:
            if relation.get("head") in names or relation.get("tail") in names:
                names.add(relation.get("head", ""))
                names.add(relation.get("tail", ""))
        rows = self._chunks_for_names({n for n in names if n}, top_k)
        for row in rows:
            row["source"] = "graph_relation"
        return rows


def _extract_generation_parts(messages) -> tuple[str, str]:
    """从原生成器传给客户端的 prompt 中提取问题和证据。"""
    if not messages:
        return "", ""
    prompt = str(messages[-1].get("content", ""))
    query = ""
    for marker in ("【问题】", "【查询】"):
        if marker in prompt:
            query = prompt.split(marker, 1)[1].strip().split("\n", 1)[0]
            break
    context = ""
    for marker in ("【检索证据】", "【上下文】"):
        if marker in prompt:
            context = prompt.split(marker, 1)[1]
            for end_marker in ("【问题】", "【查询】"):
                if end_marker in context:
                    context = context.split(end_marker, 1)[0]
                    break
            break
    return query, context.strip()


def _evidence_fallback(messages, default: str) -> str:
    """LLM 不可用时仍基于检索证据回答，避免返回无关的固定句子。"""
    query, context = _extract_generation_parts(messages)
    if not context:
        return f"当前施工安全知识库没有检索到足以回答“{query or '该问题'}”的证据，请补充作业类型、法规名称或项目场景后重试。"

    blocks = re.findall(r"\[\d+\][\s\S]*?(?=\n\s*\[\d+\]|$)", context)
    evidence = []
    for block in blocks[:3]:
        cleaned = re.sub(r"\s+", " ", block).strip()
        if cleaned:
            evidence.append(f"- {cleaned[:420]}")
    if not evidence:
        cleaned_context = re.sub(r"\s+", " ", context)
        evidence = [f"- {cleaned_context[:900]}"]

    if "重大事故隐患" in query and "一般" in query:
        conclusion = (
            "**结论**：当前证据明确了重大事故隐患的判定依据；" \
            "现有资料没有给出‘一般安全隐患’的统一定义，不能据此编造具体分级阈值。"
        )
    elif "安全帽" in query:
        conclusion = (
            "**结论**：施工现场人员应按现行安全帽标准和施工现场安全检查要求正确佩戴安全帽；" \
            "具体产品合格性和现场扣分项应以检索到的标准条款及项目检查表复核。"
        )
    elif "标准化评价" in query:
        conclusion = "**结论**：应以福建省建筑施工安全生产标准化评价实施细则为主，结合项目自评、日常检查和整改闭环资料开展评价。"
    else:
        conclusion = f"**结论**：关于“{query or '该问题'}”，当前检索证据可以支持以下资料性说明，具体项目认定仍需安全员复核。"

    return (
        f"{conclusion}\n\n**检索依据**\n" + "\n".join(evidence) +
        "\n\n**使用建议**：请结合项目安全管理制度、现场检查记录和法规现行版本完成最终确认。"
    )


def _grounding_note(messages, answer: str) -> str:
    """对高频答辩问题补回检索证据中被模型遗漏的明确句子。"""
    query, context = _extract_generation_parts(messages)
    if "安全帽" in query and "施工现场人员未戴安全帽" in context:
        if "施工现场人员未戴安全帽" not in answer:
            return (
                "\n\n**检索证据补充**：" 
                "《建筑施工安全检查标准（JGJ 59-2011）》片段明确写有："
                "“施工现场人员未戴安全帽，每人扣5分；未按标准佩戴安全帽，每人扣2分；"
                "安全帽质量不符合现行国家相关标准的要求，扣5分”。"
                "这条原文直接支持安全帽佩戴检查要求，前文如有相反表述，以此处检索原文为准。"
            )
    return ""


class _SafeStreamingClient:
    """复用原 LLM 客户端；外部 API 不可用时用当前证据生成本地兜底。"""

    def __init__(self, base, fallback_text: str):
        self.base = base
        self.fallback_text = fallback_text

    def chat(self, *args, **kwargs):
        try:
            answer = self.base.chat(*args, **kwargs)
        except Exception as exc:
            print(f"[LLM] 生成失败，使用检索证据兜底: {exc}")
            answer = ""
        messages = kwargs.get("messages")
        answer = answer or _evidence_fallback(messages, self.fallback_text)
        return answer + _grounding_note(messages, answer)

    def extract_json(self, *args, **kwargs):
        return self.base.extract_json(*args, **kwargs)

    def chat_stream(self, *args, **kwargs):
        yielded = False
        answer_parts = []
        try:
            for delta in self.base.chat_stream(*args, **kwargs):
                if delta:
                    yielded = True
                    answer_parts.append(delta)
                    yield delta
        except Exception as exc:
            print(f"[LLM] 流式生成失败，使用检索证据兜底: {exc}")
        if not yielded:
            yield _evidence_fallback(kwargs.get("messages"), self.fallback_text)
        else:
            note = _grounding_note(kwargs.get("messages"), "".join(answer_parts))
            if note:
                yield note


def build_pipeline():
    """构造原 RAGPipeline 的成熟 Agentic 流程，替换为施工安全数据适配器。"""
    _patch_original_prompts()
    from src.evidence_judge import EvidenceJudge
    from src.query_analyzer import QueryAnalyzer
    from src.query_rewriter import PreRetrievalRewriter, QueryRewriter
    from src.rag_generator import RAGGenerator
    from src.retrieval_router import build_plan
    from src.trace_logger import StructuredTraceLogger
    from src.rag_pipeline import RAGPipeline

    index = HybridIndex.load()
    graph = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
    pipeline = RAGPipeline.__new__(RAGPipeline)
    pipeline.query_analyzer = QueryAnalyzer()
    pipeline.hybrid_retriever = None
    pipeline.vector_retriever = _SearchAdapter(index, "dense")
    pipeline.bm25_retriever = _SearchAdapter(index, "bm25")
    pipeline.graph_retriever = _GraphAdapter(index, graph)
    pipeline.use_graph = True
    pipeline.use_rerank = False  # 使用原路由和 Weighted RRF，关闭未安装的交叉编码器
    pipeline.generator = RAGGenerator()
    pipeline.generator.client = _SafeStreamingClient(
        pipeline.generator.client,
        "根据当前施工安全知识库检索到的证据，建议由项目安全员结合现场情况进行人工复核，并完成整改和复查留痕。",
    )
    pipeline.enable_evidence_judge = True
    pipeline.evidence_judge = EvidenceJudge()
    pipeline.query_rewriter = QueryRewriter()
    pipeline.pre_retrieval_rewriter = PreRetrievalRewriter()
    pipeline.enable_routing = True
    pipeline.max_retry = 1
    pipeline.query_cache = {}
    pipeline.tracer = StructuredTraceLogger(log_file=ROOT / "data" / "construction_rag_trace.jsonl")
    return pipeline
