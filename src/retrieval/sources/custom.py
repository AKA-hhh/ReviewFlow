"""
自定义 API 检索源。

允许用户从设置页面添加自定义学术检索 API 端点。
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import aiohttp

from src.graph.state import PaperRecord
from src.retrieval.sources.base import BaseSearchSource

logger = logging.getLogger(__name__)


class CustomApiSource(BaseSearchSource):
    """用户自定义的学术检索 API 源"""

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str = "",
        search_path: str = "/search",
        query_param: str = "q",
        limit_param: str = "limit",
        results_path: str = "data",
    ):
        self._name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._search_path = search_path
        self._query_param = query_param
        self._limit_param = limit_param
        self._results_path = results_path
        self._session: Optional[aiohttp.ClientSession] = None

    def source_name(self) -> str:
        return self._name

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {"Accept": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session

    @staticmethod
    def _resolve_path(data: Any, path: str) -> Any:
        """按点号分隔的路径从 JSON 中取值，如 'data.items' → data['data']['items']"""
        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list) and key.isdigit():
                current = current[int(key)]
            else:
                return None
        return current

    async def search(
        self, keywords: List[str], max_results: int = 50
    ) -> List[PaperRecord]:
        """搜索自定义 API"""
        # 构建查询字符串（支持多个关键词 OR 拼接）
        query_parts = [kw.strip() for kw in keywords if kw.strip()]
        query = " OR ".join(query_parts[:5])
        try:
            session = await self._get_session()
            url = (
                f"{self._base_url}{self._search_path}"
                f"?{self._query_param}={quote(query)}"
                f"&{self._limit_param}={min(max_results, 100)}"
            )
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("Custom source [%s] HTTP %d: %s",
                                   self._name, resp.status, await resp.text()[:100])
                    return []
                data = await resp.json()

            items = self._resolve_path(data, self._results_path)
            if not isinstance(items, list):
                items = data if isinstance(data, list) else []

            papers: List[PaperRecord] = []
            for item in items[:max_results]:
                if not isinstance(item, dict):
                    continue
                paper: PaperRecord = {
                    "id": f"custom_{self._name}_{item.get('id', hash(str(item)))}",
                    "title": str(item.get("title", "") or ""),
                    "authors": self._extract_authors(item),
                    "journal": str(item.get("journal") or item.get("venue") or item.get("source") or ""),
                    "year": int(item.get("year") or item.get("publication_year") or 0),
                    "abstract": str(item.get("abstract") or item.get("summary") or "")[:2000],
                    "url": str(item.get("url") or item.get("link") or ""),
                    "source": self._name,
                    "pdf_url": str(item.get("pdf_url") or item.get("pdfUrl") or ""),
                }
                papers.append(paper)

            logger.info("Custom source [%s]: '%s' -> %d papers", self._name, query[:60], len(papers))
            return papers

        except Exception as e:
            logger.warning("Custom source [%s] search failed: %s", self._name, e)
            return []

    @staticmethod
    def _extract_authors(item: dict) -> List[str]:
        """从多种格式中提取作者列表"""
        authors = item.get("authors")
        if isinstance(authors, list):
            result = []
            for a in authors:
                if isinstance(a, str):
                    result.append(a)
                elif isinstance(a, dict):
                    result.append(a.get("name") or a.get("full_name") or str(a))
            return result
        if isinstance(authors, str):
            return [a.strip() for a in authors.split(",")]
        return []

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None

    @staticmethod
    async def test_endpoint(
        base_url: str, api_key: str = "",
        search_path: str = "/search", query_param: str = "q",
        limit_param: str = "limit", results_path: str = "data",
    ) -> Dict[str, Any]:
        """
        测试自定义 API 端点是否可用。

        Returns:
            {"ok": True/False, "message": str, "sample_count": int}
        """
        base_url = base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15), headers=headers
            ) as session:
                url = f"{base_url}{search_path}?{query_param}=test+medicine&{limit_param}=3"
                async with session.get(url) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        return {
                            "ok": False,
                            "message": f"HTTP {resp.status}: {body[:200]}",
                            "sample_count": 0,
                        }
                    data = await resp.json()
        except asyncio.TimeoutError:
            return {"ok": False, "message": "连接超时（>15s），请检查 URL 和网络", "sample_count": 0}
        except aiohttp.ClientError as e:
            return {"ok": False, "message": f"网络错误: {e}", "sample_count": 0}
        except Exception as e:
            return {"ok": False, "message": f"请求失败: {e}", "sample_count": 0}

        # 解析结果（使用用户配置的路径或自动探测）
        items = CustomApiSource._resolve_path(data, results_path)
        if not isinstance(items, list):
            items = data if isinstance(data, list) else data.get("data", data.get("results", []))
        if isinstance(items, list) and len(items) > 0:
            sample_titles = []
            for item in items[:3]:
                title = item.get("title", "") if isinstance(item, dict) else str(item)[:60]
                if title:
                    sample_titles.append(title)
            return {
                "ok": True,
                "message": f"成功！获取到 {len(items)} 条结果（共请求 3 条）",
                "sample_count": len(items),
                "samples": sample_titles,
            }
        else:
            return {
                "ok": True,
                "message": "端点可达但返回结果格式不标准（未找到数据数组）",
                "sample_count": 0,
            }
