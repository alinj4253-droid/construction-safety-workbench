"""GPU 收尾流水线的 Python 段：装包验证 + 训练 + 切权重 + 测试 + 提交。

由 gpu_finalize.ps1 调用；也可独立运行：
    python scripts/gpu_finalize.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
WHEEL = Path(r"C:\Users\Public\torch_wheels\torch-2.7.1+cu126-cp311-cp311-win_amd64.whl.full")
TV = Path(r"C:\Users\Public\torch_wheels\torchvision-0.22.1+cu126-cp311-cp311-win_amd64.whl")
TOTAL = 2716982502


def run(cmd, **kw):
    print("RUN:", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, **kw)


def main():
    # 阶段2: 安装 GPU torch
    print("=== 阶段2: 安装 GPU torch + torchvision ===", flush=True)
    env = {**__import__("os").environ, "PIP_USER": "0"}
    run([PY, "-m", "pip", "install", "--force-reinstall", "--no-deps", str(WHEEL)], env=env)
    run([PY, "-m", "pip", "install", "--force-reinstall", "--no-deps", str(TV)], env=env)
    run([PY, "-m", "pip", "install", "filelock", "typing-extensions", "sympy",
         "networkx", "jinja2", "fsspec",
         "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "--quiet"], env=env)

    # 验证 CUDA
    r = run([PY, "-c", "import torch; print('TORCH_VERSION:', torch.__version__); "
                       "print('CUDA_OK:', torch.cuda.is_available())"],
            capture_output=True, text=True)
    print(r.stdout, r.stderr, flush=True)
    if "CUDA_OK: True" not in r.stdout:
        print("FATAL: CUDA 不可用", flush=True)
        sys.exit(1)

    # 阶段3: GPU 训练
    print("=== 阶段3: GPU 完整训练 ===", flush=True)
    run([PY, str(ROOT / "scripts" / "train.py")], cwd=str(ROOT))
    best = ROOT / "models" / "helmet_yolo11n" / "weights" / "best.pt"
    if not best.exists():
        print("FATAL: 训练未产出 best.pt", flush=True)
        sys.exit(1)

    # 阶段4: 切换默认权重
    print("=== 阶段4: 切换默认权重 ===", flush=True)
    cfg = ROOT / "app" / "config.py"
    src = cfg.read_text(encoding="utf-8")
    old_line_prefix = "DEFAULT_MODEL_PATH = MODELS_DIR / "
    new_line = 'DEFAULT_MODEL_PATH = MODELS_DIR / "helmet_yolo11n" / "weights" / "best.pt"'
    lines = []
    for ln in src.splitlines():
        if ln.strip().startswith(old_line_prefix.strip()):
            lines.append(new_line)
        else:
            lines.append(ln)
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("CONFIG_SWITCHED", flush=True)

    # 阶段5: 全量测试 + e2e
    print("=== 阶段5: pytest + e2e ===", flush=True)
    run([PY, "-m", "pytest", "tests", "-q"], cwd=str(ROOT))
    run([PY, str(ROOT / "scripts" / "e2e_verify.py")], cwd=str(ROOT))

    # 阶段6: git 提交
    print("=== 阶段6: git 提交 ===", flush=True)
    run(["git", "-C", str(ROOT.parent), "add", str(ROOT)])
    run(["git", "-C", str(ROOT.parent), "commit", "-m",
         "feat: GPU完整训练(25 epochs)上线，默认权重切换为完整模型"])
    print("=== ALL_PIPELINE_DONE ===", flush=True)


if __name__ == "__main__":
    main()

