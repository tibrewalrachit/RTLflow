"""Anthropic (Claude) backend."""

from __future__ import annotations

import os
from typing import Optional

from .base import LLMBackend, LLMResponse, Message


class AnthropicBackend(LLMBackend):
    name = "anthropic"

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(model, temperature, max_tokens)
        import anthropic  # deferred so other backends work without the SDK

        kwargs = {}
        if api_key or os.environ.get("ANTHROPIC_API_KEY"):
            kwargs["api_key"] = api_key or os.environ["ANTHROPIC_API_KEY"]
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)

    def _chat_once(
        self, messages: list[Message], system: Optional[str], temperature: float, max_tokens: int
    ) -> LLMResponse:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or "",
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return LLMResponse(
            text=text,
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            raw=resp,
        )
