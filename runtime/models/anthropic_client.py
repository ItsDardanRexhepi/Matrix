from __future__ import annotations

"""
Anthropic model provider for 0pnMatrx.

Supports Claude models via the Messages API.
API key loaded from config — never hardcoded.
"""

import json
import logging
import os

import aiohttp

from runtime.models.model_interface import ModelInterface, ModelResponse

logger = logging.getLogger(__name__)


class AnthropicClient(ModelInterface):

    def __init__(self, config: dict):
        self.api_key = config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = config.get("model", "claude-sonnet-4-6")
        self.base_url = config.get("base_url", "https://api.anthropic.com")

    async def complete(self, messages: list, tools: list[dict] | None = None, **kwargs) -> ModelResponse:
        if not self.api_key:
            raise RuntimeError("Anthropic API key not configured")

        system_text = ""
        formatted = []
        for m in messages:
            if m.role == "system":
                system_text += (m.content or "") + "\n"
            elif m.role == "tool" and m.tool_call_id:
                formatted.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content or ""}],
                })
            elif m.role == "assistant" and m.tool_calls:
                content_blocks = []
                if m.content:
                    content_blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    content_blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": fn.get("name", ""), "input": args})
                formatted.append({"role": "assistant", "content": content_blocks})
            else:
                formatted.append({"role": m.role if m.role in ("user", "assistant") else "user", "content": m.content or ""})

        payload: dict = {"model": self.model, "max_tokens": 4096, "messages": formatted}
        if system_text.strip():
            payload["system"] = system_text.strip()
        if tools:
            payload["tools"] = [
                {"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("parameters", {})}
                for t in tools
            ]

        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/v1/messages", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Anthropic HTTP {resp.status}: {body[:300]}")
                data = await resp.json()

        content_text = ""
        tool_calls = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {"name": block.get("name", ""), "arguments": json.dumps(block.get("input", {}))},
                })

        usage = data.get("usage", {})
        return ModelResponse(
            content=content_text if content_text else None,
            tool_calls=tool_calls if tool_calls else None,
            model=data.get("model", self.model),
            provider="anthropic",
            finish_reason=data.get("stop_reason", ""),
            usage={"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": usage.get("output_tokens", 0)},
        )

    async def health_check(self) -> bool:
        return bool(self.api_key)

    @property
    def provider_name(self) -> str:
        return "anthropic"
