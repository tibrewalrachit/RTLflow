"""Backend-agnostic LLM interface.

Every backend implements ``chat(messages, system=..., ...) -> LLMResponse``.
The harness only ever speaks this interface, so swapping Anthropic for GLM
(or a local vLLM server) is a config change, not a code change.
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Any = None


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, resp: LLMResponse) -> None:
        self.calls += 1
        self.input_tokens += resp.input_tokens
        self.output_tokens += resp.output_tokens


class LLMBackend(ABC):
    """Abstract chat backend with retry handling."""

    name: str = "abstract"

    def __init__(self, model: str, temperature: float = 0.3, max_tokens: int = 8192):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.usage = Usage()

    @abstractmethod
    def _chat_once(
        self, messages: list[Message], system: Optional[str], temperature: float, max_tokens: int
    ) -> LLMResponse:
        ...

    def chat(
        self,
        messages: list[Message] | str,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        retries: int = 4,
    ) -> LLMResponse:
        if isinstance(messages, str):
            messages = [Message("user", messages)]
        temp = self.temperature if temperature is None else temperature
        mt = max_tokens or self.max_tokens
        delay = 2.0
        last_err: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                resp = self._chat_once(messages, system, temp, mt)
                self.usage.add(resp)
                return resp
            except Exception as e:  # noqa: BLE001 — provider SDKs raise many types
                last_err = e
                if attempt == retries:
                    break
                log.warning("%s chat failed (%s); retry %d/%d in %.0fs",
                            self.name, e, attempt + 1, retries, delay)
                time.sleep(delay)
                delay = min(delay * 2, 30)
        raise RuntimeError(f"LLM backend '{self.name}' failed after {retries + 1} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Structured-output helpers
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)
_VERILOG_FENCE_RE = re.compile(r"```(?:systemverilog|verilog|sv)?\s*\n(.*?)```", re.DOTALL)


def extract_json(text: str) -> Optional[Any]:
    """Best-effort JSON extraction from an LLM reply."""
    candidates = _CODE_FENCE_RE.findall(text)
    candidates.append(text)
    # Also try the largest {...} span.
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for c in candidates:
        try:
            return json.loads(c.strip())
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def extract_verilog(text: str) -> Optional[str]:
    """Extract the largest Verilog code block from an LLM reply."""
    blocks = _VERILOG_FENCE_RE.findall(text)
    blocks = [b for b in blocks if "module" in b]
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    if "module" in text and "endmodule" in text:
        start = text.find("module")
        # Back up to grab preceding compiler directives/comments on same design.
        end = text.rfind("endmodule") + len("endmodule")
        return text[start:end].strip() + "\n"
    return None
