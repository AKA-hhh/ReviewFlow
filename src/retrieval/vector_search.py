"""
向量语义检索器。

使用 sentence-transformers 生成嵌入向量，通过 ChromaDB 进行语义相似度检索。
"""

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional

# 必须在 sentence_transformers 导入前设置（国内镜像 + 本地模型目录）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
if "HF_HOME" not in os.environ:
    _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault("HF_HOME", os.path.join(_project_root, "models", "huggingface"))

from sentence_transformers import SentenceTransformer

# 二次确保：直接改 huggingface_hub 常量
try:
    import huggingface_hub.constants as hf_constants
    hf_constants.ENDPOINT = "https://hf-mirror.com"
except Exception:
    pass

from src.config.settings import settings
from src.storage.vector_store import VectorStore
from src.storage.cache import get_embedding_cache

logger = logging.getLogger(__name__)


class VectorSearch:
    """
    向量语义检索器。

    使用 sentence-transformers 模型将文本转换为向量，
    通过 ChromaDB 进行语义相似度检索。
    """

    def __init__(
        self,
        vector_store: VectorStore,
        model_name: Optional[str] = None,
    ):
        self.vector_store = vector_store
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self._model: Optional[SentenceTransformer] = None
        self._embed_cache = get_embedding_cache()

    @property
    def model(self) -> SentenceTransformer:
        """懒加载嵌入模型"""
        if self._model is None:
            logger.info("加载嵌入模型: %s", self.model_name)
            self._model = SentenceTransformer(self.model_name, local_files_only=True)
        return self._model

    def _get_text_hash(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()[:16]

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """
        生成文本嵌入向量（带缓存）。

        Args:
            texts: 文本列表

        Returns:
            嵌入向量列表
        """
        embeddings = []
        texts_to_embed = []
        cache_indices = []

        # 检查缓存
        for i, text in enumerate(texts):
            text_hash = self._get_text_hash(text)
            cached = self._embed_cache.get(text_hash)
            if cached is not None:
                embeddings.append(cached)
            else:
                embeddings.append(None)
                texts_to_embed.append(text)
                cache_indices.append(i)

        # 批量编码未缓存的文本
        if texts_to_embed:
            vectors = self.model.encode(
                texts_to_embed,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            for j, idx in enumerate(cache_indices):
                vec = vectors[j].tolist()
                embeddings[idx] = vec
                # 写入缓存
                text_hash = self._get_text_hash(texts_to_embed[j])
                self._embed_cache.set(text_hash, vec, ttl=None)  # 永久缓存

        return embeddings

    async def search(
        self,
        query: str,
        top_k: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        语义检索。

        Args:
            query: 查询文本
            top_k: 返回结果数

        Returns:
            论文列表，含 similarity_score
        """
        # 查询嵌入
        query_embeddings = await self.embed([query])
        query_embedding = query_embeddings[0]

        # ChromaDB 检索
        papers = self.vector_store.search(query_embedding, top_k=top_k)

        logger.info("向量检索: '%s' → Top%d 结果", query[:50], len(papers))
        return papers

    def index_papers(
        self,
        papers: List[Dict[str, Any]],
        texts: Optional[List[str]] = None,
    ) -> None:
        """
        将论文索引到向量数据库。

        Args:
            papers: 论文元数据列表
            texts: 对应的文本（默认拼接 title + abstract）
        """
        if texts is None:
            texts = [
                f"{p.get('title', '')} {p.get('abstract', '')}"
                for p in papers
            ]

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        self.vector_store.add_papers(
            papers=papers,
            embeddings=[e.tolist() for e in embeddings],
        )
        logger.info("已索引 %d 篇论文到向量数据库", len(papers))
