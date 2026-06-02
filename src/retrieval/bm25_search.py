"""
BM25 关键词检索器。

基于 rank-bm25 实现稀疏检索，按标题+摘要构建索引。
"""

import logging
from typing import Any, Dict, List, Optional

import jieba
from rank_bm25 import BM25Okapi

from src.graph.state import PaperRecord

logger = logging.getLogger(__name__)


class BM25Search:
    """
    BM25 关键词检索器。

    对论文的标题+摘要建立 BM25 索引，检索时按查询匹配得分排序。
    """

    def __init__(self):
        self._papers: List[PaperRecord] = []
        self._index: Optional[BM25Okapi] = None
        self._id_to_idx: Dict[str, int] = {}

    def _tokenize(self, text: str) -> List[str]:
        """分词：中英文混合"""
        tokens = []
        # JieBa 中文分词
        tokens.extend(jieba.lcut(text.lower()))
        # 按空白进一步切分英文
        final_tokens = []
        for t in tokens:
            t = t.strip()
            if len(t) >= 2:
                final_tokens.append(t)
        return final_tokens

    def index(self, papers: List[PaperRecord]) -> None:
        """
        对论文列表建立 BM25 索引。

        Args:
            papers: 论文列表
        """
        self._papers = papers
        self._id_to_idx = {}

        if not papers:
            self._index = None
            return

        corpus = []
        for i, paper in enumerate(papers):
            text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
            corpus.append(self._tokenize(text))
            self._id_to_idx[paper.get("id", str(i))] = i

        self._index = BM25Okapi(corpus)
        logger.info("BM25 索引构建完成: %d 篇论文", len(papers))

    def search(
        self,
        query: str,
        top_k: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        BM25 检索。

        Args:
            query: 查询文本
            top_k: 返回结果数

        Returns:
            论文列表，每篇含 id 和 bm25_score
        """
        if self._index is None or not self._papers:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = self._index.get_scores(query_tokens)

        # 排序取 top_k
        idx_scores = list(enumerate(scores))
        idx_scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in idx_scores[:top_k]:
            if score <= 0:
                continue
            paper = self._papers[idx].copy()
            paper["bm25_score"] = float(score)
            results.append(paper)

        logger.info("BM25 检索: '%s' → Top%d 结果", query[:50], len(results))
        return results

    def add_papers(self, papers: List[PaperRecord]) -> None:
        """增量添加论文并重建索引"""
        all_papers = self._papers + papers
        # 基于 id 去重
        seen = set()
        deduped = []
        for p in all_papers:
            pid = p.get("id", "")
            if pid not in seen:
                seen.add(pid)
                deduped.append(p)
        self.index(deduped)
