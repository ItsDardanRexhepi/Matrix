from __future__ import annotations

"""
Ollama model provider — local, private, free inference.

Default provider for 0pnMatrx. Connects to a locally running
Ollama instance, supports tool calling, and alerts via Telegram
when both primary and fallback models fail.
"""

import json
import logging
import os
import uuid

import aiohttp

from runtime.models.model_interface import ModelInterface, ModelResponse

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1"


class OllamaClient(ModelInterface):
    """Connects to a local Ollama instance for inference."""

    def __init__(self, config: dict):
        self.base_url = config.get("base_url", DEFAULT_BASE_URL).rstrip("/")
        self.model = config.get("model", DEFAULT_MODEL)
        self.fallback_model = config.get("fallback_model", "mistral")
        self._notifications_config = config.get("_notifications", {})

    async def complete(
        self,
        messages: list,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> ModelResponse:
        try:
            return await self._call_model(self.model, messages, tools)
        except Exception as primary_err:
            logger.warning(f"Ollama primary model '{self.model}' failed: {primary_err}")
            try:
                return await self._call_model(self.fallback_model, messages, tools)
            except Exception as fallback_err:
                logger.error(f"Ollama fallback model '{self.fallback_model}' also failed: {fallback_err}")
                await self._alert_failure(str(primary_err), str(fallback_err))
                raise RuntimeError(
                    f"Both Ollama models failed. Primary ({self.model}): {primary_err}. "
                    f"Fallback ({self.fallback_model}): {fallback_err}"
                )

    async def _call_model(
        self, model: str, messages: list, tools: list[dict] | None
    ) -> ModelResponse:
        formatted = self._format_messages(messages)
        payload: dict = {"model": model, "messages": formatted, "stream": False}
        if tools:
            payload["tools"] = self._format_tools(tools)

        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{self.base_url}/api/chat", json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Ollama HTTP {resp.status}: {body[:300]}")
                data = await resp.json()

        message = data.get("message", {})
        content = message.get("content", "")
        tool_calls = self._extract_tool_calls(message)

        return ModelResponse(
            content=content if content else None,
            tool_calls=tool_calls if tool_calls else None,
            model=data.get("model", model),
            provider="ollama",
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
        )

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def _alert_failure(self, primary_err: str, fallback_err: str):
        """Send Telegram alert when both models fail. Config-driven, never hardcoded."""
        bot_token = self._notifications_config.get("bot_token", "")
        owner_id = self._notifications_config.get("owner_id", "")
        if not bot_token or not owner_id:
            return
        msg = (
            f"0pnMatrx Ollama ALERT\n"
            f"Primary ({self.model}): {primary_err[:200]}\n"
            f"Fallback ({self.fallback_model}): {fallback_err[:200]}"
        )
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            async with aiohttp.ClientSession() as session:
                await session.post(url, json={"chat_id": owner_id, "text": msg}, timeout=aiohttp.ClientTimeout(total=5))
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    def _format_messages(self, messages: list) -> list[dict]:
        formatted = []
        for msg in messages:
            entry: dict = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
                # Ollama expects arguments as objects, not JSON strings
                native_calls = []
                for tc in msg.tool_calls:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                    native_calls.append({"function": {"name": fn.get("name", ""), "arguments": args}})
                entry["tool_calls"] = native_calls
            # Ollama tool responses: just role + content, no extra fields
            if msg.role == "tool":
                entry = {"role": "tool", "content": msg.content or ""}
            formatted.append(entry)
        return formatted

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        formatted = []
        for tool in tools:
            formatted.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}),
                },
            })
        return formatted

    def _extract_tool_calls(self, message: dict) -> list[dict] | None:
        raw_calls = message.get("tool_calls")
        if not raw_calls:
            return None
        calls = []
        for call in raw_calls:
            fn = call.get("function", {})
            calls.append({
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "arguments": json.dumps(fn.get("arguments", {})),
                },
            })
        return calls
