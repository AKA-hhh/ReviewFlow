"""
Semantic Scholar API 数据源。

通过 Semantic Scholar Academic Graph API 检索学术论文。
免费 tier: 100 请求/5分钟，无需 API key。
"""

import asyncio
import logging
from typing import List
from urllib.parse import quote

import requests

from src.graph.state import PaperRecord
from src.retrieval.sources.base import BaseSearchSource
from src.storage.cache import get_search_cache

logger = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


class SemanticScholarSource(BaseSearchSource):
    """Semantic Scholar 学术数据源"""

    def __init__(self):
        self._cache = get_search_cache()

    def source_name(self) -> str:
        return "semantic_scholar"

    async def search(
        self,
        keywords: List[str],
        max_results: int = 50,
    ) -> List[PaperRecord]:
        """搜索 Semantic Scholar"""
        query_parts = [kw.strip() for kw in keywords if kw.strip()]
        query = " ".join(query_parts[:5])

        cache_key = f"s2:{query}:{max_results}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.info("Semantic Scholar 缓存命中: %s (%d 篇)", query[:80], len(cached))
            return cached

        all_papers: List[PaperRecord] = []
        limit = min(max_results, 100)
        fields = "title,authors,year,abstract,externalIds,url,publicationVenue"
        loop = asyncio.get_event_loop()

        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                url = f"{BASE_URL}?query={quote(query)}&limit={limit}&fields={fields}"
                resp = await loop.run_in_executor(
                    None, lambda: requests.get(url, timeout=30)
                )
                if resp.status_code == 429 and attempt < max_attempts - 1:
                    wait = 10 * (2 ** attempt)
                    logger.warning("S2 HTTP 429，%ds 后重试 (%d/%d)...", wait, attempt + 1, max_attempts)
                    await asyncio.sleep(wait)
                    continue
                elif resp.status_code != 200:
                    logger.warning("S2 API HTTP %d: %s", resp.status_code, resp.text[:200])
                    break

                data = resp.json()
                papers_data = data.get("data", [])

                for p in papers_data:
                    paper_id = p.get("paperId", "")
                    ext_ids = p.get("externalIds", {}) or {}
                    arxiv_id = ext_ids.get("ArXiv", "")

                    authors_list = p.get("authors", []) or []
                    authors = [a.get("name", "") for a in authors_list]

                    venue = p.get("publicationVenue") or {}
                    journal = venue.get("name", "") if venue else ""

                    paper: PaperRecord = {
                        "id": f"s2_{paper_id}",
                        "title": p.get("title", ""),
                        "authors": authors,
                        "journal": journal or "Semantic Scholar",
                        "year": p.get("year", 0),
                        "abstract": (p.get("abstract") or "")[:2000],
                        "url": f"https://api.semanticscholar.org/{paper_id}"
                               if arxiv_id else p.get("url", ""),
                        "source": "semantic_scholar",
                        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
                    }
                    all_papers.append(paper)

                logger.info("S2: '%s' -> %d 篇", query[:80], len(all_papers))
                self._cache.set(cache_key, all_papers, ttl=7200)
                break

            except Exception as e:
                logger.warning("S2 检索失败: %s", e)
                if attempt < max_attempts - 1:
                    await asyncio.sleep(3)
                break

        return all_papers

    async def close(self):
        pass
