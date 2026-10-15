"""系统状态看板：模型/GPU/数据/依赖/台账一览。双击 查看进度.bat 运行。"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
TOTAL_WHEEL = 2716982502


def run_py(code: str) -> str:
    try:
        r = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                           timeout=60, cwd=str(ROOT))
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"检测失败: {e}"


def human_mb(n):
    return f"{n / 1024 / 1024:.1f}MB"


def main():
    print("=" * 56)
    print("     建筑工地安全智能巡检系统 —— 状态看板")
    print(f"     项目位置: {ROOT}")
    print("=" * 56)

    # 1. GPU / torch
    out = run_py("import torch; print(torch.__version__); "
                 "print(torch.cuda.is_available()); "
                 "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')")
    lines = out.splitlines()
    if len(lines) >= 2 and "True" in lines[1]:
        print(f"\n[1] PyTorch {lines[0]}  ✅ GPU可用（{lines[2]}）")
    else:
        print(f"\n[1] PyTorch 状态异常:\n    {out}")

    # 2. 模型
    print("\n[2] 检测模型：")
    best = ROOT / "models" / "helmet_yolo11n" / "weights" / "best.pt"
    demo = ROOT / "models" / "helmet_demo_best.pt"
    if best.exists():
        from datetime import datetime
        mt = datetime.fromtimestamp(best.stat().st_mtime).strftime("%m-%d %H:%M")
        print(f"    ✅ GPU完整训练模型 best.pt（{human_mb(best.stat().st_size)}，{mt} 生成）")
    if demo.exists():
        import hashlib
        same = (best.exists() and
                demo.stat().st_size == best.stat().st_size)
        print(f"    {'✅' if same else '⚠️'} 界面挂载权重 helmet_demo_best.pt"
              f"（{human_mb(demo.stat().st_size)}{'，与完整模型一致' if same else ''}）")

    # 3. 数据集
    print("\n[3] 数据集：")
    for split in ("train", "val"):
        d = ROOT / "data" / "shwd_yolo" / "images" / split
        n = len(list(d.glob("*.jpg"))) if d.exists() else 0
        print(f"    {split}: {n} 张{' ✅' if n > 0 else ' ❌'}")
    demo_imgs = ROOT / "demo_images"
    if demo_imgs.exists():
        print(f"    演示图片: {len(list(demo_imgs.glob('*.jpg')))} 张 ✅")

    # 4. 依赖完整性（关键包 import）
    out = run_py(
        "import gradio, cv2, ultralytics, openai, dotenv, pytest;"
        "print('all_imports_ok')")
    print("\n[4] 依赖完整性：", "✅ 全部可导入" if "all_imports_ok" in out else f"❌ {out}")

    # 5. 台账
    print("\n[5] 违规台账：")
    out = run_py(
        "import sys; sys.path.insert(0, '.');"
        "from app.detection import ledger; s = ledger.stats();"
        "print(f\"记录 {s['count']} 条 / 未戴帽 {s['persons']} 人次 / 严重 {s['severe']} 次\")")
    print(f"    {out}")

    # 6. 启动方式
    print("\n[6] 启动：双击 run.bat → 自动打开 http://127.0.0.1:7860")
    print("=" * 56)


if __name__ == "__main__":
    main()

