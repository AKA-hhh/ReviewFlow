"""
综述章节结构规划器。

基于文献分析结果（时间线、聚类、冲突），规划综述的章节结构。
"""

import json
import logging
import re
from typing import Any, Dict, List

from langchain_core.language_models import BaseChatModel

from src.graph.state import ReviewChapter, StructuredPaper

logger = logging.getLogger(__name__)


class ReviewPlanner:
    """综述章节结构规划器"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    async def plan(
        self,
        query: str,
        timeline_data: Dict[str, Any],
        clusters: List[Dict[str, Any]],
        conflicts: List[Dict[str, Any]],
        structured_papers: List[StructuredPaper],
    ) -> List[ReviewChapter]:
        """
        规划综述的章节结构。

        标准结构：
        1. Abstract
        2. Introduction
        3-7. 按主题聚类组织的核心章节
        8. Discussion (时间线、冲突、开放问题)
        9. Conclusion
        10. References

        Returns:
            章节列表，含依赖关系和关键引用
        """
        n_papers = len(structured_papers)
        n_clusters = len(clusters)

        if n_papers == 0:
            return [
                {
                    "id": "ch1",
                    "title": "Abstract",
                    "description": "未找到相关文献",
                    "depends_on": [],
                    "key_citations": [],
                    "content": "未能检索到与查询主题相关的学术文献。",
                }
            ]

        # 构建规划 prompt（精简数据以减少 token 消耗）
        clusters_brief = [{
            "name": c.get("cluster_name", ""),
            "papers": len(c.get("paper_ids", [])),
            "desc": c.get("description", "")[:150],
        } for c in clusters]

        plan_prompt = f"""你是一位资深的学术综述撰写专家。请根据以下文献分析结果，规划综述的章节结构。

## 综述主题
{query}

## 文献概况
- 共 {n_papers} 篇文献，分 {n_clusters} 个主题聚类

## 主题聚类
{json.dumps(clusters_brief, ensure_ascii=False, indent=2)[:1200]}

## 观点冲突
{json.dumps(conflicts, ensure_ascii=False, indent=2)[:600]}

## 要求
1. 遵循学术综述标准结构（Abstract → Introduction → 3~5个主题章节 → Discussion → Conclusion）
2. 每个主题聚类对应一个核心章节
3. 标注章节间依赖关系和关键引用 paper_id

请以 JSON 格式输出：
{{"chapters": [{{"id": "ch1", "title": "...", "description": "...", "depends_on": [], "key_citations": []}}]}}
"""

        try:
            response = await self.llm.ainvoke(plan_prompt)
            content = response.content if hasattr(response, "content") else str(response)
            content = re.sub(r"```(?:json)?\s*", "", content)
            content = re.sub(r"```", "", content).strip()

            data = json.loads(content)
            chapters: List[ReviewChapter] = []
            for ch in data.get("chapters", []):
                chapters.append({
                    "id": ch.get("id", ""),
                    "title": ch.get("title", ""),
                    "description": ch.get("description", ""),
                    "depends_on": ch.get("depends_on", []),
                    "key_citations": ch.get("key_citations", []),
                    "content": "",
                })

            logger.info("章节规划完成: %d 个章节", len(chapters))
            return chapters
        except Exception as e:
            logger.error("章节规划失败: %s", e)
            # 降级：简单按主题聚类生成章节
            chapters: List[ReviewChapter] = [
                {"id": "ch1", "title": "Abstract", "description": "综述摘要", "depends_on": [], "key_citations": [], "content": ""},
                {"id": "ch2", "title": "Introduction", "description": f"关于 {query} 的研究综述", "depends_on": [], "key_citations": [], "content": ""},
            ]
            for i, cluster in enumerate(clusters):
                chapters.append({
                    "id": f"ch{i+3}",
                    "title": cluster.get("cluster_name", f"Topic {i+1}"),
                    "description": cluster.get("description", ""),
                    "depends_on": ["ch2"],
                    "key_citations": cluster.get("paper_ids", []),
                    "content": "",
                })
            chapters.append({
                "id": f"ch{len(chapters)+1}",
                "title": "Discussion",
                "description": "综合讨论与未来方向",
                "depends_on": [ch["id"] for ch in chapters if ch["id"] not in ("ch1",)],
                "key_citations": [],
                "content": "",
            })
            return chapters
