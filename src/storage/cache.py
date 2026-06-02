"""
缓存层实现。

提供内存缓存 + 文件缓存两级缓存机制，减少重复 API 调用和计算。
"""

import hashlib
import json
import logging
import time
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

from src.config.settings import settings

logger = logging.getLogger(__name__)


class CacheLayer:
    """
    两级缓存层：内存（L1）+ 磁盘文件（L2）。

    使用方式:
        cache = CacheLayer("search_results")
        cache.set("key", value, ttl=3600)
        value = cache.get("key")
    """

    def __init__(self, namespace: str):
        self.namespace = namespace
        self._memory: Dict[str, Dict[str, Any]] = {}
        self._lock = RLock()
        self._cache_dir = settings.CACHE_DIR / namespace
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, key: str) -> Path:
        safe_key = hashlib.md5(key.encode()).hexdigest()[:16]
        return self._cache_dir / f"{safe_key}.json"

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值，L1 -> L2 -> miss"""
        if not settings.CACHE_ENABLED:
            return None

        with self._lock:
            # L1: 内存缓存
            if key in self._memory:
                entry = self._memory[key]
                if entry["expires_at"] > time.time():
                    logger.debug("L1 cache hit: %s:%s", self.namespace, key[:50])
                    return entry["value"]
                del self._memory[key]

            # L2: 文件缓存
            fp = self._file_path(key)
            if fp.exists():
                try:
                    entry = json.loads(fp.read_text(encoding="utf-8"))
                    if entry.get("expires_at", 0) > time.time():
                        # 回填 L1
                        self._memory[key] = entry
                        logger.debug("L2 cache hit: %s:%s", self.namespace, key[:50])
                        return entry["value"]
                    fp.unlink()  # 过期删除
                except (json.JSONDecodeError, KeyError):
                    fp.unlink(missing_ok=True)

        return None

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """设置缓存，同时写入 L1 和 L2。ttl=None 表示永久缓存。"""
        if not settings.CACHE_ENABLED:
            return

        # ttl=None 表示永久缓存，设一个极大的过期时间
        expires_at = time.time() + ttl if ttl is not None else float("inf")

        entry = {
            "value": value,
            "expires_at": expires_at,
            "created_at": time.time(),
        }

        with self._lock:
            # L1
            self._memory[key] = entry
            # L2
            fp = self._file_path(key)
            try:
                fp.write_text(json.dumps(entry, ensure_ascii=False, default=str), encoding="utf-8")
            except Exception as e:
                logger.warning("L2 cache write failed: %s", e)

        logger.debug("Cache set: %s:%s, ttl=%ds", self.namespace, key[:50], ttl)

    def clear(self) -> None:
        """清空命名空间下所有缓存"""
        with self._lock:
            self._memory.clear()
            for fp in self._cache_dir.glob("*.json"):
                fp.unlink()
        logger.info("Cache cleared: %s", self.namespace)


# 全局缓存实例（按命名空间）
_search_cache = CacheLayer("search")
_paper_cache = CacheLayer("papers")
_summary_cache = CacheLayer("summaries")
_embedding_cache = CacheLayer("embeddings")


def get_search_cache() -> CacheLayer:
    return _search_cache


def get_paper_cache() -> CacheLayer:
    return _paper_cache


def get_summary_cache() -> CacheLayer:
    return _summary_cache


def get_embedding_cache() -> CacheLayer:
    return _embedding_cache
