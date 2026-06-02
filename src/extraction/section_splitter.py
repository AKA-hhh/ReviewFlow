"""
论文全文章节切分器。

使用正则表达式识别学术论文常见的章节标题，将全文切分为结构化段落。
"""

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 章节标题正则模式（中英文）
SECTION_PATTERNS: Dict[str, List[str]] = {
    "abstract": [
        r"(?i)^\s*(?:abstract|摘要|概要)\s*$",
    ],
    "introduction": [
        r"(?i)^\s*(?:\d+\.?\s*)?(?:introduction|引言|背景|background|related\s*work|相关工作|文献综述)\s*$",
    ],
    "method": [
        r"(?i)^\s*(?:\d+\.?\s*)?(?:method|approach|methodology|proposed|our\s*approach|方法|方案|算法|模型|model|architecture|框架)\s*$",
    ],
    "experiment": [
        r"(?i)^\s*(?:\d+\.?\s*)?(?:experiment|evaluation|result|实验|评估|结果|性能|performance|ablation)\s*$",
    ],
    "conclusion": [
        r"(?i)^\s*(?:\d+\.?\s*)?(?:conclusion|discussion|future\s*work|总结|讨论|结论|未来工作|limitation|局限)\s*$",
    ],
}

# 通用章节标题正则（匹配编号 + 标题的行）
SECTION_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?([A-Z][a-zA-Z\s\-]+|[^\x00-\x7F]{2,})\s*$",
    re.MULTILINE,
)


class SectionSplitter:
    """
    基于正则表达式的论文全文章节切分器。

    将 PDF 解析后的纯文本按章节标题切分为结构化段落。
    """

    def _identify_section(self, line: str) -> Optional[str]:
        """识别单行文本属于哪个章节类型"""
        line = line.strip()
        if not line or len(line) > 100:
            return None
        for section_type, patterns in SECTION_PATTERNS.items():
            for pattern in patterns:
                if re.match(pattern, line):
                    return section_type
        return None

    def split(self, full_text: str) -> Dict[str, str]:
        """
        将论文全文切分为章节。

        Args:
            full_text: PDF 解析后的论文全文

        Returns:
            {"abstract": "...", "introduction": "...", "method": "...", ...}
            可能缺少某些章节
        """
        lines = full_text.split("\n")
        sections: Dict[str, List[str]] = {}
        current_section = "preamble"

        for line in lines:
            section_type = self._identify_section(line)
            if section_type:
                current_section = section_type
                if current_section not in sections:
                    sections[current_section] = []
                continue
            if current_section not in sections:
                sections[current_section] = []
            sections[current_section].append(line)

        # 合并为字符串
        result = {}
        for sec_type, content_lines in sections.items():
            text = "\n".join(content_lines).strip()
            if text and len(text) > 50:
                result[sec_type] = text

        # 确保有 abstract
        if "abstract" not in result:
            # 取开头前500字符作为摘要
            preamble = sections.get("preamble", [])
            preamble_text = "\n".join(preamble).strip()[:500]
            if preamble_text:
                result["abstract"] = preamble_text

        logger.info(
            "章节切分完成: 全文 %d 字符 → %d 个章节 [%s]",
            len(full_text), len(result), ", ".join(result.keys()),
        )
        return result

    def split_batch(self, papers_text: List[str]) -> List[Dict[str, str]]:
        """批量切分多篇论文"""
        return [self.split(text) for text in papers_text]
