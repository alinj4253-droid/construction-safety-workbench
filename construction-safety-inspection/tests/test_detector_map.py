"""hat/person 原始类别 -> 佩戴判定 的映射逻辑单测。

覆盖三个核心规则，防止"戴帽工人被误标为未佩戴"的回归：
1. person 框与 hat 框重叠 -> 佩戴（cls 0）
2. person 框与所有 hat 框不重叠 -> 未佩戴（cls 1）
3. 孤立 hat 框（无对应 person）-> 不计入人数
"""

from app.detection.detector import map_hat_person


def test_person_overlapping_hat_is_wearing():
    # person 与 hat 几乎同框（脚手架视频实测 IoU≈0.90 的形态）
    raw = [
        (0, 0.6, (100, 100, 200, 220)),   # hat
        (1, 0.7, (102, 107, 198, 224)),   # person 与 hat 高度重叠
    ]
    det = map_hat_person(raw)
    assert len(det) == 1
    assert det[0].cls_id == 0  # 佩戴


def test_person_without_hat_is_not_wearing():
    raw = [
        (0, 0.6, (500, 100, 600, 220)),   # 远处的 hat
        (1, 0.7, (100, 300, 200, 500)),   # 与该 hat 完全不重叠的 person
    ]
    det = map_hat_person(raw)
    assert len(det) == 1
    assert det[0].cls_id == 1  # 未佩戴


def test_isolated_hat_not_counted():
    # 只有放置的安全帽、没有人：不计入任何人数
    raw = [(0, 0.8, (10, 10, 60, 60))]
    det = map_hat_person(raw)
    assert det == []


def test_mixed_frame_counts():
    raw = [
        (0, 0.6, (100, 100, 200, 220)),   # hat A
        (1, 0.7, (102, 107, 198, 224)),   # person A -> 佩戴
        (1, 0.5, (700, 400, 800, 700)),   # person B -> 未佩戴
    ]
    det = map_hat_person(raw)
    on = sum(1 for d in det if d.cls_id == 0)
    off = sum(1 for d in det if d.cls_id == 1)
    assert (on, off) == (1, 1)


def test_small_hat_box_inside_large_person_is_wearing():
    # 真实检测中 hat 框通常只覆盖头部，和全身 person 框的 IoU 很低，
    # 但帽子中心落在人员框上半部，应判定为佩戴。
    raw = [
        (0, 0.55, (145, 105, 175, 135)),
        (1, 0.80, (100, 100, 220, 500)),
    ]
    det = map_hat_person(raw)
    assert len(det) == 1
    assert det[0].cls_id == 0
