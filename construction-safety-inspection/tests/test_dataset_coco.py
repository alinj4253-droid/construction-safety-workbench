"""COCO(Roboflow) → YOLO 转换测试。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.prepare_dataset import prepare  # noqa: E402


def _make_coco(root: Path):
    """构造一个最小 Roboflow COCO 数据集（train 2 图 / valid 1 图）。"""
    tr = root / "train"
    va = root / "valid"
    tr.mkdir(parents=True)
    va.mkdir(parents=True)
    # 假图片（YOLO 训练时才读内容，转换阶段只复制）
    for name in ("a.jpg", "b.jpg"):
        (tr / name).write_bytes(b"\xff\xd8 fake")
    (va / "c.jpg").write_bytes(b"\xff\xd8 fake")

    def coco_json(imgs_and_anns):
        images, annotations = [], []
        ann_id = 1
        for im_id, (fname, w, h, boxes) in enumerate(imgs_and_anns, start=1):
            images.append({"id": im_id, "file_name": fname, "width": w, "height": h})
            for cat, x, y, bw, bh in boxes:
                annotations.append({
                    "id": ann_id, "image_id": im_id, "category_id": cat,
                    "bbox": [x, y, bw, bh], "iscrowd": 0, "area": bw * bh,
                })
                ann_id += 1
        return {"images": images, "annotations": annotations,
                "categories": [{"id": 1, "name": "helmet"}, {"id": 2, "name": "head"}]}

    (tr / "_annotations.coco.json").write_text(
        json.dumps(coco_json([
            ("a.jpg", 640, 480, [(1, 10, 10, 100, 100), (2, 200, 100, 50, 50)]),
            ("b.jpg", 640, 480, [(1, 0, 0, 320, 240)]),
        ])), encoding="utf-8")
    (va / "_annotations.coco.json").write_text(
        json.dumps(coco_json([
            ("c.jpg", 640, 480, [(2, 5, 5, 60, 60)]),
        ])), encoding="utf-8")


def test_coco_end_to_end(tmp_path):
    src = tmp_path / "coco_src"
    _make_coco(src)
    out = tmp_path / "out"
    stats = prepare(src, out)
    assert stats["total"] == 3
    assert stats["train"] == 2
    assert stats["val"] == 1
    assert stats["hat"] == 2       # 两个 helmet 框
    assert stats["person"] == 2    # 两个 head 框
    assert (out / "data.yaml").exists()
    # label 内容校验：a.jpg 有两行，类别 0 和 1
    label_a = (out / "labels" / "train" / "a.txt").read_text().splitlines()
    assert len(label_a) == 2
    assert {ln.split()[0] for ln in label_a} == {"0", "1"}


def test_coco_unknown_category_skipped(tmp_path):
    src = tmp_path / "coco_src2"
    tr = src / "train"
    tr.mkdir(parents=True)
    (tr / "x.jpg").write_bytes(b"\xff\xd8 fake")
    data = {
        "images": [{"id": 1, "file_name": "x.jpg", "width": 100, "height": 100}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 9,
                         "bbox": [0, 0, 10, 10], "iscrowd": 0, "area": 100}],
        "categories": [{"id": 9, "name": "glove"}],
    }
    (tr / "_annotations.coco.json").write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out2"
    stats = prepare(src, out)
    assert stats["total"] == 0     # 未知类别 → 无有效目标 → 跳过


def test_coco_bbox_normalization(tmp_path):
    """bbox (10,10,100,100) on 640x480 → cx=60/640, cy=60/480。"""
    src = tmp_path / "coco_src3"
    tr = src / "train"
    tr.mkdir(parents=True)
    (tr / "n.jpg").write_bytes(b"\xff\xd8 fake")
    data = {
        "images": [{"id": 1, "file_name": "n.jpg", "width": 640, "height": 480}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1,
                         "bbox": [10, 10, 100, 100], "iscrowd": 0, "area": 10000}],
        "categories": [{"id": 1, "name": "helmet"}],
    }
    (tr / "_annotations.coco.json").write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out3"
    prepare(src, out)
    line = (out / "labels" / "train" / "n.txt").read_text().strip()
    parts = line.split()
    assert parts[0] == "0"
    assert abs(float(parts[1]) - 60 / 640) < 1e-4
    assert abs(float(parts[2]) - 60 / 480) < 1e-4
    assert abs(float(parts[3]) - 100 / 640) < 1e-4
    assert abs(float(parts[4]) - 100 / 480) < 1e-4
