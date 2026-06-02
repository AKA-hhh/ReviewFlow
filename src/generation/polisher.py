"""
综述润色器。

对生成的综述进行语言润色、格式标准化和摘要生成。
"""

import logging
import re
from typing import Dict, Any

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class ReviewPolisher:
    """综述润色器"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    async def polish(
        self,
        draft: str,
        citation_check_result: Dict[str, Any] = None,
    ) -> str:
        """
        对综述草稿进行润色。

        包括：
        - 语言流畅度和学术规范性
        - 可疑引用标记处理
        - 格式统一（Markdown 标题层级、引用格式）
        - 重复内容去重

        Args:
            draft: 综述草稿
            citation_check_result: 引用验证结果（可选）

        Returns:
            润色后的最终综述
        """
        suspicious_info = ""
        if citation_check_result and citation_check_result.get("suspicious_count", 0) > 0:
            suspicious_info = f"""
## 引用验证警告
以下引用未能找到原文支撑，请在润色时标记为 [待核实] 或移除：
{chr(10).join(f"- {s['citation']}" for s in citation_check_result.get("suspicious", []))}
"""

        polish_prompt = f"""你是一位专业的学术编辑。请对以下综述草稿进行润色。

## 润色要求
1. 修正语言流畅度问题（语法、拼写、句式）
2. 统一 Markdown 格式规范
3. 确保引用格式一致：使用上标编号 [1]、[2]、[3] 格式
4. 文末必须保留完整的 References 章节，编号与文中引用对应
5. 检查段落逻辑，合并重复或冗余内容
6. 保持学术中立的语气
7. 对标记为 [待核实] 的引用保留标记，不删除

{suspicious_info}

## 综述草稿
{draft}

## 输出
请输出润色后的完整综述（Markdown 格式），保持原有章节结构。
"""

        try:
            response = await self.llm.ainvoke(polish_prompt)
            polished = response.content if hasattr(response, "content") else str(response)

            logger.info(
                "综述润色完成: %d → %d 字符",
                len(draft), len(polished),
            )
            return polished

        except Exception as e:
            logger.error("综述润色失败: %s", e)
            return draft
