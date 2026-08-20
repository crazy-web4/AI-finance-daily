"""
Agent 基类与通用 LLM 调用器
所有 Agent 继承 BaseAgent，统一处理 prompt 加载、JSON 解析、重试
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Generic, TypeVar

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """统一的 LLM 调用客户端（OpenAI 兼容）。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ARK_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("ARK_BASE_URL", "") or os.environ.get("OPENAI_BASE_URL", "")
        self.model = model or os.environ.get("LLM_MODEL", "doubao-pro-128k-240515")

        if not self.api_key:
            raise ValueError("未配置 API key，请设置 ARK_API_KEY 或 OPENAI_API_KEY")
        if not self.base_url:
            raise ValueError("未配置 Base URL，请设置 ARK_BASE_URL 或 OPENAI_BASE_URL")

        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        # 架构评审 #16: 调用统计，供运行报告使用
        self.stats = {"calls": 0, "completion_chars": 0}

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.3,
        max_retries: int = 2,
    ) -> T:
        """
        调用 LLM 并解析返回的 JSON 为 Pydantic 模型。
        支持最多 max_retries 次重试（解析失败时）。
        """
        for attempt in range(max_retries + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
                text = resp.choices[0].message.content or "{}"
                self.stats["calls"] += 1
                self.stats["completion_chars"] += len(text)
                data = _extract_json(text)
                return response_model.model_validate(data)

            except Exception as e:
                if attempt < max_retries:
                    continue
                raise RuntimeError(f"LLM 调用失败（{max_retries+1}次重试后）: {e}") from e

    def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        """纯文本调用。"""
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )
        text = resp.choices[0].message.content or ""
        self.stats["calls"] += 1
        self.stats["completion_chars"] += len(text)
        return text


def _extract_json(text: str) -> dict[str, Any]:
    """
    从 LLM 输出中提取 JSON 对象。
    支持被 ```json ... ``` 包裹的情况，也支持纯 JSON。
    """
    text = text.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ```
    m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        return json.loads(m.group(1))

    # 尝试提取第一个 { 到最后一个 }
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        return json.loads(text[start:end+1])

    raise ValueError(f"无法从文本中提取 JSON: {text[:200]}")


class BaseAgent(Generic[T]):
    """Agent 基类。"""

    prompt_file: str = ""  # 子类指定 prompt 文件名
    response_model: type[T] | None = None  # 子类指定输出模型

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()
        self.system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        """从 prompts/ 目录加载 system prompt。"""
        if not self.prompt_file:
            return ""
        path = Path("prompts") / self.prompt_file
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def run(self, *args: Any, **kwargs: Any) -> T:
        """子类实现具体的 run 方法。"""
        raise NotImplementedError
