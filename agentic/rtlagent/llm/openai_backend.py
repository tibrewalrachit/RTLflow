"""OpenAI-compatible backend.

Covers every open-weight serving path with one client:

* GLM (Zhipu / z.ai):        base_url=https://api.z.ai/api/paas/v4  (or
                             https://open.bigmodel.cn/api/paas/v4), model="glm-5.2"
* Local vLLM / SGLang:       base_url=http://localhost:8000/v1
* OpenRouter:                base_url=https://openrouter.ai/api/v1
* DeepSeek, Qwen, ...        their native OpenAI-compatible endpoints
"""

from __future__ import annotations

import os
from typing import Optional

from .base import LLMBackend, LLMResponse, Message


class OpenAICompatBackend(LLMBackend):
    name = "openai-compat"

    def __init__(
        self,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key_env: str = "OPENAI_API_KEY",
    ):
        super().__init__(model, temperature, max_tokens)
        import openai  # deferred

        key = api_key or os.environ.get(api_key_env) or os.environ.get("OPENAI_API_KEY") or "EMPTY"
        self._client = openai.OpenAI(api_key=key, base_url=base_url)

    def _chat_once(
        self, messages: list[Message], system: Optional[str], temperature: float, max_tokens: int
    ) -> LLMResponse:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs += [{"role": m.role, "content": m.content} for m in messages]
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=msgs,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = resp.choices[0]
        usage = resp.usage
        return LLMResponse(
            text=choice.message.content or "",
            model=resp.model or self.model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            raw=resp,
        )


GLM_BASE_URL = "https://api.z.ai/api/paas/v4"
GLM_BASE_URL_CN = "https://open.bigmodel.cn/api/paas/v4"


class GLMBackend(OpenAICompatBackend):
    """Zhipu GLM models (e.g. glm-5.2, glm-4.6) via their OpenAI-compatible API."""

    name = "glm"

    def __init__(
        self,
        model: str = "glm-5.2",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url or os.environ.get("GLM_BASE_URL", GLM_BASE_URL),
            api_key_env="GLM_API_KEY",
        )
