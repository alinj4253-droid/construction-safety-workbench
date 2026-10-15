"""Agent 层测试：知识库加载 + LLM mock 流水线。"""

import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import report_writer, safety_analyst  # noqa: E402
from app.detection import ledger  # noqa: E402
from app.detection.detector import Detection, FrameResult  # noqa: E402
from app.detection.rules import judge_frame  # noqa: E402


def test_load_kb_real_regulations():
    kb = safety_analyst.load_kb()
    # 已核实的真实条文必须出现在知识库文本里
    assert "安全生产法" in kb
    assert "第四十五条" in kb
    assert "JGJ 59-2011" in kb


def test_kb_json_schema():
    data = json.loads((Path(__file__).parents[1] / "kb" / "regulations.json")
                      .read_text(encoding="utf-8"))
    assert isinstance(data["clauses"], list) and len(data["clauses"]) >= 3
    for c in data["clauses"]:
        assert all(k in c for k in ("regulation", "clause", "text", "tags"))


def _fill_ledger():
    """向当前 config 指向的台账写入三条记录。"""
    for off, on in ((1, 4), (2, 2), (3, 1)):
        dets = [Detection(cls_id=1, conf=0.8, xyxy=(0, 0, 5, 5))] * off
        dets += [Detection(cls_id=0, conf=0.9, xyxy=(0, 0, 5, 5))] * on
        frame = FrameResult(image=None, detections=dets, helmet_on=on, helmet_off=off)
        v = judge_frame(frame, source="test_cam")
        ledger.insert_violation(v)


def test_analyze_empty_ledger_local_fallback(tmp_db):
    """台账为空时走本地兜底，不调 LLM。"""
    result = safety_analyst.analyze()
    assert result["_local"] is True
    assert result["risk_level"] == "低"


def test_analyze_parses_llm_json(tmp_db):
    _fill_ledger()
    fake = json.dumps({
        "risk_level": "中",
        "risk_level_reason": "近3日多次违规",
        "patterns": ["上午时段违规集中"],
        "regulation_refs": ["安全生产法第四十五条"],
        "suggestions": ["加强班前教育"],
    }, ensure_ascii=False)
    with mock.patch.object(safety_analyst, "chat", return_value=fake):
        result = safety_analyst.analyze()
    assert result["risk_level"] == "中"
    assert "安全生产法第四十五条" in result["regulation_refs"]


def test_analyze_tolerates_llm_wrapped_json(tmp_db):
    _fill_ledger()
    fake = ('模型思考中...\n```json\n{"risk_level": "高", "risk_level_reason": "x", '
            '"patterns": [], "regulation_refs": [], "suggestions": []}\n```')
    with mock.patch.object(safety_analyst, "chat", return_value=fake):
        result = safety_analyst.analyze()
    assert result["risk_level"] == "高"


def test_analyze_invalid_json_falls_back(tmp_db):
    _fill_ledger()
    with mock.patch.object(safety_analyst, "chat", return_value="完全不是JSON的内容"):
        result = safety_analyst.analyze()
    assert result["risk_level"] == "未知"
    assert result["_raw"] == "完全不是JSON的内容"


def test_write_report_calls_main_model(tmp_db):
    _fill_ledger()
    analysis = {"risk_level": "中", "risk_level_reason": "r", "patterns": ["p1"],
                "regulation_refs": ["安全生产法第四十五条"], "suggestions": ["s1"]}
    calls = {}

    def fake_chat(system, user, model=None, **kw):
        calls["model"] = model
        calls["prompt_has_analysis"] = "安全生产法" in user or True
        return "# 施工现场安全帽佩戴巡检报告\n内容..."

    with mock.patch.object(report_writer, "chat", side_effect=fake_chat):
        md = report_writer.write_report(analysis)
    assert "巡检报告" in md
    assert calls["model"], "应调用主力模型"


def test_prompt_contains_ledger_data(tmp_db):
    """喂给报告 Agent 的 prompt 必须包含台账统计与法规条文。"""
    _fill_ledger()
    captured = {}

    def fake_chat(system, user, model=None, **kw):
        captured["user"] = user
        return "# 巡检报告"

    analysis = {"risk_level": "低", "risk_level_reason": "r", "patterns": [],
                "regulation_refs": [], "suggestions": []}
    with mock.patch.object(report_writer, "chat", side_effect=fake_chat):
        report_writer.write_report(analysis)
    assert "总次数=3" in captured["user"]        # 台账统计注入
    assert "安全生产法" in captured["user"]        # 法规条文注入
    assert "风险等级" in captured["user"] or "risk_level" in captured["user"]
