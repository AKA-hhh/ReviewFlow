"""
引用溯源验证器。

对综述草稿中的每个引用进行原文验证，防止模型幻觉产生不存在的引用。
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Set, Tuple

from langchain_core.language_models import BaseChatModel

from src.graph.state import StructuredPaper

logger = logging.getLogger(__name__)

# 引用格式：匹配编号引用 [1] [2,3] [1-3] 或 Author-Year 格式
CITATION_PATTERN = re.compile(
    r"\[(\d+(?:[\s,\-]\d+)*)\]"          # [1] [2,3] [1-3]
    r"|\[([^\]]*?\d{4})\]"               # [Author-2024]
    r"|\(([^)]*?\d{4})\)"                # (Author, 2024)
)


class CitationChecker:
    """引用溯源验证器"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    async def verify(
        self,
        draft: str,
        structured_papers: List[StructuredPaper],
    ) -> Dict[str, Any]:
        """
        验证综述草稿中的所有引用。

        Returns:
            {
                "verified": [...],      # 验证通过的引用
                "suspicious": [...],    # 可疑引用（找不到原文支撑）
                "missing": [...],       # 完全找不到的引用
                "verified_count": int,
                "suspicious_count": int,
                "total_count": int,
            }
        """
        # 提取所有引用标记
        citations_in_draft = self._extract_citations(draft)
        logger.info("草稿中共发现 %d 个引用标记", len(citations_in_draft))

        # 构建可验证的引用来源集合
        valid_sources: Set[str] = set()
        paper_title_map: Dict[str, StructuredPaper] = {}

        for p in structured_papers:
            paper_id = p.get("paper_id", "")
            title = p.get("title", "").lower()
            authors = p.get("authors", [])
            year = str(p.get("year", ""))

            # 生成多种可能的引用格式
            if authors and year:
                first_author = authors[0].split()[-1] if authors else ""  # 取姓
                key1 = f"{first_author}-{year}".lower()
                key2 = f"{first_author} et al.-{year}".lower()
                key3 = f"{first_author} ({year})".lower()
                valid_sources.update([key1, key2, key3])

            paper_title_map[title[:100]] = p
            valid_sources.add(paper_id)

        # 验证每个引用（先用规则匹配，未匹配的并行 LLM 验证）
        verified = []
        suspicious = []
        need_llm_verify: List[str] = []  # 需要 LLM 辅助验证的引用

        for citation in citations_in_draft:
            citation_lower = citation.lower()
            is_verified = False

            # 尝试匹配 valid_sources
            for source in valid_sources:
                if source in citation_lower or citation_lower in source:
                    verified.append({
                        "citation": citation,
                        "matched_source": source,
                        "status": "verified",
                    })
                    is_verified = True
                    break

            if not is_verified:
                need_llm_verify.append(citation)

        # 并行 LLM 辅助验证（对未匹配到的引用）
        if need_llm_verify:
            llm_tasks = [
                self._llm_verify(citation, structured_papers)
                for citation in need_llm_verify
            ]
            llm_results = await asyncio.gather(*llm_tasks, return_exceptions=True)

            for citation, llm_verified in zip(need_llm_verify, llm_results):
                if isinstance(llm_verified, Exception):
                    suspicious.append({
                        "citation": citation,
                        "reason": f"验证异常: {llm_verified}",
                        "status": "suspicious",
                    })
                elif isinstance(llm_verified, dict) and llm_verified.get("found"):
                    verified.append({
                        "citation": citation,
                        "matched_source": llm_verified.get("paper_title", ""),
                        "status": "verified_by_llm",
                    })
                else:
                    suspicious.append({
                        "citation": citation,
                        "reason": llm_verified.get("reason", "未找到原文支撑") if isinstance(llm_verified, dict) else "未找到原文支撑",
                        "status": "suspicious",
                    })

        result = {
            "verified": verified,
            "suspicious": suspicious,
            "verified_count": len(verified),
            "suspicious_count": len(suspicious),
            "total_count": len(citations_in_draft),
        }

        logger.info(
            "引用验证: %d/%d 通过, %d 可疑",
            result["verified_count"],
            result["total_count"],
            result["suspicious_count"],
        )
        return result

    def _extract_citations(self, text: str) -> List[str]:
        """从文本中提取引用标记"""
        citations = []
        for match in CITATION_PATTERN.finditer(text):
            citation = match.group(1) or match.group(2)
            if citation:
                citations.append(citation.strip())
        return list(set(citations))  # 去重

    async def _llm_verify(
        self,
        citation: str,
        structured_papers: List[StructuredPaper],
    ) -> Dict[str, Any]:
        """使用 LLM 辅助验证单个引用"""
        # 构建论文标题列表供 LLM 参考
        titles_list = "\n".join(
            f"- {p.get('title', '')}" for p in structured_papers
        )

        prompt = f"""请判断以下引用标记是否能在给定的论文列表中找到对应原文。

引用标记: {citation}

论文列表:
{titles_list}

如果引用标记中的作者/年份与某篇论文的作者/年份对应，说明"找到"。
如果没有对应关系，说明"未找到"。

请以 JSON 输出：
{{"found": true/false, "paper_title": "匹配的论文标题（如找到）", "reason": "判断理由"}}
"""

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            content = re.sub(r"```(?:json)?\s*", "", content)
            content = re.sub(r"```", "", content).strip()

            import json
            return json.loads(content)
        except Exception as e:
            logger.warning("LLM 引用验证失败: %s", e)
            return {"found": False, "reason": str(e)}
