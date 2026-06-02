"""
三层相关性评分器。

对检索到的论文进行三层递进式相关性评分：
  L1: 标题+摘要快速筛选 (阈值 0.9)
  L2: 方法+实验深度评估 (阈值 0.8)
  L3: 全文综合评估 (阈值 0.7)
"""

import json
import logging
import re
from typing import Any, Dict, List

from langchain_core.language_models import BaseChatModel

from src.config.settings import settings
from src.graph.state import PaperRecord

logger = logging.getLogger(__name__)


class RelevanceScorer:
    """
    三层相关性评分器。

    采用递进式评估策略：
    - L1 (高阈值 0.9): 仅需标题+摘要即可判断高相关，通过的论文直接进入下一阶段
    - L2 (中阈值 0.8): 需方法+实验章节，用于精细评估
    - L3 (低阈值 0.7): 全文综合兜底判断
    """

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    async def score_single(
        self,
        paper: PaperRecord,
        query: str,
        sections: Dict[str, str] = None,
        level: int = 1,
    ) -> Dict[str, Any]:
        """
        对单篇论文进行相关性评估。

        Args:
            paper: 论文信息
            query: 用户研究主题
            sections: 切分后的章节（L2/L3需要）
            level: 评估层级 (1/2/3)

        Returns:
            {"relevance_score": float, "relevance_level": str, "reasoning": str}
        """
        prompt_path = settings.PROMPTS_DIR / "relevance_scoring.txt"
        template = prompt_path.read_text(encoding="utf-8")

        title = paper.get("title", "")
        authors = ", ".join(paper.get("authors", [])[:3])
        abstract = paper.get("abstract", "")

        # L2/L3: 补充方法+实验信息
        extra_context = ""
        if level >= 2 and sections:
            extra_context += f"\n方法章节摘要: {sections.get('method', '')[:500]}"
            extra_context += f"\n实验章节摘要: {sections.get('experiment', '')[:500]}"
        if level >= 3 and sections:
            extra_context += f"\n结论章节: {sections.get('conclusion', '')[:300]}"

        prompt = template.replace("{query}", query)
        prompt = prompt.replace("{title}", title)
        prompt = prompt.replace("{authors}", authors)
        prompt = prompt.replace("{abstract}", abstract + extra_context)

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            content = re.sub(r"```(?:json)?\s*", "", content)
            content = re.sub(r"```", "", content).strip()

            result = json.loads(content)
            return {
                "relevance_score": float(result.get("relevance_score", 0.5)),
                "relevance_level": result.get("relevance_level", "mid"),
                "reasoning": result.get("reasoning", ""),
            }
        except Exception as e:
            logger.error("相关性评分失败: %s", e)
            return {"relevance_score": 0.5, "relevance_level": "mid", "reasoning": "评分异常"}

    async def filter_papers(
        self,
        papers: List[PaperRecord],
        query: str,
    ) -> List[PaperRecord]:
        """
        三层递进式筛选。

        返回通过筛选的论文列表，并附上 relevance_score 和 relevance_level。
        """
        if not papers:
            return []

        scored_papers = []

        # L1: 标题+摘要快速筛选
        for paper in papers:
            score_result = await self.score_single(paper, query, level=1)
            score = score_result["relevance_score"]

            if score >= settings.RELEVANCE_THRESHOLD_HIGH:
                paper["relevance_score"] = score
                paper["relevance_level"] = "high"
                scored_papers.append(paper)
            elif score >= settings.RELEVANCE_THRESHOLD_LOW:
                # 进入 L2
                paper["_l1_score"] = score
                scored_papers.append(paper)
            # else: 丢弃

        logger.info(
            "L1 筛选: %d → %d (阈值≥%.1f)",
            len(papers), len(scored_papers), settings.RELEVANCE_THRESHOLD_LOW,
        )

        # L2/L3 对中低分论文进一步评估（实际项目中需要章节数据，这里做简化处理）
        final_papers = []
        for paper in scored_papers:
            level = paper.get("relevance_level", "mid")
            if level == "high":
                final_papers.append(paper)
            else:
                # 对 mid/low 级别进行更深层评估
                score_result = await self.score_single(paper, query, level=2)
                paper["relevance_score"] = score_result["relevance_score"]
                paper["relevance_level"] = score_result["relevance_level"]
                if score_result["relevance_score"] >= settings.RELEVANCE_THRESHOLD_LOW:
                    final_papers.append(paper)

        logger.info(
            "最终筛选: %d 篇通过（high=%d, mid=%d, low=%d）",
            len(final_papers),
            sum(1 for p in final_papers if p.get("relevance_level") == "high"),
            sum(1 for p in final_papers if p.get("relevance_level") == "mid"),
            sum(1 for p in final_papers if p.get("relevance_level") == "low"),
        )
        return final_papers
