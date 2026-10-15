"""数据集预处理：支持 SHWD(VOC/XML) 与 COCO(Roboflow) 两种格式 → YOLO 格式。

自动探测：
- 目录下有 annotations/*.xml + images/*.jpg  → SHWD VOC 格式
- 目录下有 train/_annotations.coco.json 等   → Roboflow COCO 格式

类别映射（与 config.CLASS_NAMES 一致）：
  佩戴安全帽(hat/helmet/hardhat) -> 0
  未佩戴安全帽(head/person)      -> 1
"""

from __future__ import annotations

import json
import random
import shutil
import sys
from pathlib import Path

import xml.etree.ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

CLASS_MAP = {"hat": 0, "person": 1}
TRAIN_RATIO = 0.9

# COCO 类别名到统一类别的映射（大小写不敏感，包含匹配）
# 注意：有的数据集把 supercategory（如 '-WithHelmet-WithOutHelmet-'）也当类别名传进来，必须忽略
COCO_HELMET_NAMES = {"helmet", "hardhat", "hard hat", "hat", "safety helmet", "helmet on", "with helmet", "helmet(head)"}
COCO_HEAD_NAMES = {"head", "person", "no helmet", "nohelmet", "no-helmet", "without helmet", "bare head"}


def voc_to_yolo(xml_path: Path) -> list[str]:
    """单个 VOC XML 转 YOLO 标注行（归一化 cx cy w h）。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    size = root.find("size")
    w = int(size.find("width").text)
    h = int(size.find("height").text)
    lines = []
    for obj in root.iter("object"):
        name = obj.find("name").text.strip().lower()
        if name not in CLASS_MAP:
            continue
        cls_id = CLASS_MAP[name]
        bnd = obj.find("bndbox")
        x1 = float(bnd.find("xmin").text)
        y1 = float(bnd.find("ymin").text)
        x2 = float(bnd.find("xmax").text)
        y2 = float(bnd.find("ymax").text)
        cx = min(max((x1 + x2) / 2 / w, 0.0), 1.0)
        cy = min(max((y1 + y2) / 2 / h, 0.0), 1.0)
        bw = min(max((x2 - x1) / w, 0.0), 1.0)
        bh = min(max((y2 - y1) / h, 0.0), 1.0)
        lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    return lines


def _norm_coco_cat(name: str) -> int | None:
    """COCO 类别名 -> 统一类别 id。"""
    n = name.strip().lower()
    if n in COCO_HELMET_NAMES:
        return 0
    if n in COCO_HEAD_NAMES:
        return 1
    # 忽略同时包含两义的混合类别名（如 '-withhelmet-withouthelmet-'）
    if "withhelmet" in n.replace(" ", "") and "withouthelmet" in n.replace(" ", ""):
        return None
    # 包含式匹配兜底
    if "nohelmet" in n.replace(" ", "") or "without" in n:
        return 1
    if "helmet" in n or "hardhat" in n or n == "hat":
        return 0
    if "head" in n or "person" in n:
        return 1
    return None


def _coco_split_to_yolo(img_dir: Path, ann_json: Path, out_root: Path, split: str,
                        stats: dict) -> None:
    """一个 COCO split（train/valid）转成 YOLO images/labels。"""
    data = json.loads(ann_json.read_text(encoding="utf-8"))
    # 类别映射表
    cat_map = {}
    for cat in data.get("categories", []):
        cid = _norm_coco_cat(cat["name"])
        if cid is not None:
            cat_map[cat["id"]] = cid

    # 图片 id -> 文件名与尺寸
    imgs = {im["id"]: im for im in data.get("images", [])}

    # 按 image_id 聚合标注
    by_img: dict[int, list[str]] = {}
    for ann in data.get("annotations", []):
        if ann.get("category_id") not in cat_map:
            continue
        im = imgs.get(ann.get("image_id"))
        if im is None:
            continue
        x, y, w, h = ann["bbox"]  # COCO: 左上角 + 宽高（像素）
        W, H = im["width"], im["height"]
        cx = min(max((x + w / 2) / W, 0.0), 1.0)
        cy = min(max((y + h / 2) / H, 0.0), 1.0)
        bw = min(max(w / W, 0.0), 1.0)
        bh = min(max(h / H, 0.0), 1.0)
        cls_id = cat_map[ann["category_id"]]
        by_img.setdefault(ann["image_id"], []).append(
            f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"
        )

    (out_root / "images" / split).mkdir(parents=True, exist_ok=True)
    (out_root / "labels" / split).mkdir(parents=True, exist_ok=True)

    for im_id, im in imgs.items():
        lines = by_img.get(im_id)
        if not lines:
            continue  # 无有效目标，跳过
        src_img = img_dir / im["file_name"]
        if not src_img.exists():
            stats["skipped"] += 1
            continue
        stats[split] = stats.get(split, 0) + 1
        stats["total"] += 1
        stats["hat"] += sum(1 for ln in lines if ln.startswith("0 "))
        stats["person"] += sum(1 for ln in lines if ln.startswith("1 "))
        shutil.copy2(src_img, out_root / "images" / split / src_img.name)
        (out_root / "labels" / split / f"{src_img.stem}.txt").write_text(
            "\n".join(lines), encoding="utf-8"
        )


def prepare_coco(src_root: Path, out_root: Path) -> dict:
    """Roboflow COCO 数据集转 YOLO。"""
    stats = {"total": 0, "train": 0, "val": 0, "skipped": 0, "hat": 0, "person": 0}
    handled = False
    for split_dir in sorted(src_root.rglob("*_annotations.coco.json")):
        parent = split_dir.parent
        split = "val" if parent.name.lower().startswith(("valid", "val", "test")) else "train"
        _coco_split_to_yolo(parent, split_dir, out_root, split, stats)
        handled = True
    if not handled:
        raise FileNotFoundError(f"未在 {src_root} 找到 *_annotations.coco.json")
    return stats


def prepare_voc(src_root: Path, out_root: Path, seed: int = 42) -> dict:
    """SHWD VOC 数据集转 YOLO。"""
    candidates = [src_root, src_root / "Safety-Helmet-Wearing-Dataset-master"]
    src = next((c for c in candidates if (c / "annotations").exists()), None)
    if src is None:
        raise FileNotFoundError(f"未找到 VOC 标注目录，尝试过：{candidates}")

    xml_dir = src / "annotations"
    img_dir = src / "images"
    for split in ("train", "val"):
        (out_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_root / "labels" / split).mkdir(parents=True, exist_ok=True)

    xmls = sorted(xml_dir.glob("*.xml"))
    random.Random(seed).shuffle(xmls)
    n_train = int(len(xmls) * TRAIN_RATIO)

    stats = {"total": 0, "train": 0, "val": 0, "skipped": 0, "hat": 0, "person": 0}
    for i, xml_path in enumerate(xmls):
        img_file = img_dir / f"{xml_path.stem}.jpg"
        if not img_file.exists():
            stats["skipped"] += 1
            continue
        lines = voc_to_yolo(xml_path)
        if not lines:
            stats["skipped"] += 1
            continue
        split = "train" if i < n_train else "val"
        stats[split] += 1
        stats["total"] += 1
        stats["hat"] += sum(1 for ln in lines if ln.startswith("0 "))
        stats["person"] += sum(1 for ln in lines if ln.startswith("1 "))
        shutil.copy2(img_file, out_root / "images" / split / img_file.name)
        (out_root / "labels" / split / f"{xml_path.stem}.txt").write_text(
            "\n".join(lines), encoding="utf-8"
        )
    return stats


def prepare(src_root: Path, out_root: Path, seed: int = 42) -> dict:
    """自动探测格式并转换。"""
    # COCO 优先（更常见的 Roboflow 导出）
    if list(src_root.rglob("*_annotations.coco.json")):
        stats = prepare_coco(src_root, out_root)
    else:
        stats = prepare_voc(src_root, out_root, seed)
    _write_yaml(out_root)
    return stats


def _write_yaml(out_root: Path) -> None:
    yaml_text = (
        f"path: {out_root.resolve().as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n"
        "  0: hat\n"
        "  1: person\n"
    )
    (out_root / "data.yaml").write_text(yaml_text, encoding="utf-8")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "data" / "hf_helmet"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else PROJECT_ROOT / "data" / "shwd_yolo"
    result = prepare(src, out)
    print(f"转换完成：总计 {result['total']} 张（train {result['train']} / val {result['val']}），"
          f"跳过 {result['skipped']} 张")
    print(f"目标数：hat(戴帽) {result['hat']}，person(未戴帽) {result['person']}")
    print(f"data.yaml 已生成：{out / 'data.yaml'}")

