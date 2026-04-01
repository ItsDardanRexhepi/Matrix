"""
Google Gemini model provider for 0pnMatrx.

Uses the Gemini REST API. API key loaded from config — never hardcoded.
"""

import json
import logging
import os
import uuid

import aiohttp

from runtime.models.model_interface import ModelInterface, ModelResponse

logger = logging.getLogger(__name__)


class GeminiClient(ModelInterface):

    def __init__(self, config: dict):
        self.api_key = config.get("api_key") or os.environ.get("GOOGLE_API_KEY", "")
        self.model = config.get("model", "gemini-pro")
        self.base_url = config.get("base_url", "https://generativelanguage.googleapis.com/v1beta")

    async def complete(self, messages: list, tools: list[dict] | None = None, **kwargs) -> ModelResponse:
        if not self.api_key:
            raise RuntimeError("Google API key not configured")

        contents = []
        system_text = ""
        for m in messages:
            if m.role == "system":
                system_text += (m.content or "") + "\n"
            elif m.role == "user":
                contents.append({"role": "user", "parts": [{"text": m.content or ""}]})
            elif m.role == "assistant":
                contents.append({"role": "model", "parts": [{"text": m.content or ""}]})
            elif m.role == "tool":
                contents.append({"role": "user", "parts": [{"text": f"Tool result: {m.content or ''}"}]})

        if system_text.strip() and contents:
            first_text = contents[0]["parts"][0].get("text", "")
            contents[0]["parts"][0]["text"] = f"{system_text.strip()}\n\n{first_text}"

        payload: dict = {"contents": contents}
        if tools:
            payload["tools"] = [{"function_declarations": [
                {"name": t["name"], "description": t.get("description", ""), "parameters": t.get("parameters", {})}
                for t in tools
            ]}]

        url = f"{self.base_url}/models/{self.model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Gemini HTTP {resp.status}: {body[:300]}")
                data = await resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            return ModelResponse(content="No response from Gemini", provider="gemini")

        parts = candidates[0].get("content", {}).get("parts", [])
        content_text = ""
        tool_calls = []
        for part in parts:
            if "text" in part:
                content_text += part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {"name": fc.get("name", ""), "arguments": json.dumps(fc.get("args", {}))},
                })

        usage = data.get("usageMetadata", {})
        return ModelResponse(
            content=content_text if content_text else None,
            tool_calls=tool_calls if tool_calls else None,
            model=self.model,
            provider="gemini",
            usage={"prompt_tokens": usage.get("promptTokenCount", 0), "completion_tokens": usage.get("candidatesTokenCount", 0)},
        )

    async def health_check(self) -> bool:
        return bool(self.api_key)

    @property
    def provider_name(self) -> str:
        return "gemini"
