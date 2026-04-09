from __future__ import annotations

"""
NVIDIA model provider for 0pnMatrx.

Uses NVIDIA's OpenAI-compatible API endpoint.
API key loaded from config — never hardcoded.
"""

import json
import logging
import os

import aiohttp

from runtime.models.model_interface import ModelInterface, ModelResponse

logger = logging.getLogger(__name__)


class NVIDIAClient(ModelInterface):

    def __init__(self, config: dict):
        self.api_key = config.get("api_key") or os.environ.get("NVIDIA_API_KEY", "")
        self.model = config.get("model", "meta/llama-3.3-70b-instruct")
        self.base_url = config.get("base_url", "https://integrate.api.nvidia.com/v1")

    async def complete(self, messages: list, tools: list[dict] | None = None, **kwargs) -> ModelResponse:
        if not self.api_key:
            raise RuntimeError("NVIDIA API key not configured")

        formatted = [{"role": m.role, "content": m.content or ""} for m in messages]
        payload: dict = {"model": self.model, "messages": formatted, "max_tokens": 4096}
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t.get("parameters", {})}}
                for t in tools
            ]

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"NVIDIA HTTP {resp.status}: {body[:300]}")
                data = await resp.json()

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        usage = data.get("usage", {})

        return ModelResponse(
            content=msg.get("content"),
            tool_calls=msg.get("tool_calls"),
            model=data.get("model", self.model),
            provider="nvidia",
            finish_reason=choice.get("finish_reason", ""),
            usage={"prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0)},
        )

    async def health_check(self) -> bool:
        return bool(self.api_key)

    @property
    def provider_name(self) -> str:
        return "nvidia"
