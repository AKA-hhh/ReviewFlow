"""
主题聚类分析器。

基于研究方法和应用场景对文献进行自动聚类分组。
"""

import json
import logging
import re
from typing import Any, Dict, List

from langchain_core.language_models import BaseChatModel

from src.config.settings import settings
from src.graph.state import StructuredPaper

logger = logging.getLogger(__name__)


class TopicClusterer:
    """主题聚类分析器"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    async def cluster(
        self,
        papers: List[StructuredPaper],
        query: str,
    ) -> Dict[str, Any]:
        """
        对论文集合进行主题聚类。

        Returns:
            {
                "clusters": [...],
                "outliers": [...],
                "cross_cluster_connections": [...]
            }
        """
        if not papers:
            return {
                "clusters": [],
                "outliers": [],
                "cross_cluster_connections": [],
            }

        # 构建精简数据
        papers_json = []
        for p in papers:
            papers_json.append({
                "id": p.get("paper_id", ""),
                "title": p.get("title", ""),
                "year": p.get("year", 0),
                "abstract": p.get("sections", {}).get("abstract", "")[:300],
                "method": p.get("sections", {}).get("method", "")[:200],
                "key_findings": p.get("key_findings", [])[:2],
            })

        prompt_path = settings.PROMPTS_DIR / "clustering.txt"
        template = prompt_path.read_text(encoding="utf-8")

        prompt = template.replace("{papers_json}", json.dumps(papers_json, ensure_ascii=False, indent=2))
        prompt = prompt.replace("{query}", query)

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            content = re.sub(r"```(?:json)?\s*", "", content)
            content = re.sub(r"```", "", content).strip()

            result = json.loads(content)

            logger.info(
                "主题聚类完成: %d 个聚类, %d 篇孤立论文",
                len(result.get("clusters", [])),
                len(result.get("outliers", [])),
            )
            return result
        except Exception as e:
            logger.error("主题聚类失败: %s", e)
            return {"clusters": [], "outliers": [], "cross_cluster_connections": []}
