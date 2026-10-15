"""安全分析 Agent（快模型）：分析违规台账数据，输出结构化风险分析。

职责（多智能体分工中的"安全分析"角色）：
1. 汇总违规台账的统计特征（频次、时段、严重度分布）
2. 结合法规知识库，指出违规行为对应的具体条款
3. 给出风险研判与整改建议要点

输出 JSON 结构，供报告撰写 Agent 二次加工。
"""

from __future__ import annotations

import json
from pathlib import Path

from app import config
from app.agents.llm_client import chat
from app.detection import ledger

SYSTEM_PROMPT = """你是建筑工地安全管理部门的资深安全分析工程师。
你将收到一份施工现场安全帽佩戴违规检测台账（由视觉检测系统自动采集）和相关法规条文。
请基于数据完成风险分析，输出严格的 JSON（不要任何多余文字）：
{
  "risk_level": "低|中|高",
  "risk_level_reason": "判定理由（引用数据）",
  "patterns": ["违规规律分析，如时段/频次/严重度特征，没有明显规律就如实说"],
  "regulation_refs": ["引用的法规条款号与标准名，必须来自提供的法规条文"],
  "suggestions": ["针对性整改建议，3-5条，要具体可执行"]
}
要求：只依据数据说话，不编造台账中不存在的信息；法规引用必须来自我给你的条文。"""


def load_kb() -> str:
    """读取法规知识库，拼成提示词文本。"""
    kb_path = config.KB_DIR / "regulations.json"
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    lines = []
    for c in data["clauses"]:
        lines.append(
            f"【{c['regulation']} {c['clause']}】{c['text']}"
        )
    return "\n".join(lines)


def analyze(limit: int = 100) -> dict:
    """读取台账并调用快模型做安全分析。

    :param limit: 最多取最近多少条记录
    :return: 结构化分析结果 dict
    :raises: LLMError 调用失败 / 台账为空时返回本地兜底分析
    """
    records = ledger.list_violations(limit=limit)
    stat = ledger.stats()
    if stat["count"] == 0:
        return {
            "risk_level": "低",
            "risk_level_reason": "台账为空，暂无违规记录，风险水平判定为低（仅代表当前无数据，不代表现场无风险）。",
            "patterns": ["暂无数据，无法进行规律分析。建议持续开启摄像头巡检积累数据。"],
            "regulation_refs": [],
            "suggestions": ["将摄像头对准施工现场主要出入口与作业面，持续采集数据。"],
            "_local": True,
        }

    records_text = "\n".join(
        f"{i+1}. 时间={r['ts']} 来源={r['source']} 未戴帽人数={r['helmet_off']} "
        f"戴帽人数={r['helmet_on']} 置信度={r['conf_min']} 严重度={r['severity']}"
        for i, r in enumerate(records[:50])  # 控制 prompt 长度
    )
    stat_text = (
        f"总违规次数={stat['count']}，累计未戴帽人次={stat['persons']}，"
        f"严重（多人同时未戴）次数={stat['severe']}，最近违规时间={stat['latest']}"
    )
    user_prompt = (
        f"## 台账统计\n{stat_text}\n\n## 最近违规记录（最多50条）\n{records_text}\n\n"
        f"## 法规条文\n{load_kb()}\n\n请输出 JSON 分析。"
    )

    raw = chat(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        model=config.LLM_FAST_MODEL,
        temperature=0.2,
        max_tokens=1200,
    )
    # 容错：截取首个 { 到最后一个 } 之间的内容再解析
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return {
            "risk_level": "未知",
            "risk_level_reason": "模型输出解析失败，原文如下",
            "patterns": [],
            "regulation_refs": [],
            "suggestions": [],
            "_raw": raw,
        }
