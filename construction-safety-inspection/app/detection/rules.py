"""违规判定规则：把检测结果转化为违规记录。

规则（对应《建筑施工安全检查标准》JGJ 59-2011 "三宝"防护检查评分表）：
- 检出"未佩戴安全帽"目标，且置信度 >= 阈值 -> 记一次违规（不戴安全帽）
- 置信度低于阈值的目标不计入，宁可漏报不可误报（现场执法场景）

SHWD 数据集只有"人"与"安全帽"两类。在工地场景中，画面里的每个未戴帽
人员都直接对应一条违规。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app import config
from app.detection.detector import FrameResult


@dataclass
class Violation:
    """一条违规记录。"""

    ts: str               # 采集时间 ISO 格式
    source: str           # 来源（图片文件名 / 摄像头 / 视频名）
    helmet_off: int       # 未佩戴安全帽人数
    helmet_on: int        # 佩戴安全帽人数
    conf_min: float       # 本帧违规目标的最小置信度
    severity: str         # 风险等级：一般 / 严重

    def to_row(self) -> tuple:
        return (self.ts, self.source, self.helmet_off, self.helmet_on,
                self.conf_min, self.severity)


def judge_frame(result: FrameResult, source: str = "unknown",
                conf_threshold: float | None = None,
                now: Optional[datetime] = None) -> Optional[Violation]:
    """判定一帧检测结果是否构成违规。

    :return: 无违规返回 None；有违规返回 Violation 记录
    """
    thr = conf_threshold if conf_threshold is not None else config.CONF_THRESHOLD
    offs = [d for d in result.detections if d.cls_id == 1 and d.conf >= thr]
    if not offs:
        return None

    # 风险分级：单人未戴为"一般"，两人及以上为"严重"
    n_off = len(offs)
    severity = "严重" if n_off >= 2 else "一般"
    conf_min = min(d.conf for d in offs)
    ts = (now or datetime.now()).isoformat(timespec="seconds")

    return Violation(
        ts=ts, source=source,
        helmet_off=n_off, helmet_on=result.helmet_on,
        conf_min=round(conf_min, 4), severity=severity,
    )
