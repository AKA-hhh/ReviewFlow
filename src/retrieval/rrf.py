"""
RRF (Reciprocal Rank Fusion) 融合排序。

将 BM25 和向量检索两路结果进行加权融合排序。
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class RRFFusion:
    """
    RRF 融合排序器。

    算法: score(d) = Σ 1 / (k + rank_i(d))

    其中 k 为平滑参数（默认60），rank_i(d) 为文档 d 在第 i 路检索结果中的排名。
    """

    def __init__(self, k: int = 60):
        """
        Args:
            k: RRF 平滑参数，防止单路排名过高。常用值 60。
        """
        self.k = k

    def fuse(
        self,
        *ranked_lists: List[Dict[str, Any]],
        score_keys: List[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        融合多路检索结果。

        Args:
            *ranked_lists: 多路排序后的论文列表
            score_keys: 每路结果中得分字段名（用于内部排名）

        Returns:
            融合排序后的论文列表
        """
        if score_keys is None:
            score_keys = ["bm25_score"] * len(ranked_lists)

        # 收集所有论文，计算 RRF 得分
        rrf_scores: Dict[str, float] = {}
        paper_map: Dict[str, Dict[str, Any]] = {}

        for list_idx, ranked_list in enumerate(ranked_lists):
            score_key = (
                score_keys[list_idx] if list_idx < len(score_keys) else "score"
            )

            for rank, paper in enumerate(ranked_list, start=1):
                paper_id = paper.get("id", f"unknown_{rank}")
                rrf_score = 1.0 / (self.k + rank)

                if paper_id in rrf_scores:
                    rrf_scores[paper_id] += rrf_score
                    # 合并信息
                    existing = paper_map[paper_id]
                    for k, v in paper.items():
                        if v and not existing.get(k):
                            existing[k] = v
                else:
                    rrf_scores[paper_id] = rrf_score
                    paper_map[paper_id] = dict(paper)

        # 按 RRF 得分降序排列
        sorted_items = sorted(
            rrf_scores.items(), key=lambda x: x[1], reverse=True
        )

        results = []
        for paper_id, rrf_score in sorted_items:
            paper = paper_map[paper_id]
            paper["rrf_score"] = round(rrf_score, 6)
            paper["id"] = paper_id
            results.append(paper)

        logger.info(
            "RRF 融合: %d 路输入 → %d 篇（去重后）",
            len(ranked_lists), len(results),
        )
        return results
