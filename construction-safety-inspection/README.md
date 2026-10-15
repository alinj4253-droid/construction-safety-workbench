# 建筑工地安全智能巡检系统

> 实习单位：福建省凯特建筑有限公司 ｜ 专业综合实践项目（智能科学与技术）
> **YOLO 视觉检测 × 双 Agent 报告生成**：自动检测施工现场未佩戴安全帽行为，积累违规台账，一键生成可交付的《安全巡检报告》。

## 1. 系统架构

```
┌────────────────────────────────────────────────────────────┐
│                  Gradio Web 界面（:7860）                   │
│   图片检测 │ 视频检测 │ 违规台账 │ 智能报告  四个页签        │
└──────────────┬─────────────────────────────────────────────┘
               │
┌──────────────▼──────────────┐   ┌──────────────────────────┐
│      视觉检测模块            │   │     多智能体报告模块       │
│  YOLO (yolo11n 微调)        │   │  安全分析 Agent(快模型)    │
│  佩戴安全帽 / 未佩戴安全帽    │──▶│   ↓ 结构化风险分析 JSON    │
│  置信度阈值过滤              │   │  报告撰写 Agent(主力模型)  │
└──────────────┬──────────────┘   │   ↓ 巡检报告 Markdown     │
               │                  └──────────▲───────────────┘
┌──────────────▼──────────────┐              │
│    违规判定 + SQLite 台账    │──────────────┘
│  时间/来源/人数/置信度/严重度 │  台账数据喂给 Agent 做分析
└─────────────────────────────┘
```

**答辩故事线**：传统人工巡检效率低、记录难追溯 → 本系统用摄像头自动检测未戴安全帽 → 自动积累违规台账 → 双 Agent 自动生成符合法规引用规范的巡检报告。

## 2. 环境要求

- Python 3.11（venv 已建在 `.venv/`）
- 依赖见 `requirements.txt`（torch 建议装 CUDA 版，CPU 版也可运行）
- 大模型 API：OpenAI 兼容接口（默认 CloseAI 中转），配置在 `.env`

## 3. 快速启动

```powershell
# 方式一：一键启动
run.bat

# 方式二：手动
cd construction-safety-inspection
.venv\Scripts\activate
python -m app.ui.app          # 自动打开 http://127.0.0.1:7860
```

## 4. 训练自己的模型

```powershell
cd construction-safety-inspection
.venv\Scripts\activate
# 1) 数据集转换（支持 SHWD VOC / Roboflow COCO 两种格式，自动探测）
python scripts\prepare_dataset.py [数据集目录] [输出目录]
# 2) 训练（GPU: device=0；无 GPU 改 scripts/train.py 中 device="cpu"）
python scripts\train.py
# 产出 models/helmet_yolo11n/weights/best.pt + 训练曲线/混淆矩阵
```

## 5. 配置说明（.env）

```ini
OPENAI_BASE_URL=https://api.closeai-asia.com/v1   # OpenAI 兼容接口
OPENAI_API_KEY=sk-xxxx                             # 你的 key
LLM_MAIN_MODEL=gpt-4.1-mini                        # 报告撰写（质量优先）
LLM_FAST_MODEL=deepseek-v4.1-flash                 # 安全分析（速度优先）
CONF_THRESHOLD=0.35                                # 人员框置信度/违规判定阈值
LEDGER_DB=data/ledger.db                           # 台账数据库
```

## 6. 测试

```powershell
.venv\Scripts\python.exe -m pytest tests -v
# 当前共 38 项：检测映射、视频去重、判定规则、台账、数据转换与 Agent 测试
```

## 7. 目录结构

```
construction-safety-inspection/
├─ app/
│  ├─ config.py                # 全局配置（.env 加载）
│  ├─ detection/
│  │  ├─ detector.py           # YOLO 检测器封装（单例）
│  │  ├─ rules.py              # 违规判定规则（阈值/分级）
│  │  └─ ledger.py             # SQLite 违规台账
│  ├─ agents/
│  │  ├─ llm_client.py         # OpenAI 兼容客户端（重试/超时）
│  │  ├─ safety_analyst.py     # 安全分析 Agent（快模型）
│  │  └─ report_writer.py      # 报告撰写 Agent（主力模型）
│  └─ ui/app.py                # Gradio 四页签界面
├─ kb/regulations.json         # 法规知识库（北大法宝核实）
├─ scripts/
│  ├─ prepare_dataset.py       # VOC/COCO → YOLO 转换
│  └─ train.py                 # 训练脚本
├─ tests/                      # pytest 29 项
├─ data/                       # 数据集与台账（gitignore）
├─ models/                     # 训练产物（gitignore）
└─ exports/                    # 报告/视频导出（gitignore）
```

## 8. 法规依据（已核实）

- 《中华人民共和国安全生产法》（2021修正）**第四十五条**：生产经营单位必须为从业人员提供符合国家标准或者行业标准的劳动防护用品，并监督、教育从业人员按照使用规则佩戴、使用。
- 《建筑施工安全检查标准》（JGJ 59-2011）：将"三宝"（安全帽、安全带、安全网）使用列为检查评定项目，进入施工现场必须佩戴安全帽。

## 9. 已知限制

- 检测类别为二分类（戴/未戴安全帽），未覆盖反光衣、安全带等（可扩展）
- SHWD 类别口径中 person=未戴帽人头，与常规"行人"语义不同
- Agent 报告生成依赖外部 API，断网时检测功能不受影响但报告页不可用
- 视频页按抽帧结果做轻量人员轨迹去重，同一人连续多帧只计入一次；违规帧数仍单独保留用于说明检测覆盖情况
