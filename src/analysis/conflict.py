"""
观点冲突识别器。

识别不同论文之间的结论冲突、方法论争议和待解决开放问题。
"""

import json
import logging
import re
from typing import Any, Dict, List

from langchain_core.language_models import BaseChatModel

from src.config.settings import settings
from src.graph.state import StructuredPaper

logger = logging.getLogger(__name__)


class ConflictDetector:
    """观点冲突识别器"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    async def detect(
        self,
        papers: List[StructuredPaper],
        query: str,
    ) -> Dict[str, Any]:
        """
        识别论文间的观点冲突和方法论差异。

        Returns:
            {
                "conflicts": [...],
                "open_questions": [...]
            }
        """
        if not papers:
            return {"conflicts": [], "open_questions": []}

        # 构建数据：关注方法和结论
        papers_json = []
        for p in papers:
            sections = p.get("sections", {})
            papers_json.append({
                "id": p.get("paper_id", ""),
                "title": p.get("title", ""),
                "year": p.get("year", 0),
                "method": sections.get("method", "")[:400],
                "conclusion": sections.get("conclusion", "")[:400],
                "key_findings": p.get("key_findings", []),
            })

        prompt_path = settings.PROMPTS_DIR / "conflict.txt"
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
                "冲突识别完成: %d 个冲突, %d 个开放问题",
                len(result.get("conflicts", [])),
                len(result.get("open_questions", [])),
            )
            return result
        except Exception as e:
            logger.error("冲突识别失败: %s", e)
            return {"conflicts": [], "open_questions": []}
