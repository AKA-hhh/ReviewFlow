"""
结构化信息抽取器。

使用 LLM 对论文章节内容进行结构化抽取，生成标准化 JSON。
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel

from src.config.settings import settings
from src.graph.state import PaperRecord, StructuredPaper
from src.storage.cache import get_summary_cache

logger = logging.getLogger(__name__)


class StructuredExtractor:
    """
    结构化信息抽取器。

    对切分后的论文章节进行 LLM 驱动的结构化抽取，
    输出包含摘要、方法、实验、结论、关键发现、引用的标准化 JSON。
    """

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self._cache = get_summary_cache()

    async def extract(
        self,
        paper: PaperRecord,
        sections: Dict[str, str],
        query: str,
    ) -> StructuredPaper:
        """
        对单篇论文进行结构化抽取。

        Args:
            paper: 论文元数据
            sections: 切分后的章节
            query: 用户研究主题（用于聚焦抽取）

        Returns:
            StructuredPaper
        """
        paper_id = paper.get("id", "unknown")
        title = paper.get("title", "")

        # 检查缓存
        cache_key = f"extract:{paper_id}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.info("抽取缓存命中: %s", title[:50])
            return cached

        try:
            prompt_path = settings.PROMPTS_DIR / "summarize.txt"
            template = prompt_path.read_text(encoding="utf-8")

            # 提取 paper 元数据
            title = paper.get("title", "")
            authors = ", ".join(paper.get("authors", [])[:5])
            year = str(paper.get("year", ""))
            abstract = paper.get("abstract", "")
            sections_str = json.dumps(sections, ensure_ascii=False, indent=2) if sections else "{}"

            prompt = template.replace("{title}", title)
            prompt = prompt.replace("{authors}", authors)
            prompt = prompt.replace("{year}", year)
            prompt = prompt.replace("{abstract}", abstract[:3000])
            prompt = prompt.replace("{sections}", sections_str if sections_str != "{}" else "(无全文数据，请仅根据摘要提取)")
            prompt = prompt.replace("{query}", query)

            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            if not content or not content.strip():
                raise ValueError("LLM 返回空响应")

            # 清理 JSON：移除 markdown 代码块标记
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*\n?", "", content)
                content = re.sub(r"\n?```\s*$", "", content)
            content = content.strip()

            data = json.loads(content)

            result: StructuredPaper = {
                "paper_id": paper_id,
                "title": title,
                "authors": paper.get("authors", []),
                "journal": paper.get("journal", ""),
                "year": paper.get("year", 0),
                "url": paper.get("url", ""),
                "source": paper.get("source", ""),
                "relevance_score": paper.get("rerank_score", 0.0),
                "relevance_level": "mid",
                "sections": data.get("sections", sections),
                "key_findings": data.get("key_findings", []),
                "key_citations": data.get("key_citations", []),
            }

            # 缓存（永久，因为抽取成本高）
            self._cache.set(cache_key, result, ttl=86400 * 30)

            logger.info("结构化抽取完成: %s", title[:50])
            return result

        except Exception as e:
            logger.error("结构化抽取失败 [%s]: %s", paper_id, e)
            # 降级：返回基础信息
            return {
                "paper_id": paper_id,
                "title": title,
                "authors": paper.get("authors", []),
                "journal": paper.get("journal", ""),
                "year": paper.get("year", 0),
                "url": paper.get("url", ""),
                "source": paper.get("source", ""),
                "relevance_score": paper.get("rerank_score", 0.0),
                "relevance_level": "low",
                "sections": {"abstract": paper.get("abstract", "")},
                "key_findings": [],
                "key_citations": [],
            }

    async def extract_batch(
        self,
        papers: List[PaperRecord],
        sections_map: Dict[str, Dict[str, str]],
        query: str,
    ) -> List[StructuredPaper]:
        """批量抽取多篇论文"""
        results = []
        for paper in papers:
            paper_id = paper.get("id", "")
            sections = sections_map.get(paper_id, {})
            result = await self.extract(paper, sections, query)
            results.append(result)
        return results
