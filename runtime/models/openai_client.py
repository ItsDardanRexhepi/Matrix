"""
OpenAI model provider for 0pnMatrx.

Supports GPT-4o and other OpenAI models via the chat completions API.
API key loaded from config — never hardcoded.
"""

import json
import logging
import os

import aiohttp

from runtime.models.model_interface import ModelInterface, ModelResponse

logger = logging.getLogger(__name__)


class OpenAIClient(ModelInterface):

    def __init__(self, config: dict):
        self.api_key = config.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
        self.model = config.get("model", "gpt-4o")
        self.base_url = config.get("base_url", "https://api.openai.com/v1")

    async def complete(self, messages: list, tools: list[dict] | None = None, **kwargs) -> ModelResponse:
        if not self.api_key:
            raise RuntimeError("OpenAI API key not configured")

        formatted = [{"role": m.role, "content": m.content or ""} for m in messages]
        # handle tool results
        for i, m in enumerate(messages):
            if m.role == "tool" and m.tool_call_id:
                formatted[i]["tool_call_id"] = m.tool_call_id
            if m.tool_calls:
                formatted[i]["tool_calls"] = m.tool_calls

        payload: dict = {"model": self.model, "messages": formatted}
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
                    raise RuntimeError(f"OpenAI HTTP {resp.status}: {body[:300]}")
                data = await resp.json()

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")
        usage = data.get("usage", {})

        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            model=data.get("model", self.model),
            provider="openai",
            finish_reason=choice.get("finish_reason", ""),
            usage={"prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0)},
        )

    async def health_check(self) -> bool:
        if not self.api_key:
            return False
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/models", headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception:
            return False

    @property
    def provider_name(self) -> str:
        return "openai"
