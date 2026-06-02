"""
学术数据源抽象基类与实现。

支持插件化扩展：实现 BaseSearchSource 即可接入新数据源。
"""

import logging
from abc import ABC, abstractmethod
from typing import List

from src.graph.state import PaperRecord

logger = logging.getLogger(__name__)


class BaseSearchSource(ABC):
    """学术数据源抽象基类"""

    @abstractmethod
    async def search(
        self,
        keywords: List[str],
        max_results: int = 50,
    ) -> List[PaperRecord]:
        """
        按关键词检索论文。

        Args:
            keywords: 检索关键词列表
            max_results: 最大返回结果数

        Returns:
            PaperRecord 列表
        """
        ...

    @abstractmethod
    def source_name(self) -> str:
        """返回数据源标识名称"""
        ...
