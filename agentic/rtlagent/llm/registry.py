"""Backend factory.

Backend spec strings (CLI / config friendly):

    anthropic:claude-sonnet-5
    anthropic:claude-opus-4-8
    glm:glm-5.2                          # Zhipu API (GLM_API_KEY)
    openai:gpt-5                         # OPENAI_API_KEY
    openai:zai-org/GLM-5.2@http://localhost:8000/v1   # vLLM/SGLang, any model
    openrouter:z-ai/glm-5.2              # OPENROUTER_API_KEY
    mock:
"""

from __future__ import annotations

import os
from typing import Optional

from .base import LLMBackend


def create_backend(spec: str, temperature: float = 0.3, max_tokens: int = 8192) -> LLMBackend:
    provider, _, rest = spec.partition(":")
    model, _, base_url = rest.partition("@")
    provider = provider.strip().lower()
    base_url = base_url.strip() or None

    if provider == "anthropic":
        from .anthropic_backend import AnthropicBackend

        return AnthropicBackend(model or "claude-sonnet-5", temperature, max_tokens, base_url=base_url)
    if provider == "glm":
        from .openai_backend import GLMBackend

        return GLMBackend(model or "glm-5.2", temperature, max_tokens, base_url=base_url)
    if provider in ("openai", "vllm", "sglang", "deepseek", "qwen"):
        from .openai_backend import OpenAICompatBackend

        defaults = {
            "deepseek": "https://api.deepseek.com/v1",
            "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "vllm": "http://localhost:8000/v1",
            "sglang": "http://localhost:30000/v1",
        }
        return OpenAICompatBackend(
            model,
            temperature,
            max_tokens,
            base_url=base_url or defaults.get(provider),
            api_key_env={"deepseek": "DEEPSEEK_API_KEY", "qwen": "DASHSCOPE_API_KEY"}.get(
                provider, "OPENAI_API_KEY"
            ),
        )
    if provider == "openrouter":
        from .openai_backend import OpenAICompatBackend

        return OpenAICompatBackend(
            model,
            temperature,
            max_tokens,
            base_url=base_url or "https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
        )
    if provider == "claude-cli":
        from .claude_cli_backend import ClaudeCLIBackend

        return ClaudeCLIBackend(model, temperature, max_tokens)
    if provider == "mock":
        from .mock_backend import MockBackend

        return MockBackend()
    raise ValueError(f"unknown LLM backend provider '{provider}' in spec '{spec}'")


def default_backend_spec() -> str:
    """Pick a sensible default from the environment."""
    if os.environ.get("RTLAGENT_BACKEND"):
        return os.environ["RTLAGENT_BACKEND"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic:claude-sonnet-5"
    if os.environ.get("GLM_API_KEY"):
        return "glm:glm-5.2"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai:gpt-5"
    import shutil

    if shutil.which("claude"):
        return "claude-cli:"
    return "mock:"
