"""违规台账 CRUD 与统计测试。"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.detection import ledger  # noqa: E402
from app.detection.detector import Detection, FrameResult  # noqa: E402
from app.detection.rules import judge_frame  # noqa: E402


def _mk_violation(helmet_off=1, helmet_on=2, severity_auto=True):
    dets = [Detection(cls_id=1, conf=0.9, xyxy=(0, 0, 5, 5)) for _ in range(helmet_off)]
    dets += [Detection(cls_id=0, conf=0.9, xyxy=(0, 0, 5, 5)) for _ in range(helmet_on)]
    frame = FrameResult(image=None, detections=dets,
                        helmet_on=helmet_on, helmet_off=helmet_off)
    return judge_frame(frame, source="unit_test")


def test_init_idempotent(tmp_db):
    ledger.init_db(tmp_db)  # 重复初始化不报错
    ledger.init_db(tmp_db)


def test_insert_and_list(tmp_db):
    v = _mk_violation(helmet_off=1, helmet_on=3)
    vid = ledger.insert_violation(v, db_path=tmp_db)
    assert vid >= 1
    rows = ledger.list_violations(db_path=tmp_db)
    assert len(rows) == 1
    assert rows[0]["helmet_off"] == 1
    assert rows[0]["helmet_on"] == 3
    assert rows[0]["severity"] == "一般"


def test_stats(tmp_db):
    ledger.insert_violation(_mk_violation(helmet_off=1), db_path=tmp_db)
    ledger.insert_violation(_mk_violation(helmet_off=3), db_path=tmp_db)  # 严重
    s = ledger.stats(db_path=tmp_db)
    assert s["count"] == 2
    assert s["persons"] == 4
    assert s["severe"] == 1
    assert s["latest"] is not None


def test_clear(tmp_db):
    ledger.insert_violation(_mk_violation(), db_path=tmp_db)
    n = ledger.clear(db_path=tmp_db)
    assert n == 1
    assert ledger.stats(db_path=tmp_db)["count"] == 0


def test_empty_stats(tmp_db):
    s = ledger.stats(db_path=tmp_db)
    assert s["count"] == 0 and s["persons"] == 0 and s["severe"] == 0


def test_order_desc(tmp_db):
    from datetime import timedelta
    base = datetime(2026, 10, 12, 10, 0, 0)
    for i in range(3):
        v = _mk_violation()
        v.ts = (base + timedelta(hours=i)).isoformat(timespec="seconds")
        ledger.insert_violation(v, db_path=tmp_db)
    rows = ledger.list_violations(db_path=tmp_db)
    assert rows[0]["ts"] > rows[-1]["ts"]
