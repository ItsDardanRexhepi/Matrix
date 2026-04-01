"""
Web Tool — fetch and extract content from URLs.

Retrieves web pages and extracts readable text content,
stripping HTML tags and navigation elements.
"""

import logging

import aiohttp

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 100_000


class WebTool:
    name = "web_fetch"
    schema = {
        "name": "web_fetch",
        "description": "Fetch a web page and extract its text content.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch",
                },
            },
            "required": ["url"],
        },
    }

    def __init__(self, config: dict):
        self.config = config

    async def execute(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return "Error: URL must start with http:// or https://"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; 0pnMatrx/1.0)"},
                    timeout=aiohttp.ClientTimeout(total=15),
                    allow_redirects=True,
                ) as resp:
                    if resp.status != 200:
                        return f"Error: HTTP {resp.status}"

                    content_type = resp.headers.get("Content-Type", "")
                    if "text" not in content_type and "json" not in content_type:
                        return f"Error: unsupported content type: {content_type}"

                    body = await resp.text()

            if len(body) > MAX_CONTENT_LENGTH:
                body = body[:MAX_CONTENT_LENGTH]

            text = self._extract_text(body)
            return text if text.strip() else "(page returned no readable content)"

        except aiohttp.ClientError as e:
            return f"Error fetching URL: {e}"
        except Exception as e:
            logger.error(f"Web fetch failed: {e}")
            return f"Error: {e}"

    def _extract_text(self, html: str) -> str:
        """Extract readable text from HTML, removing scripts, styles, and tags."""
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

        text = "".join(result)

        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(stripped)

        return "\n".join(lines)
