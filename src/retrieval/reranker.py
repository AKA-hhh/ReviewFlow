"""
BGE Reranker 重排序模块。

使用 Cross-encoder 模型对 RRF 融合结果进行精细重排序。
"""

import logging
import os
from typing import Any, Dict, List, Optional

# 必须在 sentence_transformers 导入前设置（国内镜像 + 本地模型目录）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
if "HF_HOME" not in os.environ:
    _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault("HF_HOME", os.path.join(_project_root, "models", "huggingface"))

from sentence_transformers import CrossEncoder

# 二次确保：直接改 huggingface_hub 常量
try:
    import huggingface_hub.constants as hf_constants
    hf_constants.ENDPOINT = "https://hf-mirror.com"
except Exception:
    pass

from src.config.settings import settings

logger = logging.getLogger(__name__)


class Reranker:
    """
    Cross-encoder 重排序器。

    对每篇论文的 (query, title+abstract) 对进行精细相关性打分。
    相比 Bi-encoder（向量检索），Cross-encoder 精度更高但速度较慢，
    因此仅用于最终的精筛阶段。
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.RERANKER_MODEL
        self._model: Optional[CrossEncoder] = None

    @property
    def model(self) -> CrossEncoder:
        """懒加载重排序模型"""
        if self._model is None:
            logger.info("加载 Reranker 模型: %s", self.model_name)
            self._model = CrossEncoder(
                self.model_name,
                max_length=512,
                local_files_only=True,  # 仅使用本地缓存，避免网络波动导致加载失败
            )
        return self._model

    def rerank(
        self,
        query: str,
        papers: List[Dict[str, Any]],
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        对论文列表进行重排序。

        Args:
            query: 用户查询
            papers: 待重排序的论文列表
            top_k: 返回的 Top-K 结果数

        Returns:
            重排序后的 Top-K 论文，含 rerank_score
        """
        if not papers:
            return []

        # 构建 (query, document) 对
        pairs = []
        for paper in papers:
            doc = f"{paper.get('title', '')} [SEP] {paper.get('abstract', '')}"
            pairs.append([query, doc])

        # Cross-encoder 打分
        try:
            scores = self.model.predict(
                pairs,
                show_progress_bar=False,
            )
        except Exception as e:
            logger.warning("Reranker 模型预测失败（可能是网络问题）: %s，跳过重排序", e)
            return papers[:top_k]

        # 附分并排序（处理各种返回值类型）
        for i, paper in enumerate(papers):
            try:
                if hasattr(scores, '__iter__') and not isinstance(scores, (str, bytes)):
                    val = float(scores[i]) if i < len(scores) else 0.0
                else:
                    val = float(scores) if not hasattr(scores, '__iter__') else float(scores[i])
                paper["rerank_score"] = val
            except (TypeError, ValueError, IndexError):
                paper["rerank_score"] = 0.0

        sorted_papers = sorted(
            papers,
            key=lambda x: x.get("rerank_score", 0),
            reverse=True,
        )

        # 基于 title 去重
        seen_titles = set()
        deduped = []
        for p in sorted_papers:
            title_key = p.get("title", "").lower().strip()[:100]
            if title_key and title_key not in seen_titles:
                seen_titles.add(title_key)
                deduped.append(p)

        result = deduped[:top_k]
        logger.info(
            "Reranker 重排序: %d → %d (去重后 Top%d)",
            len(papers), len(result), top_k,
        )
        return result
