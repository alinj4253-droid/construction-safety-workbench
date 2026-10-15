# 施工安全管理工作台

六个原型页面已接入 FastAPI + SQLite：工作台、AI 安全助手、隐患办理、隐患台账、AI 监控、知识库。原型文件与两个旧工程源码保留，正式运行入口为 `backend/app/main.py`。

前端已移除外部字体CDN，沿用原型的本机字体回退（微软雅黑 / 苹方 / 等宽字体），浏览器界面资源可完全本地加载。

## 在当前机器启动

```powershell
cd D:\Desktop\ProfPractice
.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010
```

也可以运行 `./start.ps1`。浏览器打开 http://127.0.0.1:8010 。若本轮验收服务仍在运行，直接打开即可；不要同时启动两个实例占用同一端口。

| 工号 | 姓名 | 视角 | 初始密码 |
|---|---|---|---|
| AQ20260001 | 王建国 | 专职安全员，可办理、签发、整改与复查 | 123456 |
| AQ20260002 | 李文静 | 安全员，同上 | 123456 |
| AQ20260003 | 张志强 | 项目安全总监，可查看、督办和审核知识资料 | 123456 |

本地演示账号密码以 PBKDF2 加盐保存，登录令牌仅保存哈希，8小时过期。会话与记忆按账号隔离；同项目隐患和办理文书共同可见。首次交付数据库为6条历史种子隐患、4条独立待确认演示线索，知识资料按实际文件登记。测试业务数据单独保留在 `qa.db`，不会混入交付台账。

## 大模型与离线运行

根目录 `.env` 已配置用户提供的 CloseAI 密钥，文件被 Git 忽略，切勿提交或分享。配置模板见 `.env.example`。本机已实际验证：

- OpenAI 兼容地址：`https://api.openai-proxy.org/v1`，平台[官方文档](https://doc.closeai-asia.com/tutorial/library.html)。
- 办理/检索：`deepseek-v4.1-flash`；独立复核：`doubao-seed-2-1-turbo-260628`。可通过 `LLM_MAIN_MODEL`、`LLM_REVIEW_MODEL` 更换为账号实际可用模型。
- 网关只读取本仓库 `.env` 与显式环境变量，不加载旧工程父目录的密钥。

设置 `$env:LLM_ENABLED='0'` 后启动即可演练离线。网络超时、凭证无效或输出格式不合格也会进入有标识的本地兜底：原文检索、模板起草、规则复核继续工作；离线的两角色不宣称已调用模型。

短期上下文保留最近8条消息，较早内容形成最多6000字的可追溯摘录摘要；长期记忆只保存用户明确指定的项目背景，可查看、删除，跨会话保留。密钥和密码不写入长期记忆。记忆不是法规证据，也不能替代现场事实确认。

## 业务约束

- AI 问答展示库内原文和片段定位。没有相关原文时明确拒答；仅有发布公告不能冒充独立规范全文。
- 轻轨为待确认→整改中→已闭环；重轨为待整改→整改中→待复查→已销项，复查不合格可退回。逾期按上海时区截止日派生，不覆盖业务状态。
- A 与 B 使用独立调用上下文，规则与复核意见逐轮落库，最多返工一次。未补齐责任方、期限或依据时转人工；签发前再次核验引用与隐患版本。
- 人工签发更新原隐患并关联唯一编号，不重复创建隐患；重复签发幂等。已签发引用保留快照，不随知识库改写。
- 真实 YOLO 抓拍只生成待核实线索。必须填写人工现场核实记录才创建轻轨隐患；误报驳回留痕且不入账。
- 上传知识文件一律待核验。项目资料与案例可供问答参考，但仅有效、已核验、适用地域的法规正文可作为文书引用候选。版本关系检查采用人工登记关系本地比对；撤销管理操作不会恢复已废止法定效力。
- GB55034-2022 公告废止的 JGJ80 部分强制性条文单独拦截；临边案例使用核对原页的现行4.3.1，不能沿用原型4.1.1。

## 新环境安装与知识库重建

使用 Python 3.11；建议新建独立虚拟环境后安装直接依赖（验收版本另见 `requirements-tested.txt`）：

```powershell
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 填入自己的密钥；不填也可离线运行。本机视觉依赖复用了旧工程中的兼容 torch / ultralytics 包（通过本地虚拟环境 `.pth`），迁移机器时需重新安装视觉依赖。检测权重路径为 `construction-safety-inspection/models/helmet_yolo11n/weights/best.pt`，本地回放素材位于 `videos/`。缺少这些文件时其他业务继续可用，检测会明确报错。

当前机器已保留 `backend/data/app.db`、`index.npz`、OCR缓存及解包后的标准正文。它们和模型/视频是本地交付数据，不纳入 Git。仅克隆 Git 时须另行复制这些本地资产，或重建：

```powershell
.venv/Scripts/python.exe -m backend.app.db
.venv/Scripts/python.exe -m backend.rag.knowledge
```

首次重建扫描PDF需先安装 PyMuPDF，并在 Windows 安装中文 OCR 语言包，运行 `python scripts/render_source_pdfs.py`；本机使用有 fitz 的系统 Python 完成此步骤。RAR 使用 7-Zip 解包到 `backend/data/extracted/` 后运行 `python scripts/extract_local_standards.py`，再重建索引。无解析能力的旧 DOC 保持待核验，不自动生效。源资料只读，审核结果写入新库。

**重建命令用于初始导入，不用于已有生产业务的日常治理**，它会按原料重新核定初始审核状态；日常增量通过知识库页面上传、核验、版本治理。要制作独立的新演示库，可执行 `python -m scripts.prepare_seed --output backend/data/new-demo.db`（拒绝覆盖已存在文件），并用 `APP_DB` 指向它。请先备份数据库再做任何迁移，停服务时可用SQLite备份API复制一致性快照。

## 测试与证据

```powershell
.venv/Scripts/python.exe -m pytest backend/tests -q --junitxml=artifacts/pytest-results.xml
```

测试使用临时SQLite副本或新库，自动关闭大模型。五条业务场景证据写入 `artifacts/e2e-results.json`；场景1的返工使用隔离环境显式注入的错误期限，测试标识写入任务与文书，不在正式业务中故意制造错误，正式接口默认拒绝测试草稿参数。

浏览器验收使用安装的 Google Chrome、`websocket-client`，每次创建独立临时浏览器配置，不操作个人资料。QA服务需先指向独立 `backend/data/qa.db` 并设置 `LLM_ENABLED=0`，监听8011；然后运行 `scripts/browser_p2.py` 至 `browser_p6.py`、`browser_identity.py`。`scripts/browser_cdp.py` 为P1验收（8010）。脚本会创建验收数据，不能对实际业务库运行。每个页面的 JSON 和截图位于 `artifacts/`。

线上连通/时延：`python -m scripts.llm_smoke`、`python -m scripts.smoke_stream`；实际双模型任务：`python -m scripts.smoke_handling_online`（会在8010创建明确命名的验收隐患，请使用专门测试库）。真实视频检测：`python scripts/smoke_vision.py`（8011）。

详细审读见 [审读与修正记录](docs/审读与修正记录.md)，最终验收见 [最终交付报告](docs/最终交付报告.md)。

## 当前边界

- 支持本机、单服务进程运行，未接真实短信、RTSP、门禁或生产级组织权限；总监与安全员是本地演示账号。正式部署需另行完成账号管理、TLS、运维备份与组织授权。
- 在场87人为门禁融合的演示值，反光衣线索为演示数据，安全帽两类才有真实模型。mAP50/P/R来自历史训练验证集，不代表现场准确率。实际帧可误检漏检，局部轨迹去重不代表唯一人员统计。
- RAG为稳定哈希向量与BM25独立召回后RRF融合；未伪称使用预训练语义嵌入。扫描资料只启用已核对条款作为核心依据；大量来源仍待人工核验，原清单63行缺有效URL。缺少全文的JGJ130/JGJ59/JGJ162不能凭空补条款。
- 大模型输出仍需人工判断。问答采用原文摘录保障出处，复杂跨条款解释能力有限；正式通知单必须人工签发，JSA/交底/日志始终为待审核草稿。
