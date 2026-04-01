"""
Web Search Tool — search the internet for information.

Uses a configurable search backend. Results are returned as
structured text for the agent to reason about.
"""

import logging

import aiohttp

logger = logging.getLogger(__name__)


class WebSearchTool:
    name = "web_search"
    schema = {
        "name": "web_search",
        "description": "Search the internet for current information. Returns titles, URLs, and snippets.",
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
        num_results = min(num_results, 10)

        try:
            results = await self._search_duckduckgo(query, num_results)
            if not results:
                return f"No results found for '{query}'"

            lines = []
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r['title']}")
                lines.append(f"   {r['url']}")
                lines.append(f"   {r['snippet']}")
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return f"Search failed: {e}"

    async def _search_duckduckgo(self, query: str, num_results: int) -> list[dict]:
        """Use DuckDuckGo HTML search as a free, no-API-key search backend."""
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; 0pnMatrx/1.0)",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                data={"q": query},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()

        return self._parse_results(html, num_results)

    def _parse_results(self, html: str, num_results: int) -> list[dict]:
        """Parse search results from DuckDuckGo HTML response."""
        results = []
        parts = html.split('class="result__a"')

        for part in parts[1:num_results + 1]:
            title = ""
            url = ""
            snippet = ""

            href_start = part.find('href="')
            if href_start != -1:
                href_end = part.find('"', href_start + 6)
                url = part[href_start + 6:href_end]

            tag_end = part.find(">")
            if tag_end != -1:
                close_tag = part.find("</a>", tag_end)
                if close_tag != -1:
                    title = part[tag_end + 1:close_tag]
                    title = self._strip_tags(title).strip()

            snippet_marker = 'class="result__snippet"'
            snippet_start = part.find(snippet_marker)
            if snippet_start != -1:
                s_tag_end = part.find(">", snippet_start)
                s_close = part.find("</", s_tag_end)
                if s_tag_end != -1 and s_close != -1:
                    snippet = self._strip_tags(part[s_tag_end + 1:s_close]).strip()

            if title and url:
                results.append({"title": title, "url": url, "snippet": snippet})

        return results

    @staticmethod
    def _strip_tags(html: str) -> str:
        result = []
        in_tag = False
        for char in html:
            if char == "<":
                in_tag = True
            elif char == ">":
                in_tag = False
            elif not in_tag:
                result.append(char)
        return "".join(result)
