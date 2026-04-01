"""
Ollama model provider — local, private, free inference.

This is the default provider for 0pnMatrx. It connects to a locally running
Ollama instance and supports tool calling for models that implement it.
"""

import json
import logging
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

    async def complete(
        self,
        messages: list,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> ModelResponse:
        formatted = self._format_messages(messages)

        payload: dict = {
            "model": self.model,
            "messages": formatted,
            "stream": False,
        }

        if tools:
            payload["tools"] = self._format_tools(tools)

        url = f"{self.base_url}/api/chat"

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"Ollama error {resp.status}: {body}")
                    return ModelResponse(content=f"Model error: {resp.status}")

                data = await resp.json()

        message = data.get("message", {})
        content = message.get("content", "")
        tool_calls = self._extract_tool_calls(message)

        return ModelResponse(
            content=content if content else None,
            tool_calls=tool_calls if tool_calls else None,
            model=data.get("model", self.model),
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
        )

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception:
            return False

    @property
    def provider_name(self) -> str:
        return "ollama"

    def _format_messages(self, messages: list) -> list[dict]:
        formatted = []
        for msg in messages:
            entry: dict = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.name:
                entry["name"] = msg.name
            formatted.append(entry)
        return formatted

    def _format_tools(self, tools: list[dict]) -> list[dict]:
        """Convert tool schemas to Ollama's expected format."""
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
