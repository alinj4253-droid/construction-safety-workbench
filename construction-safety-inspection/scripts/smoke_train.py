"""CPU 冒烟训练：3 epochs 验证全链路（数据集/YOLO/保存）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ultralytics import YOLO  # noqa: E402

print("start: cpu smoke 3 epochs", flush=True)
m = YOLO(str(ROOT / "yolo11n.pt"))
r = m.train(
    data=str(ROOT / "data" / "shwd_yolo" / "data.yaml"),
    epochs=3, imgsz=480, batch=8, device="cpu",
    project=str(ROOT / "models"), name="helmet_smoke",
    exist_ok=True, patience=3, plots=True, workers=0, seed=42, save=True,
)
print("SMOKE_TRAIN_DONE", flush=True)

