"""Claude Code CLI backend.

Drives ``claude -p`` headless — the same way Dr.RTL itself invokes its LLM.
Useful where an Anthropic API key is not available but a Claude Code session
is (subscription auth, sandboxed CI, this repo's remote environment).

Limitations: no temperature control (the CLI does not expose it), one call
per process. Diversity across candidates then comes from directives alone.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Optional

from .base import LLMBackend, LLMResponse, Message


class ClaudeCLIBackend(LLMBackend):
    name = "claude-cli"

    def __init__(self, model: str = "", temperature: float = 0.3, max_tokens: int = 8192,
                 timeout: int = 600):
        super().__init__(model or "default", temperature, max_tokens)
        self.timeout = timeout
        if not shutil.which("claude"):
            raise RuntimeError("claude CLI not found on PATH")

    def _chat_once(
        self, messages: list[Message], system: Optional[str], temperature: float, max_tokens: int
    ) -> LLMResponse:
        parts = []
        if system:
            parts.append(f"<instructions>\n{system}\n</instructions>")
        for m in messages:
            parts.append(m.content)
        prompt = "\n\n".join(parts)

        cmd = ["claude", "-p", "--output-format", "json", "--max-turns", "1"]
        if self.model and self.model != "default":
            cmd += ["--model", self.model]
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=self.timeout
        )
        if proc.returncode != 0:
            # Error details often arrive as JSON on stdout, not stderr.
            detail = (proc.stderr.strip() or proc.stdout.strip())[-500:]
            raise RuntimeError(f"claude CLI failed (rc={proc.returncode}): {detail}")
        try:
            data = json.loads(proc.stdout)
            text = data.get("result", "")
            usage = data.get("usage", {}) or {}
            return LLMResponse(
                text=text,
                model=data.get("model", self.model),
                input_tokens=int(usage.get("input_tokens", 0) or 0),
                output_tokens=int(usage.get("output_tokens", 0) or 0),
                raw=data,
            )
        except json.JSONDecodeError:
            # Fall back to treating stdout as plain text.
            return LLMResponse(text=proc.stdout.strip(), model=self.model)
