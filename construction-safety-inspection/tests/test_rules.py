"""违规判定规则单元测试。"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.detection.detector import Detection, FrameResult  # noqa: E402
from app.detection.rules import judge_frame  # noqa: E402


def _frame(helmet_on=0, helmet_off=0, conf=0.9):
    dets = []
    for _ in range(helmet_on):
        dets.append(Detection(cls_id=0, conf=conf, xyxy=(0, 0, 10, 10)))
    for _ in range(helmet_off):
        dets.append(Detection(cls_id=1, conf=conf, xyxy=(0, 0, 10, 10)))
    return FrameResult(image=None, detections=dets,
                       helmet_on=helmet_on, helmet_off=helmet_off)


def test_no_violation_when_all_helmets_on():
    assert judge_frame(_frame(helmet_on=5)) is None


def test_no_detections():
    assert judge_frame(_frame()) is None


def test_single_violation_general_severity():
    v = judge_frame(_frame(helmet_on=3, helmet_off=1), source="测试图片.jpg")
    assert v is not None
    assert v.helmet_off == 1
    assert v.severity == "一般"


def test_multi_violation_severe():
    v = judge_frame(_frame(helmet_on=1, helmet_off=3), source="cam")
    assert v.severity == "严重"
    assert v.helmet_off == 3


def test_low_confidence_filtered():
    frame = _frame(helmet_off=2, conf=0.20)
    v = judge_frame(frame, conf_threshold=0.35)
    assert v is None  # 低于阈值不计违规


def test_conf_min_recorded():
    frame = FrameResult(
        image=None,
        detections=[
            Detection(cls_id=1, conf=0.42, xyxy=(0, 0, 1, 1)),
            Detection(cls_id=1, conf=0.88, xyxy=(0, 0, 1, 1)),
        ],
        helmet_on=0, helmet_off=2,
    )
    v = judge_frame(frame, conf_threshold=0.35)
    assert abs(v.conf_min - 0.42) < 1e-6


def test_ts_and_to_row():
    now = datetime(2026, 10, 12, 15, 0, 0)
    v = judge_frame(_frame(helmet_off=1), source="x", now=now)
    assert v.ts == "2026-10-12T15:00:00"
    row = v.to_row()
    assert row[2] == 1 and row[5] == "一般"
