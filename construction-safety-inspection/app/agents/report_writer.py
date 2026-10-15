"""报告撰写 Agent（主力模型）：基于分析结果生成《安全巡检报告》。

职责（多智能体分工中的"报告撰写"角色）：
接收安全分析 Agent 的结构化输出 + 台账统计数据，
撰写一份可直接交付项目安全总监的巡检报告（Markdown）。
"""

from __future__ import annotations

from datetime import datetime

from app import config
from app.agents.llm_client import chat
from app.detection import ledger

SYSTEM_PROMPT = """你是建筑工程公司的安全巡检报告撰写专家。
你将收到：视觉检测系统的台账统计、安全分析 Agent 的结构化分析结果、相关法规条文。
请撰写一份《施工现场安全帽佩戴巡检报告》，Markdown 格式，结构如下：

# 施工现场安全帽佩戴巡检报告
- 巡检时间：{用台账数据}
- 巡检方式：AI 视觉检测系统自动巡检 + 人工复核
## 一、巡检概况
（检测数据汇总：违规次数、人次、严重度分布）
## 二、主要问题
（基于分析结果的 patterns，逐条展开）
## 三、法规依据
（引用 regulation_refs 对应条款，条款号和标准号必须准确）
## 四、风险研判
（risk_level 及理由）
## 五、整改建议
（suggestions 逐条展开，落实到责任岗位和时间要求）
## 六、复查安排
（给出建议复查时间与复查方式）

写作要求：
1. 语言正式、克制，符合工程安全管理文风
2. 所有数据必须来自我给你的材料，禁止编造
3. 法规引用保留标准号与条款号
4. 篇幅 500-800 字"""


def write_report(analysis: dict) -> str:
    """基于分析结果生成巡检报告 Markdown。

    :param analysis: 安全分析 Agent 的输出
    :return: Markdown 报告文本
    """
    stat = ledger.stats()
    records = ledger.list_violations(limit=20)
    records_text = "\n".join(
        f"- {r['ts']} | {r['source']} | 未戴帽 {r['helmet_off']} 人 | {r['severity']}"
        for r in records
    ) or "（无违规记录）"

    from app.agents.safety_analyst import load_kb

    user_prompt = (
        f"## 生成时间\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"## 台账统计\n总次数={stat['count']}，累计未戴帽人次={stat['persons']}，"
        f"严重次数={stat['severe']}，最近违规={stat['latest']}\n\n"
        f"## 最近违规记录\n{records_text}\n\n"
        f"## 安全分析 Agent 输出\n{analysis}\n\n"
        f"## 法规条文\n{load_kb()}\n\n请撰写巡检报告。"
    )
    return chat(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        model=config.LLM_MAIN_MODEL,
        temperature=0.4,
        max_tokens=2500,
    )
