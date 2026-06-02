"""
arXiv API 数据源。

通过 arxiv Python 库查询 arXiv.org 学术论文。
支持镜像站点和超时重试。
"""

import asyncio
import logging
import os
import socket
from typing import List

import arxiv

from src.graph.state import PaperRecord
from src.retrieval.sources.base import BaseSearchSource
from src.storage.cache import get_search_cache

logger = logging.getLogger(__name__)

# arXiv API 端点（可通过环境变量配置镜像）
_ARXIV_API_URL = os.getenv("ARXIV_API_URL", "https://export.arxiv.org")
_ARXIV_TIMEOUT = int(os.getenv("ARXIV_TIMEOUT", "60"))


class ArxivSource(BaseSearchSource):
    """arXiv 学术数据源"""

    def __init__(self):
        # 设置 socket 超时防止长时间挂起
        socket.setdefaulttimeout(_ARXIV_TIMEOUT)
        self._client = arxiv.Client(
            page_size=50,
            delay_seconds=5.0,     # 提高延迟避免 HTTP 429
            num_retries=5,
        )
        self._cache = get_search_cache()

    def source_name(self) -> str:
        return "arxiv"

    def _build_queries(self, keywords: List[str]) -> List[str]:
        """构建多个查询策略（从精确到宽松），中英文分词避免混合 AND 返回空"""
        # 分离中英文关键词
        en_words = []
        zh_words = []
        seen = set()
        for kw in keywords:
            for w in kw.split():
                w = w.strip().lower()
                if len(w) >= 2 and w not in seen:
                    seen.add(w)
                    if any('一' <= c <= '鿿' for c in w):
                        zh_words.append(w)
                    else:
                        en_words.append(w)

        queries = []

        # 策略1: 英文核心词 AND（精确匹配 arXiv 索引）
        if len(en_words) >= 2:
            queries.append(" AND ".join(en_words[:4]))

        # 策略2: 中文关键词 OR（arXiv 中文论文较少，宽松匹配）
        if zh_words:
            queries.append(" OR ".join(zh_words[:3]))

        # 策略3: 英文 + 中文混合 OR（中精确）
        clean_keywords = [" ".join(kw.split()) for kw in keywords[:3] if kw.strip()]
        if clean_keywords:
            queries.append(" OR ".join(clean_keywords))

        # 策略4: 只用第一个英文核心词（兜底）
        if en_words:
            queries.append(en_words[0])
        elif zh_words:
            queries.append(zh_words[0])

        return queries

    async def search(
        self,
        keywords: List[str],
        max_results: int = 50,
    ) -> List[PaperRecord]:
        """异步搜索 arXiv，多策略尝试直到获取足够结果"""
        all_papers: dict = {}  # 用 dict 去重

        queries = self._build_queries(keywords)
        logger.info("arXiv 检索策略: %d 种查询", len(queries))

        for i, query in enumerate(queries):
            cache_key = f"arxiv:{query}:{max_results}"
            cached = self._cache.get(cache_key)
            if cached:
                for p in cached:
                    all_papers[p["id"]] = p
                logger.info("arXiv 缓存命中[策略%d]: %s (%d 篇)", i+1, query[:80], len(cached))
                if len(all_papers) >= max_results:
                    break
                continue

            # 多策略间加延迟，避免 429
            if i > 0:
                await asyncio.sleep(2.0)

            # HTTP 429/超时重试（最多 3 次，指数退避）
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    loop = asyncio.get_event_loop()
                    search = arxiv.Search(
                        query=query,
                        max_results=max_results,
                        sort_by=arxiv.SortCriterion.Relevance,
                    )
                    results = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: list(self._client.results(search))),
                        timeout=_ARXIV_TIMEOUT,
                    )

                    papers = []
                    for result in results:
                        paper: PaperRecord = {
                            "id": f"arxiv_{result.get_short_id()}",
                            "title": result.title,
                            "authors": [str(a) for a in result.authors],
                            "journal": "arXiv preprint",
                            "year": result.published.year if result.published else 0,
                            "abstract": result.summary.replace("\n", " "),
                            "url": result.entry_id,
                            "source": "arxiv",
                            "pdf_url": result.pdf_url,
                        }
                        papers.append(paper)
                        all_papers[paper["id"]] = paper

                    logger.info("arXiv[策略%d]: '%s' → %d 篇 (累计 %d)", i+1, query[:80], len(papers), len(all_papers))
                    self._cache.set(cache_key, papers, ttl=3600)
                    break  # 成功，跳出重试循环

                except asyncio.TimeoutError:
                    logger.warning("arXiv[策略%d] 请求超时 (>%ds)，检查网络或设置 ARXIV_MIRROR 环境变量",
                                   i+1, _ARXIV_TIMEOUT)
                    break
                except Exception as e:
                    err_msg = str(e)
                    if "429" in err_msg and attempt < max_attempts - 1:
                        wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
                        logger.warning("arXiv[策略%d] HTTP 429，%ds 后重试 (%d/%d)...", i+1, wait, attempt+1, max_attempts)
                        await asyncio.sleep(wait)
                    elif "timeout" in err_msg.lower() or "timed out" in err_msg.lower():
                        logger.warning("arXiv[策略%d] 连接超时: %s", i+1, e)
                        break
                    else:
                        logger.warning("arXiv[策略%d] 失败: %s", i+1, e)
                        break  # 非可恢复错误，跳出

            # 获取足够结果就停止
            if len(all_papers) >= max_results:
                break

        papers_list = list(all_papers.values())
        logger.info("arXiv 检索完成: %d 个关键词 → %d 篇（多策略合并去重）", len(keywords), len(papers_list))
        return papers_list
