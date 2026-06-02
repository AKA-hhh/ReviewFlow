"""
向量数据库存储层封装。

基于 ChromaDB 实现论文嵌入向量的存储与语义检索。
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from src.config.settings import settings

logger = logging.getLogger(__name__)


class VectorStore:
    """ChromaDB 向量存储封装"""

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        collection_name: Optional[str] = None,
    ):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self.collection_name = collection_name or settings.CHROMA_COLLECTION_NAME

        self._client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "ChromaDB 初始化完成: persist_dir=%s, collection=%s, count=%d",
            self.persist_dir, self.collection_name, self._collection.count(),
        )

    def add_papers(
        self,
        papers: List[Dict[str, Any]],
        embeddings: List[List[float]],
    ) -> None:
        """
        批量添加论文向量。

        Args:
            papers: 论文元数据列表，每篇需包含 id, title, abstract, authors, year 等
            embeddings: 对应的嵌入向量列表
        """
        if not papers or not embeddings:
            return

        ids = []
        documents = []
        metadatas = []

        for paper in papers:
            paper_id = paper["id"]
            # 生成唯一 ID（避免重复插入）
            unique_id = hashlib.md5(paper_id.encode()).hexdigest()[:16]

            # 检查是否已存在
            existing = self._collection.get(ids=[unique_id])
            if existing and existing["ids"]:
                continue

            ids.append(unique_id)
            documents.append(
                f"{paper.get('title', '')} {paper.get('abstract', '')}"
            )
            metadatas.append({
                "paper_id": paper_id,
                "title": paper.get("title", ""),
                "authors": json.dumps(paper.get("authors", [])),
                "year": paper.get("year", 0),
                "journal": paper.get("journal", ""),
                "url": paper.get("url", ""),
                "source": paper.get("source", ""),
            })

        if ids:
            self._collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            logger.info("向 ChromaDB 添加 %d 篇论文", len(ids))

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        语义检索最相似的论文。

        Args:
            query_embedding: 查询文本的嵌入向量
            top_k: 返回结果数

        Returns:
            论文列表，包含 id, title, abstract, score 等
        """
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )

        papers = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] and results["distances"][0] else 0
                if distance is None:
                    distance = 0
                papers.append({
                    "id": metadata.get("paper_id", doc_id),
                    "title": metadata.get("title", ""),
                    "authors": json.loads(metadata.get("authors", "[]")),
                    "year": metadata.get("year", 0),
                    "journal": metadata.get("journal", ""),
                    "abstract": results["documents"][0][i] if results["documents"] else "",
                    "url": metadata.get("url", ""),
                    "source": metadata.get("source", ""),
                    "score": float(1.0 - distance),  # cosine距离转相似度
                })
        return papers

    def count(self) -> int:
        """返回当前集合中的文档数量"""
        return self._collection.count()

    def clear(self) -> None:
        """清空集合"""
        self._client.delete_collection(self.collection_name)
        self._collection = self._client.create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB 集合已清空")
