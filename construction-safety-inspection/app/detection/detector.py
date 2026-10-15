"""YOLO 安全帽检测器：加载训练好的权重，对图片/视频帧进行推理。

对外暴露统一的 detect_frame() 接口，供界面（图片/视频两个入口）复用。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app import config


@dataclass
class Detection:
    """单个检测目标。"""

    cls_id: int          # 类别 id（0=佩戴安全帽 1=未佩戴安全帽）
    conf: float          # 置信度
    xyxy: tuple          # 边界框 (x1, y1, x2, y2)


def _iou(a: tuple, b: tuple) -> float:
    """两个 (x1, y1, x2, y2) 框的交并比。"""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _hat_matches_person(person: tuple, hat: tuple, iou_thr: float) -> bool:
    """判断帽子框是否属于人员框。

    训练数据中的 hat 框通常只覆盖头部，而 person 框可能覆盖全身，
    直接使用 IoU 会把真实佩戴者误判为未佩戴。因此保留 IoU 规则，
    同时增加“帽子中心位于人员框上半部”的空间关联规则。
    """
    if _iou(person, hat) > iou_thr:
        return True

    px1, py1, px2, py2 = person
    hx1, hy1, hx2, hy2 = hat
    pw, ph = max(1.0, px2 - px1), max(1.0, py2 - py1)
    hcx, hcy = (hx1 + hx2) / 2.0, (hy1 + hy2) / 2.0

    # 给人员框左右和顶部留少量余量，适配帽子框略微超出人员框的情况。
    in_horizontal = px1 - 0.2 * pw <= hcx <= px2 + 0.2 * pw
    in_head_zone = py1 - 0.2 * ph <= hcy <= py1 + 0.5 * ph
    return in_horizontal and in_head_zone


def map_hat_person(raw: list[tuple[int, float, tuple]],
                   iou_thr: float = 0.3,
                   person_conf_thr: float | None = None) -> list[Detection]:
    """把 SHWD 权重原始两类（0=hat 安全帽 / 1=person 人）映射为佩戴判定。

    权重训练自 SHWD 数据集，只有"安全帽"与"人"两个类别，并不直接输出
    "未佩戴"。旧实现把每个 person 框都当作"未佩戴"，导致戴帽工人同时被
    计为"佩戴+未佩戴"并画出错误的违规框。正确规则：

    - person 框与某个 hat 框重叠，或帽子中心位于该人员框上半部
      -> 该人佩戴安全帽（cls 0）
    - person 框与所有 hat 框都不重叠     -> 该人未佩戴安全帽（cls 1）
    - 没有对应 person 的孤立 hat 框      -> 不计入人数（可能是放置的安全帽）
    - person 置信度低于 person_conf_thr  -> 丢弃（不画框、不计数）

    hat 框不受 person_conf_thr 限制：低置信度的帽子也参与匹配，
    避免"帽子检出置信度偏低 -> 戴帽者被误判未佩戴"。

    :param raw: [(原始类别id, 置信度, xyxy), ...]
    :param iou_thr: person 与 hat 判定为同一目标的重叠阈值
    :param person_conf_thr: person 框计入判定的最低置信度（None=不过滤）
    """
    hats = [(conf, xyxy) for cid, conf, xyxy in raw if cid == 0]
    persons = [(conf, xyxy) for cid, conf, xyxy in raw if cid == 1]
    if person_conf_thr is not None:
        persons = [p for p in persons if p[0] >= person_conf_thr]

    mapped: list[Detection] = []
    for conf, xyxy in persons:
        matched = any(_hat_matches_person(xyxy, h_xyxy, iou_thr) for _, h_xyxy in hats)
        mapped.append(Detection(cls_id=0 if matched else 1, conf=conf, xyxy=xyxy))
    return mapped


@dataclass
class FrameResult:
    """一帧图像的检测结果。"""

    image: np.ndarray                    # 画好框的图像
    detections: list[Detection] = field(default_factory=list)
    helmet_on: int = 0                   # 佩戴安全帽人数
    helmet_off: int = 0                  # 未佩戴安全帽人数


class HelmetDetector:
    """线程安全的 YOLO 检测器单例封装。

    Gradio 的图片/视频两个入口共享同一个模型实例，
    避免重复加载权重（权重加载约 1-2 秒，重复加载会卡界面）。
    """

    _instance: Optional["HelmetDetector"] = None
    _lock = threading.Lock()

    def __init__(self, model_path=None, conf=None):
        from ultralytics import YOLO  # 延迟导入，加快模块加载

        path = str(model_path or config.DEFAULT_MODEL_PATH)
        self.model = YOLO(path)
        self.conf = conf if conf is not None else config.CONF_THRESHOLD
        # 覆盖模型内部类别名（训练时为 hat/person），让检测框直接显示中文，
        # 答辩演示时不需要再解释英文标签的含义
        self.names = {0: "佩戴安全帽", 1: "未佩戴安全帽"}
        # ultralytics 的 YOLO 包装类 names 为只读属性，需写到底层 nn.Module
        try:
            self.model.model.names = self.names
        except Exception:
            pass  # 个别版本不支持覆写时退回英文标签，不影响功能

    @classmethod
    def get_instance(cls, model_path=None, conf=None) -> "HelmetDetector":
        """获取（必要时创建）全局单例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(model_path=model_path, conf=conf)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """单测用：重置单例。"""
        with cls._lock:
            cls._instance = None

    def detect_frame(self, frame_bgr: np.ndarray, conf: float | None = None,
                     imgsz: int | None = None, augment: bool = False) -> FrameResult:
        """对单帧 BGR 图像推理，返回画框结果与目标列表。

        :param frame_bgr: OpenCV BGR 格式图像 (H, W, 3)
        :param conf: 覆盖默认置信度阈值
        :param imgsz: 推理输入尺寸；图片可用更大尺寸提高小目标召回
        :param augment: 是否开启 YOLO 增强推理；会增加图片推理耗时
        """
        thr = conf if conf is not None else self.conf
        # 推理用更低的内部阈值：低置信度的帽子框也要召回用于佩戴匹配，
        # 否则"帽子置信度偏低被过滤 -> 戴帽者误判为未佩戴"。
        # 用户阈值仍作为 person 是否计入/画框/记违规的门槛。
        infer_thr = min(thr, config.HAT_RECALL_CONF)
        predict_kwargs = {"conf": infer_thr, "verbose": False}
        if imgsz is not None:
            predict_kwargs["imgsz"] = imgsz
        if augment:
            predict_kwargs["augment"] = True
        preds = self.model.predict(frame_bgr, **predict_kwargs)

        raw: list[tuple[int, float, tuple]] = []
        if preds:
            # ultralytics 返回列表（每个元素对应一张图），取第一张
            boxes = preds[0].boxes
            if boxes is not None:
                for i in range(len(boxes)):
                    cid = int(boxes.cls[i].item())
                    conf_val = float(boxes.conf[i].item())
                    x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[i].tolist())
                    raw.append((cid, conf_val, (x1, y1, x2, y2)))

        # hat/person 原始类别 -> 佩戴/未佩戴 判定（见 map_hat_person 说明）
        detections = map_hat_person(raw, person_conf_thr=thr)

        # 自绘标注框：只画"人"的判定结果，中文标签 + 置信度
        annotated = frame_bgr
        if detections:
            from ultralytics.utils.plotting import Annotator, colors

            annotator = Annotator(frame_bgr.copy(), line_width=None,
                                  font_size=None, font="Arial.ttf",
                                  pil=False, example="佩戴安全帽")
            for d in detections:
                annotator.box_label(d.xyxy,
                                    f"{self.names[d.cls_id]} {d.conf:.2f}",
                                    color=colors(d.cls_id, True))
            annotated = annotator.result()

        helmet_on = sum(1 for d in detections if d.cls_id == 0)
        helmet_off = sum(1 for d in detections if d.cls_id == 1)
        return FrameResult(
            image=annotated, detections=detections,
            helmet_on=helmet_on, helmet_off=helmet_off,
        )
