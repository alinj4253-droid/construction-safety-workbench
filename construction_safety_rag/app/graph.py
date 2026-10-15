from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Iterable

from .llm import extract_json

ENTITY_TERMS = {
    "安全帽": "PPE", "安全带": "PPE", "安全网": "PPE", "劳动防护用品": "PPE",
    "高处作业": "OPERATION", "有限空间作业": "OPERATION", "脚手架": "EQUIPMENT", "模板工程": "OPERATION",
    "支撑体系": "EQUIPMENT", "深基坑": "OPERATION", "基坑": "OPERATION", "起重机械": "EQUIPMENT",
    "塔式起重机": "EQUIPMENT", "施工电梯": "EQUIPMENT", "临时用电": "OPERATION", "消防安全": "RISK",
    "智慧工地": "CONCEPT", "安全生产标准化": "CONCEPT", "动态监管": "CONCEPT", "安责险": "CONCEPT",
    "重大事故隐患": "HAZARD", "隐患排查": "CONCEPT", "应急救援": "CONCEPT", "安全教育": "CONCEPT",
    "安全技术交底": "DOCUMENT", "专项施工方案": "DOCUMENT", "安全生产许可证": "DOCUMENT",
    "施工单位": "ROLE", "建设单位": "ROLE", "监理单位": "ROLE", "项目负责人": "ROLE", "安全员": "ROLE",
    "专职安全生产管理人员": "ROLE", "保险机构": "ROLE", "投保单位": "ROLE", "施工现场": "LOCATION",
}


def _rule_extract(text: str) -> tuple[list[dict], list[dict]]:
    names = [name for name in ENTITY_TERMS if name in text]
    entities = [{"name": name, "type": ENTITY_TERMS[name]} for name in names]
    relations = []
    clause_names = sorted(set(re.findall(r"第[一二三四五六七八九十百千万零〇0-9]+条", text)))
    entities.extend({"name": clause, "type": "CLAUSE"} for clause in clause_names)
    concept_names = sorted(set(re.findall(r"[\u4e00-\u9fff]{2,12}(?:作业|工程|管理|责任|方案|检查|评价|标准|措施|制度|培训|监管|治理|服务)", text)))
    for concept in concept_names:
        if concept not in ENTITY_TERMS and not any(item["name"] == concept for item in entities):
            entities.append({"name": concept, "type": "CONCEPT"})
    for name in names:
        if name in {"安全帽", "劳动防护用品"}:
            relations.append({"head": "施工现场", "relation": "应佩戴", "tail": name})
        if name == "重大事故隐患":
            relations.append({"head": name, "relation": "需要治理", "tail": "挂牌督办/整改"})
        if name == "智慧工地":
            relations.append({"head": name, "relation": "支持", "tail": "质量安全信息化"})
        if name in {"重大事故隐患", "隐患排查"}:
            relations.append({"head": "项目安全员", "relation": "负责", "tail": name})
        if name in {"安全技术交底", "专项施工方案"}:
            relations.append({"head": name, "relation": "服务于", "tail": "施工现场"})
    return entities, relations


def extract_entities(text: str, use_llm: bool = False) -> tuple[list[dict], list[dict]]:
    if use_llm:
        result = extract_json(
            f"从以下施工安全资料抽取实体和关系，只输出 JSON。文本：{text[:5000]}",
            "你是施工安全知识图谱抽取专家。实体类型包括法规、条款、危险源、作业、设备、防护用品、责任岗位、整改措施。格式：{\"entities\":[{\"name\":\"\",\"type\":\"\"}],\"relations\":[{\"head\":\"\",\"relation\":\"\",\"tail\":\"\"}]}",
        )
        if result:
            return result.get("entities", []), result.get("relations", [])
    return _rule_extract(text)


def build_graph(chunks: Iterable[dict], use_llm: bool = False) -> dict:
    entities: dict[str, dict] = {}
    relations: list[dict] = []
    for chunk in chunks:
        context = f"{chunk.get('title', '')} {chunk.get('document_no', '')} {chunk['text']}"
        ens, rels = extract_entities(context, use_llm=use_llm)
        document_name = chunk.get("title", "未命名资料")
        # 条款号脱离法规名称时无法定位；展示名绑定所属文件，原条款号保留为搜索别名。
        for entity in ens:
            raw_name = str(entity.get("name", "")).strip()
            if re.fullmatch(r"第[一二三四五六七八九十百千万零〇0-9]+条", raw_name):
                entity["name"] = f"{document_name} · {raw_name}"
                entity["aliases"] = [raw_name]
        clause_aliases = {
            alias: entity["name"]
            for entity in ens
            for alias in entity.get("aliases", [])
        }
        for relation in rels:
            relation["head"] = clause_aliases.get(relation.get("head"), relation.get("head"))
            relation["tail"] = clause_aliases.get(relation.get("tail"), relation.get("tail"))
        ens.append({"name": document_name, "type": "DOCUMENT"})
        for entity in ens:
            if entity.get("name") and entity["name"] != document_name:
                rels.append({"head": document_name, "relation": "涉及", "tail": entity["name"]})
        for entity in ens:
            name = entity.get("name", "").strip()
            if not name:
                continue
            aliases = entity.get("aliases", [])
            if not isinstance(aliases, list):
                aliases = [str(aliases)] if aliases else []
            row = entities.setdefault(name, {
                "name": name,
                "type": entity.get("type", "OTHER"),
                "source_chunks": [],
                "aliases": [],
            })
            if chunk["chunk_id"] not in row["source_chunks"]:
                row["source_chunks"].append(chunk["chunk_id"])
            for alias in aliases:
                alias = str(alias).strip()
                if alias and alias != name and alias not in row["aliases"]:
                    row["aliases"].append(alias)
        for relation in rels:
            if relation.get("head") and relation.get("relation") and relation.get("tail"):
                relations.append({**relation, "source_chunk": chunk["chunk_id"]})
    unique = {(r["head"], r["relation"], r["tail"], r["source_chunk"]): r for r in relations}
    return {"entities": list(entities.values()), "relations": list(unique.values())}
