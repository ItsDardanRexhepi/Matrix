"""
Web / HTTP Request Tool — full HTTP client supporting GET, POST, PUT, DELETE.

Supports custom headers, configurable timeout, and returns status code,
response headers, and response body.
"""

import json
import logging

import aiohttp

logger = logging.getLogger(__name__)

MAX_BODY = 100_000


class WebTool:
    name = "web_request"
    schema = {
        "name": "web_request",
        "description": "Make an HTTP request. Supports GET, POST, PUT, DELETE with custom headers and body.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to request",
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE"],
                    "description": "HTTP method (default GET)",
                },
                "headers": {
                    "type": "object",
                    "description": "Custom request headers",
                },
                "body": {
                    "type": "string",
                    "description": "Request body (for POST/PUT)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30)",
                },
            },
            "required": ["url"],
        },
    }

    def __init__(self, config: dict):
        self.config = config

    async def execute(
        self,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        body: str | None = None,
        timeout: int = 30,
    ) -> str:
        if not url.startswith(("http://", "https://")):
            return "Error: URL must start with http:// or https://"

        method = method.upper()
        if method not in ("GET", "POST", "PUT", "DELETE"):
            return f"Error: unsupported method '{method}'"

        req_headers = {"User-Agent": "Mozilla/5.0 (compatible; 0pnMatrx/1.0)"}
        if headers:
            req_headers.update(headers)

        try:
            client_timeout = aiohttp.ClientTimeout(total=min(timeout, 120))
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                kwargs: dict = {"headers": req_headers, "allow_redirects": False}
                if body and method in ("POST", "PUT"):
                    # Try to send as JSON if parseable
                    try:
                        json.loads(body)
                        kwargs["data"] = body
                        req_headers.setdefault("Content-Type", "application/json")
                    except (json.JSONDecodeError, TypeError):
                        kwargs["data"] = body

                async with session.request(method, url, **kwargs) as resp:
                    status = resp.status
                    resp_headers = dict(resp.headers)
                    content_type = resp.headers.get("Content-Type", "")

                    if "text" in content_type or "json" in content_type or "xml" in content_type:
                        resp_body = await resp.text()
                    else:
                        raw = await resp.read()
                        resp_body = f"(binary content, {len(raw)} bytes)"

            if len(resp_body) > MAX_BODY:
                resp_body = resp_body[:MAX_BODY] + "\n... (truncated)"

            # Extract text from HTML for readability
            if "text/html" in content_type:
                resp_body = self._extract_text(resp_body)

            result_lines = [
                f"Status: {status}",
                f"Content-Type: {content_type}",
                f"Body:\n{resp_body}",
            ]
            return "\n".join(result_lines)

        except aiohttp.ClientError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"Web request failed: {e}")
            return f"Error: {e}"

    def _extract_text(self, html: str) -> str:
        for tag in ["script", "style", "nav", "footer", "header"]:
            while True:
                start = html.lower().find(f"<{tag}")
                if start == -1:
                    break
                end = html.lower().find(f"</{tag}>", start)
                if end == -1:
                    break
                html = html[:start] + html[end + len(f"</{tag}>"):]

        result = []
        in_tag = False
        for char in html:
            if char == "<":
                in_tag = True
            elif char == ">":
                in_tag = False
                result.append(" ")
            elif not in_tag:
                result.append(char)

        lines = [line.strip() for line in "".join(result).splitlines() if line.strip()]
        return "\n".join(lines[:200])
