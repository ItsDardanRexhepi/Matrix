"""
Web Search Tool — search the internet using DuckDuckGo.

Uses the duckduckgo_search Python library. Requires no API key.
Returns top results with title, URL, and snippet.
"""

import logging

logger = logging.getLogger(__name__)


class WebSearchTool:
    name = "web_search"
    schema = {
        "name": "web_search",
        "description": "Search the internet for current information using DuckDuckGo. Returns titles, URLs, and snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 10)",
                },
            },
            "required": ["query"],
        },
    }

    def __init__(self, config: dict):
        self.config = config

    async def execute(self, query: str, num_results: int = 5) -> str:
        num_results = min(max(num_results, 1), 10)

        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=num_results))

            if not results:
                return f"No results found for '{query}'"

            lines = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "No title")
                url = r.get("href", r.get("link", ""))
                snippet = r.get("body", r.get("snippet", ""))
                lines.append(f"{i}. {title}")
                lines.append(f"   URL: {url}")
                lines.append(f"   {snippet}")
                lines.append("")

            return "\n".join(lines)

        except ImportError:
            logger.warning("duckduckgo_search not installed, falling back to HTML scraping")
            return await self._fallback_search(query, num_results)
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return f"Search failed: {e}"

    async def _fallback_search(self, query: str, num_results: int) -> str:
        """Fallback to HTML scraping if duckduckgo_search is not installed."""
        import aiohttp

        url = "https://html.duckduckgo.com/html/"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; 0pnMatrx/1.0)"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data={"q": query}, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return f"Search returned HTTP {resp.status}"
                html = await resp.text()

        results = []
        parts = html.split('class="result__a"')
        for part in parts[1:num_results + 1]:
            title, link, snippet = "", "", ""
            href_start = part.find('href="')
            if href_start != -1:
                href_end = part.find('"', href_start + 6)
                link = part[href_start + 6:href_end]
            tag_end = part.find(">")
            if tag_end != -1:
                close_tag = part.find("</a>", tag_end)
                if close_tag != -1:
                    title = self._strip_tags(part[tag_end + 1:close_tag]).strip()
            sm = part.find('class="result__snippet"')
            if sm != -1:
                st = part.find(">", sm)
                sc = part.find("</", st)
                if st != -1 and sc != -1:
                    snippet = self._strip_tags(part[st + 1:sc]).strip()
            if title and link:
                results.append(f"- {title}\n  {link}\n  {snippet}")

        return "\n".join(results) if results else f"No results for '{query}'"

    @staticmethod
    def _strip_tags(html: str) -> str:
        out, in_tag = [], False
        for c in html:
            if c == "<":
                in_tag = True
            elif c == ">":
                in_tag = False
            elif not in_tag:
                out.append(c)
        return "".join(out)
