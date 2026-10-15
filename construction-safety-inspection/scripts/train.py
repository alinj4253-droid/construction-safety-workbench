"""YOLO 训练脚本：在 SHWD 数据集上微调 yolo11n。

训练参数面向笔记本 GPU（RTX 4050 6GB）做了取舍：
- 模型 yolo11n（最小档，保证训练速度与推理延迟）
- imgsz 640（精度与速度的平衡点）
- epochs 25（一下午时限内可完成：约 25-40 分钟）
- batch 16（6GB 显存安全值）

产出：models/helmet_yolo11n/weights/best.pt
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import config  # noqa: E402


def main() -> None:
    from ultralytics import YOLO

    data_yaml = config.DATA_DIR / "shwd_yolo" / "data.yaml"
    if not data_yaml.exists():
        raise SystemExit(
            f"未找到 {data_yaml}，请先运行 scripts/prepare_dataset.py 转换数据集"
        )

    # 从预训练权重微调（迁移学习：COCO 预训练主干 + 安全帽数据微调）
    model = YOLO("yolo11n.pt")
    results = model.train(
        data=str(data_yaml),
        epochs=25,
        imgsz=640,
        batch=16,
        device=0,                    # GPU；如无 GPU 改为 "cpu"（训练会很慢）
        project=str(config.MODELS_DIR),
        name="helmet_yolo11n",
        exist_ok=True,
        patience=10,                 # 早停：验证精度连续 10 轮不提升则停止
        save=True,
        plots=True,                  # 保存训练曲线/混淆矩阵（答辩实验图）
        workers=4,
        seed=42,
    )
    print("\n训练完成。最优权重：", config.DEFAULT_MODEL_PATH)
    print("验证结果：", results.results_dict if hasattr(results, "results_dict") else results)


if __name__ == "__main__":
    main()

