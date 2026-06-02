"""
综述生成器（Writer）。

基于结构化数据和章节规划，逐章撰写综述正文。
"""

import json
import logging
import re
from typing import Any, Dict, List

from langchain_core.language_models import BaseChatModel

from src.config.settings import settings
from src.graph.state import ReviewChapter, StructuredPaper

logger = logging.getLogger(__name__)


class ReviewWriter:
    """综述撰写器"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    async def write(
        self,
        query: str,
        chapter_plan: List[ReviewChapter],
        timeline: str,
        clusters: List[Dict[str, Any]],
        conflicts: List[Dict[str, Any]],
        structured_papers: List[StructuredPaper],
        language: str = "zh",
    ) -> str:
        """
        生成完整综述文档。

        Args:
            language: "zh" 中文 / "en" English

        Returns:
            完整的 Markdown 格式综述文档
        """
        lang_instruction = "请用中文撰写整篇综述（包括标题、摘要、正文、参考文献）。" if language == "zh" \
            else "Write the entire review in English (including title, abstract, body, and references)."
        # 构建论文索引（方便按 paper_id 查找）
        paper_index: Dict[str, StructuredPaper] = {}
        for p in structured_papers:
            paper_index[p.get("paper_id", "")] = p

        # 使用主 prompt 模板
        prompt_path = settings.PROMPTS_DIR / "generate_review.txt"
        template = prompt_path.read_text(encoding="utf-8")

        # 格式化供 LLM 使用的结构化数据（精简以减少 token 消耗）
        papers_for_llm = []
        for p in structured_papers:
            sections = p.get("sections", {})
            papers_for_llm.append({
                "id": p.get("paper_id", ""),
                "title": p.get("title", ""),
                "authors": p.get("authors", [])[:3],  # 最多3位作者
                "year": p.get("year", 0),
                "abstract": sections.get("abstract", "")[:200],
                "method": sections.get("method", "")[:150],
                "conclusion": sections.get("conclusion", "")[:150],
                "key_findings": p.get("key_findings", [])[:2],  # 最多2条
            })

        prompt = template.replace("{language}", lang_instruction)
        prompt = prompt.replace("{query}", query)
        prompt = prompt.replace("{timeline}", timeline)
        prompt = prompt.replace("{topic_clusters}", json.dumps(clusters, ensure_ascii=False, indent=2))
        prompt = prompt.replace("{conflicts}", json.dumps(conflicts, ensure_ascii=False, indent=2))
        prompt = prompt.replace(
            "{structured_papers}",
            json.dumps(papers_for_llm, ensure_ascii=False, indent=2),
        )

        try:
            logger.info("开始生成综述 (Context: %d 字符)...", len(prompt))
            response = await self.llm.ainvoke(prompt)
            draft = response.content if hasattr(response, "content") else str(response)

            logger.info("综述草稿生成完成: %d 字符", len(draft))
            return draft

        except Exception as e:
            logger.error("综述生成失败: %s", e)
            # 降级：生成简单版本
            return self._fallback_generate(
                query, chapter_plan, structured_papers
            )

    def _fallback_generate(
        self,
        query: str,
        chapter_plan: List[ReviewChapter],
        structured_papers: List[StructuredPaper],
    ) -> str:
        """降级生成（无需 LLM，直接拼装）"""
        lines = [
            f"# Review: {query}",
            "",
            f"## Abstract",
            f"This review covers {len(structured_papers)} papers on {query}.",
            "",
        ]

        for ch in chapter_plan:
            if ch.get("id") in ("ch1",):
                continue  # Abstract 已处理
            lines.append(f"## {ch.get('title', 'Section')}")
            lines.append("")
            lines.append(ch.get("description", ""))
            lines.append("")
            # 列出关键引用
            for paper_id in ch.get("key_citations", [])[:5]:
                for p in structured_papers:
                    if p.get("paper_id") == paper_id:
                        authors = ", ".join(p.get("authors", [])[:2])
                        year = p.get("year", "")
                        lines.append(
                            f"- **[{authors} ({year})]** {p.get('title', '')}"
                        )
                        break

        lines.append("")
        lines.append("## References")
        lines.append("")
        for i, p in enumerate(structured_papers, 1):
            authors = ", ".join(p.get("authors", [])[:3])
            title = p.get("title", "")
            journal = p.get("journal", "")
            year = p.get("year", "")
            lines.append(f"{i}. {authors} ({year}). *{title}*. {journal}.")

        return "\n".join(lines)
