# 施工安全证据助手 RAG

这是一个与原“嘉庚智答”独立运行的施工安全领域 RAG 项目，面向建筑施工实习场景。问答服务直接复用原项目已经验证的 `RAGPipeline.query_stream`、查询改写、路由检索、Weighted RRF、证据裁判、有限重试、会话历史和滚动摘要；只替换施工安全知识库、领域提示词和界面文案。

## 项目链路

```text
官方网页/PDF
   -> 抓取与清洗
   -> 条款/段落级切分
   -> BM25 + 本地向量混合索引
   -> 施工安全实体/关系图谱
   -> 原 RAGPipeline：查询理解/路由/多路检索/证据裁判/有限重试
   -> 流式 LLM 生成与会话记忆
```

本项目与 `construction-safety-inspection` 分开运行。后续如果需要，可以通过 `event` JSON 把视觉巡检结果作为查询上下文传入，但两者不互相依赖。

## 快速启动

```powershell
cd D:\Desktop\ProfPractice\construction_safety_rag
python -m pip install -r requirements.txt
python scripts\fetch_sources.py
python scripts\build_kb.py
python -m uvicorn app.api:app --host 127.0.0.1 --port 8010
```

打开 <http://127.0.0.1:8010/> 使用问答前端，<http://127.0.0.1:8010/docs> 查看 API，<http://127.0.0.1:8010/graph> 查看知识图谱，<http://127.0.0.1:8010/project> 查看知识库、切分规则和完整 RAG 流程说明。

若配置了 OpenAI 兼容接口，可复制 `.env.example` 为 `.env` 并填写密钥。前端问答会自动调用该接口；流式接口复用原项目的 `RAGPipeline.query_stream`、Evidence Judge、有限重试和 `RAGGenerator.generate_stream`。`python scripts\build_kb.py --with-llm` 会使用模型抽取知识图谱。未配置时自动使用规则抽取和本地兜底答案，仍可完成离线演示。

## 数据来源

来源清单在 `data/source_catalog.json`。当前成功处理 18 份网页/PDF，生成 446 个知识片段、1456 个实体和 3495 条关系。原始资料保存在 `data/raw/`，清洗文本保存在 `data/clean/`，切块、索引和图谱保存在 `data/processed/`。每个 chunk 都保存来源、发布部门、文号、生效状态和原文链接，避免把历史法规误当成现行依据。

## 重要边界

系统用于资料检索、风险解释和整改建议，不代替项目负责人、安全员或主管部门作出最终合规认定。法规更新后应重新运行抓取和构建命令，并人工复核版本状态。

