"""
DBLP 计算机科学文献数据源。

通过 DBLP Search API 检索 CS 领域论文。
免费 API，无速率限制声明，但建议控制在 1 请求/秒。
"""

import asyncio
import logging
from typing import List
from urllib.parse import quote

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from src.graph.state import PaperRecord
from src.retrieval.sources.base import BaseSearchSource
from src.storage.cache import get_search_cache

logger = logging.getLogger(__name__)

SEARCH_URL = "https://dblp.org/search/publ/api"


class DBLPSource(BaseSearchSource):
    """DBLP 计算机科学文献数据源"""

    def __init__(self):
        self._cache = get_search_cache()

    def source_name(self) -> str:
        return "dblp"

    async def search(
        self,
        keywords: List[str],
        max_results: int = 50,
    ) -> List[PaperRecord]:
        """搜索 DBLP（使用 requests 避免 PyWebView aiohttp 兼容问题）"""
        query = " ".join(kw.strip() for kw in keywords[:4] if kw.strip())

        cache_key = f"dblp:{query}:{max_results}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.info("DBLP 缓存命中: %s (%d 篇)", query[:80], len(cached))
            return cached

        all_papers: List[PaperRecord] = []
        loop = asyncio.get_event_loop()

        try:
            params = {
                "q": query,
                "h": min(max_results, 100),
                "format": "json",
            }
            url = f"{SEARCH_URL}?{'&'.join(f'{k}={quote(str(v))}' for k, v in params.items())}"

            resp = await loop.run_in_executor(
                None, lambda: requests.get(url, timeout=30, verify=False)
            )
            if resp.status_code == 429:
                logger.warning("DBLP HTTP 429 rate limited")
                await asyncio.sleep(5)
                return []
            if resp.status_code != 200:
                logger.warning("DBLP HTTP %d", resp.status_code)
                return []

            data = resp.json()
            hits = data.get("result", {}).get("hits", {}).get("hit", [])

            for hit in hits:
                info = hit.get("info", {})
                title = info.get("title", "")
                year_str = info.get("year", "0")
                try:
                    year = int(year_str)
                except (ValueError, TypeError):
                    year = 0

                venue = info.get("venue", "")
                doi = info.get("doi", "")
                url_link = info.get("url", f"https://dblp.org/rec/{info.get('key', '')}")

                authors_list = info.get("authors", {})
                authors = []
                if isinstance(authors_list, dict):
                    author_entries = authors_list.get("author", [])
                    if isinstance(author_entries, dict):
                        author_entries = [author_entries]
                    for a in author_entries:
                        if isinstance(a, dict):
                            authors.append(a.get("text", ""))
                        elif isinstance(a, str):
                            authors.append(a)

                paper_id = info.get("key", hit.get("id", str(hash(title))))

                paper: PaperRecord = {
                    "id": f"dblp_{paper_id}",
                    "title": title,
                    "authors": authors,
                    "journal": venue or "DBLP",
                    "year": year,
                    "abstract": "",
                    "url": url_link,
                    "source": "dblp",
                    "pdf_url": f"https://doi.org/{doi}" if doi else "",
                }
                all_papers.append(paper)

            logger.info("DBLP: '%s' → %d 篇", query[:80], len(all_papers))
            self._cache.set(cache_key, all_papers, ttl=7200)

        except Exception as e:
            logger.warning("DBLP 检索失败: %s", e)

        return all_papers

    async def close(self):
        pass  # requests 无需手动关闭
