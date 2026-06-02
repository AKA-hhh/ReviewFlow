"""
学术数据源注册表。

实现 BaseSearchSource 即可插入新数据源。
各数据源按 source_name() 标识，在检索时按优先级依次查询。
"""

from src.retrieval.sources.base import BaseSearchSource
from src.retrieval.sources.arxiv import ArxivSource
from src.retrieval.sources.semantic_scholar import SemanticScholarSource
from src.retrieval.sources.pubmed import PubMedSource
from src.retrieval.sources.dblp import DBLPSource

# 所有可用数据源（按 source_name 索引）
SOURCE_REGISTRY: dict = {
    "arxiv": ArxivSource,
    "semantic_scholar": SemanticScholarSource,
    "pubmed": PubMedSource,
    "dblp": DBLPSource,
}

# 各数据源描述（用于 UI 展示）
SOURCE_DESCRIPTIONS: dict = {
    "arxiv": "arXiv — 物理/CS/数学预印本，质量高范围广",
    "semantic_scholar": "Semantic Scholar — AI驱动学术搜索，索引全面",
    "pubmed": "PubMed — 生物医学权威数据库，生命科学首选",
    "dblp": "DBLP — 计算机科学文献库，CS领域最全",
}

# 默认优先级（无配置时的回退）
DEFAULT_SOURCES = ["arxiv", "semantic_scholar"]
