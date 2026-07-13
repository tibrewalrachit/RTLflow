"""Offline mock backend for tests and dry-runs (no API key, deterministic)."""

from __future__ import annotations

from typing import Callable, Optional

from .base import LLMBackend, LLMResponse, Message, extract_verilog


class MockBackend(LLMBackend):
    """Replays scripted responses; falls back to a harmless no-op reply.

    ``script`` is consumed in call order.  A callable script entry receives
    the concatenated prompt text and returns the response string, which lets
    tests react to what the harness actually asked.
    """

    name = "mock"

    def __init__(self, script: Optional[list[str | Callable[[str], str]]] = None):
        super().__init__(model="mock", temperature=0.0)
        self.script = list(script or [])
        self.prompts: list[str] = []  # recorded for assertions

    def _chat_once(
        self, messages: list[Message], system: Optional[str], temperature: float, max_tokens: int
    ) -> LLMResponse:
        prompt = "\n".join(m.content for m in messages)
        self.prompts.append((system or "") + "\n" + prompt)
        if self.script:
            entry = self.script.pop(0)
            text = entry(prompt) if callable(entry) else entry
        else:
            text = self._default_reply(prompt)
        return LLMResponse(text=text, model="mock", input_tokens=len(prompt) // 4,
                           output_tokens=len(text) // 4)

    @staticmethod
    def _default_reply(prompt: str) -> str:
        # Echo back any RTL in the prompt as a no-op "optimization", else a
        # bland JSON-ish acknowledgement usable by analyzer/extractor roles.
        rtl = extract_verilog(prompt)
        if rtl:
            return "No further optimization found; returning design unchanged.\n```verilog\n" + rtl + "```\n"
        return '{"analysis": "no-op mock analysis", "suggestions": []}'
