from app.original_pipeline import _SafeStreamingClient, build_pipeline


class FakeClient:
    def extract_json(self, prompt, system_prompt="", **kwargs):
        if "证据审查员" in system_prompt:
            return {"sufficient": True, "missing": [], "reason": "证据覆盖问题"}
        if "查询分析" in system_prompt or "查询分析专家" in system_prompt:
            return {"low_level_keywords": ["安全帽"], "high_level_keywords": ["施工安全"], "query_mode": "hybrid", "reason": "施工安全综合问题"}
        return {"rewritten": prompt.split("【原始问题】")[-1].strip()[:80]}

    def chat_stream(self, *args, **kwargs):
        yield "**结论**："
        yield "已有施工安全证据。"

    def chat(self, *args, **kwargs):
        return "答案"


def test_original_pipeline_stream_is_reused():
    pipeline = build_pipeline()
    fake = FakeClient()
    pipeline.query_analyzer.client = fake
    pipeline.pre_retrieval_rewriter.client = fake
    pipeline.evidence_judge.client = fake
    pipeline.query_rewriter.client = fake
    pipeline.generator.client = fake

    events = list(pipeline.query_stream("进入施工现场未佩戴安全帽有哪些依据？"))
    types = [event["type"] for event in events]
    assert "status" in types
    assert "token" in types
    assert types[-1] == "done"


def test_llm_failure_fallback_uses_retrieved_evidence():
    class EmptyClient:
        def chat_stream(self, *args, **kwargs):
            if False:
                yield "never"

    client = _SafeStreamingClient(EmptyClient(), "固定兜底不应直接返回")
    messages = [{
        "role": "user",
        "content": (
            "【检索证据】\n[1] 《建筑施工安全检查标准》片段 1：施工现场人员未戴安全帽，每人扣5分。\n\n"
            "【问题】\n安全帽佩戴的法规依据是什么？"
        ),
    }]

    answer = "".join(client.chat_stream(messages=messages))
    assert "安全帽" in answer
    assert "施工现场人员未戴安全帽" in answer
    assert "固定兜底不应直接返回" not in answer


def test_stream_adds_explicit_safety_helmet_evidence_when_model_omits_it():
    class IncompleteClient:
        def chat_stream(self, *args, **kwargs):
            yield "当前资料没有安全帽依据。"

    client = _SafeStreamingClient(IncompleteClient(), "兜底")
    messages = [{
        "role": "user",
        "content": (
            "【检索证据】\n[1] 《建筑施工安全检查标准》片段 40：施工现场人员未戴安全帽，每人扣5分。\n\n"
            "【问题】\n安全帽佩戴的法规依据是什么？"
        ),
    }]
    answer = "".join(client.chat_stream(messages=messages))
    assert "施工现场人员未戴安全帽，每人扣5分" in answer
