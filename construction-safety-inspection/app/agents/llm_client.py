"""大模型客户端封装：OpenAI 兼容接口（CloseAI 中转）。

统一超时、重试与错误提示，两个 Agent 共用。
"""

from __future__ import annotations

import time
from typing import Optional

from openai import OpenAI

from app import config


class LLMError(RuntimeError):
    """大模型调用失败（网络/鉴权/限流等）。"""


def create_client() -> OpenAI:
    if not config.OPENAI_API_KEY:
        raise LLMError("未配置 OPENAI_API_KEY，请检查 .env 文件")
    return OpenAI(
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_BASE_URL,
        timeout=90,
        max_retries=1,
    )


def chat(
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    retries: int = 2,
) -> str:
    """调用对话补全接口，带简单重试。

    :param system: 系统提示词（角色设定）
    :param user: 用户消息内容
    :param model: 模型名，默认用主力模型
    :param max_tokens: 最大生成 token 数。部分推理型模型（如
        deepseek-v4.1-flash）会先消耗思考 token，设太小会返回空，
        这里做了下限保护（>=1500）。
    :param retries: 失败重试次数
    :return: 模型回复文本
    """
    client = create_client()
    model = model or config.LLM_MAIN_MODEL
    # 推理型模型兼容：生成 token 下限保护，避免思考过程吃掉配额后返回空
    max_tokens = max(max_tokens, 1500)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise LLMError(f"模型 {model} 返回空内容")
            return content
        except LLMError:
            raise
        except Exception as e:  # 网络/限流等，退避后重试
            last_err = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise LLMError(f"大模型调用失败（重试 {retries} 次后）：{last_err}")
