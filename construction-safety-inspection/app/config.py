"""全局配置模块：从 .env 加载，集中管理系统参数。"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录 = construction-safety-inspection/
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 优先加载项目根下的 .env
load_dotenv(PROJECT_ROOT / ".env")

# ---------- 大模型 API ----------
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.closeai-asia.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MAIN_MODEL = os.getenv("LLM_MAIN_MODEL", "gpt-4.1-mini")
LLM_FAST_MODEL = os.getenv("LLM_FAST_MODEL", "deepseek-v4.1-flash")

# ---------- 检测配置 ----------
# 违规判定置信度阈值：低于该值的"未戴安全帽"目标不计入违规（防误报）
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.35"))

# 类别定义：与训练数据（SHWD 数据集）原始类别保持一致
# 0 -> hat    : 安全帽目标（框住帽子）
# 1 -> person : 人员目标（框住全身）
# 佩戴判定在 detector.map_hat_person 中完成：person 与 hat 框重叠即"佩戴"，
# 不与任何 hat 重叠的 person 才记为"未佩戴"。
CLASS_NAMES = {0: "佩戴安全帽", 1: "未佩戴安全帽"}

# 帽子框召回阈值：推理时的内部下限（低于用户阈值也要召回帽子用于佩戴匹配），
# 防止"帽子置信度偏低被过滤 -> 戴帽者误判为未佩戴"。
HAT_RECALL_CONF = float(os.getenv("HAT_RECALL_CONF", "0.15"))

# 推理策略：图片页优先提高小目标召回，视频页优先保持速度。
# 这两个参数只影响推理，不需要重新训练模型。
IMAGE_INFER_SIZE = int(os.getenv("IMAGE_INFER_SIZE", "960"))
IMAGE_FALLBACK_SIZE = int(os.getenv("IMAGE_FALLBACK_SIZE", "1280"))
VIDEO_INFER_SIZE = int(os.getenv("VIDEO_INFER_SIZE", "640"))
IMAGE_AUGMENT = os.getenv("IMAGE_AUGMENT", "1").lower() not in {"0", "false", "no"}

# ---------- 路径配置 ----------
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
KB_DIR = PROJECT_ROOT / "kb"
EXPORTS_DIR = PROJECT_ROOT / "exports"
LEDGER_DB = Path(os.getenv("LEDGER_DB", str(DATA_DIR / "ledger.db")))
if not LEDGER_DB.is_absolute():
    LEDGER_DB = PROJECT_ROOT / LEDGER_DB

# 默认使用的模型权重（训练完成后生成）
DEFAULT_MODEL_PATH = MODELS_DIR / "helmet_demo_best.pt"  # 冒烟训练演示权重；GPU完整训练后改回 helmet_yolo11n/weights/best.pt


def ensure_dirs() -> None:
    """确保运行期目录存在。"""
    for d in (DATA_DIR, MODELS_DIR, EXPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
