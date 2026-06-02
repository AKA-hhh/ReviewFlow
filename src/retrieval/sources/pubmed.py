"""
PubMed / NCBI Entrez 数据源。

通过 NCBI Entrez API 检索生物医学文献。
免费 API，限 3 请求/秒（无 key）或 10 请求/秒（有 key）。
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

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class PubMedSource(BaseSearchSource):
    """PubMed 生物医学文献数据源"""

    def __init__(self):
        self._cache = get_search_cache()

    def source_name(self) -> str:
        return "pubmed"

    async def search(
        self,
        keywords: List[str],
        max_results: int = 50,
    ) -> List[PaperRecord]:
        """搜索 PubMed（使用 requests 避免 PyWebView aiohttp 兼容问题）"""
        query = " ".join(kw.strip() for kw in keywords[:5] if kw.strip())

        cache_key = f"pubmed:{query}:{max_results}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.info("PubMed 缓存命中: %s (%d 篇)", query[:80], len(cached))
            return cached

        all_papers: List[PaperRecord] = []
        loop = asyncio.get_event_loop()

        try:
            # Step 1: ESearch → 获取 PMID 列表
            esearch_params = {
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": "relevance",
            }
            esearch_url = f"{ESEARCH_URL}?{'&'.join(f'{k}={quote(str(v))}' for k, v in esearch_params.items())}"

            resp = await loop.run_in_executor(
                None, lambda: requests.get(esearch_url, timeout=30)
            )
            if resp.status_code != 200:
                logger.warning("PubMed ESearch HTTP %d", resp.status_code)
                return []
            data = resp.json()
            pmids = data.get("esearchresult", {}).get("idlist", [])

            if not pmids:
                logger.info("PubMed: '%s' → 0 篇", query[:80])
                return []

            # 速率限制
            await asyncio.sleep(0.35)

            # Step 2: EFetch → 获取摘要
            efetch_params = {
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "xml",
            }
            efetch_url = f"{EFETCH_URL}?{'&'.join(f'{k}={quote(str(v))}' for k, v in efetch_params.items())}"

            resp2 = await loop.run_in_executor(
                None, lambda: requests.get(efetch_url, timeout=30)
            )
            if resp2.status_code != 200:
                logger.warning("PubMed EFetch HTTP %d", resp2.status_code)
                return []
            xml_text = resp2.text

            # 解析 XML（简易解析避免额外依赖）
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_text)

            for article in root.findall(".//PubmedArticle"):
                try:
                    medline = article.find(".//MedlineCitation")
                    if medline is None:
                        continue

                    pmid_elem = medline.find("PMID")
                    pmid = pmid_elem.text if pmid_elem is not None else ""

                    article_data = medline.find("Article")
                    if article_data is None:
                        continue

                    title_elem = article_data.find("ArticleTitle")
                    title = title_elem.text or "" if title_elem is not None else ""

                    abstract_elem = article_data.find("Abstract")
                    abstract = ""
                    if abstract_elem is not None:
                        parts = abstract_elem.findall("AbstractText")
                        abstract = " ".join(p.text or "" for p in parts)

                    journal_elem = article_data.find("Journal")
                    journal = ""
                    year = 0
                    if journal_elem is not None:
                        jtitle = journal_elem.find("Title")
                        journal = jtitle.text or "" if jtitle is not None else ""
                        pubdate = journal_elem.find("JournalIssue/PubDate")
                        if pubdate is not None:
                            y = pubdate.find("Year")
                            if y is not None and y.text:
                                try:
                                    year = int(y.text)
                                except ValueError:
                                    pass

                    authors = []
                    author_list = article_data.find("AuthorList")
                    if author_list is not None:
                        for auth in author_list.findall("Author"):
                            last = auth.find("LastName")
                            fore = auth.find("ForeName")
                            if last is not None:
                                name = last.text or ""
                                if fore is not None and fore.text:
                                    name = f"{fore.text} {name}"
                                authors.append(name)

                    paper: PaperRecord = {
                        "id": f"pubmed_{pmid}",
                        "title": title,
                        "authors": authors,
                        "journal": journal,
                        "year": year,
                        "abstract": abstract[:2000],
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "source": "pubmed",
                        "pdf_url": "",
                    }
                    all_papers.append(paper)
                except Exception as e:
                    logger.debug("PubMed 解析单篇失败: %s", e)
                    continue

            logger.info("PubMed: '%s' → %d 篇", query[:80], len(all_papers))
            self._cache.set(cache_key, all_papers, ttl=7200)

        except Exception as e:
            logger.warning("PubMed 检索失败: %s", e)

        return all_papers

    async def close(self):
        pass  # requests 无需手动关闭
