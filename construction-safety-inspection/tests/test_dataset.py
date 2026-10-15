"""数据集转换测试（不依赖真实数据集，用合成 XML）。"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.prepare_dataset import prepare, voc_to_yolo  # noqa: E402


def _write_voc_xml(path: Path, w=640, h=480, objs=(("hat", 10, 10, 100, 100),)):
    ann = ET.Element("annotation")
    size = ET.SubElement(ann, "size")
    ET.SubElement(size, "width").text = str(w)
    ET.SubElement(size, "height").text = str(h)
    for name, x1, y1, x2, y2 in objs:
        obj = ET.SubElement(ann, "object")
        ET.SubElement(obj, "name").text = name
        bnd = ET.SubElement(obj, "bndbox")
        for tag, val in (("xmin", x1), ("ymin", y1), ("xmax", x2), ("ymax", y2)):
            ET.SubElement(bnd, tag).text = str(val)
    ET.ElementTree(ann).write(path, encoding="utf-8")


def test_voc_to_yolo_values():
    xml = Path(__file__).parent / "_tmp_test.xml"
    _write_voc_xml(xml, objs=(("hat", 0, 0, 320, 240),))
    lines = voc_to_yolo(xml)
    assert lines == ["0 0.250000 0.250000 0.500000 0.500000"]
    xml.unlink()


def test_class_mapping():
    xml = Path(__file__).parent / "_tmp_test2.xml"
    _write_voc_xml(xml, objs=(("person", 0, 0, 100, 100), ("hat", 0, 0, 100, 100)))
    lines = voc_to_yolo(xml)
    assert len(lines) == 2
    assert any(l.startswith("1 ") for l in lines)   # person -> 1
    assert any(l.startswith("0 ") for l in lines)   # hat -> 0
    xml.unlink()


def test_unknown_class_ignored():
    xml = Path(__file__).parent / "_tmp_test3.xml"
    _write_voc_xml(xml, objs=(("vest", 0, 0, 100, 100),))
    assert voc_to_yolo(xml) == []
    xml.unlink()


def test_prepare_end_to_end(tmp_path):
    # 合成 10 张"图片"+ 标注
    src = tmp_path / "src"
    (src / "annotations").mkdir(parents=True)
    (src / "images").mkdir(parents=True)
    for i in range(10):
        _write_voc_xml(src / "annotations" / f"{i}.xml")
        (src / "images" / f"{i}.jpg").write_bytes(b"\xff\xd8\xff\xe0 fake jpg")
    out = tmp_path / "out"
    stats = prepare(src, out)
    assert stats["total"] == 10
    assert stats["train"] + stats["val"] == 10
    assert stats["hat"] == 10
    assert (out / "data.yaml").exists()
    train_imgs = list((out / "images" / "train").glob("*.jpg"))
    val_imgs = list((out / "images" / "val").glob("*.jpg"))
    assert len(train_imgs) + len(val_imgs) == 10
    # 每张图都有对应 label
    for img in train_imgs + val_imgs:
        split = img.parent.name
        assert (out / "labels" / split / (img.stem + ".txt")).exists()


def test_prepare_skips_missing_image(tmp_path):
    src = tmp_path / "src"
    (src / "annotations").mkdir(parents=True)
    (src / "images").mkdir(parents=True)
    _write_voc_xml(src / "annotations" / "a.xml")   # 无对应 jpg
    _write_voc_xml(src / "annotations" / "b.xml")
    (src / "images" / "b.jpg").write_bytes(b"x")
    stats = prepare(src, tmp_path / "out2")
    assert stats["total"] == 1
    assert stats["skipped"] == 1
