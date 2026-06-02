"""
时间线依赖分析器。

识别论文间的技术演进路径、里程碑论文和技术趋势。
"""

import json
import logging
import re
from typing import Any, Dict, List

from langchain_core.language_models import BaseChatModel

from src.config.settings import settings
from src.graph.state import StructuredPaper

logger = logging.getLogger(__name__)


class TimelineAnalyzer:
    """时间线依赖分析器"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    async def analyze(
        self,
        papers: List[StructuredPaper],
        query: str,
    ) -> Dict[str, Any]:
        """
        分析论文集合的时间线依赖关系。

        Returns:
            {
                "timeline": str,           # 自然语言描述
                "milestones": [...],       # 里程碑论文
                "dependencies": [...],     # 依赖关系
                "trends": [...]            # 技术趋势
            }
        """
        if not papers:
            return {
                "timeline": "无文献数据",
                "milestones": [],
                "dependencies": [],
                "trends": [],
            }

        # 按年份排序
        sorted_papers = sorted(papers, key=lambda p: p.get("year", 0))

        # 构建精简的论文数据（减少 token 消耗）
        papers_json = []
        for p in sorted_papers:
            papers_json.append({
                "id": p.get("paper_id", ""),
                "title": p.get("title", ""),
                "year": p.get("year", 0),
                "key_findings": p.get("key_findings", [])[:3],
                "method_summary": p.get("sections", {}).get("method", "")[:300],
            })

        prompt_path = settings.PROMPTS_DIR / "timeline.txt"
        template = prompt_path.read_text(encoding="utf-8")

        prompt = template.replace("{papers_json}", json.dumps(papers_json, ensure_ascii=False, indent=2))
        prompt = prompt.replace("{query}", query)

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            content = re.sub(r"```(?:json)?\s*", "", content)
            content = re.sub(r"```", "", content).strip()

            result = json.loads(content)

            logger.info("时间线分析完成: %d 篇论文", len(papers))
            return {
                "timeline": result.get("timeline", ""),
                "milestones": result.get("milestones", []),
                "dependencies": result.get("dependencies", []),
                "trends": result.get("trends", []),
            }
        except Exception as e:
            logger.error("时间线分析失败: %s", e)
            return {
                "timeline": f"共 {len(papers)} 篇论文，时间跨度 {sorted_papers[0].get('year', 0)}-{sorted_papers[-1].get('year', 0)}",
                "milestones": [],
                "dependencies": [],
                "trends": [],
            }
