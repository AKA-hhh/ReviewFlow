"""
LangGraph 全局状态定义。

所有 Agent 通过此 State 进行数据交换，不直接耦合。
每个 Agent 从 State 中读取所需字段，处理后写回 State。
"""

from typing import Any, Dict, List, Optional, TypedDict


class PaperRecord(TypedDict, total=False):
    """原始文献记录"""
    id: str
    title: str
    authors: List[str]
    journal: str
    year: int
    abstract: str
    url: str
    source: str          # "arxiv" | "google_scholar"
    pdf_url: Optional[str]


class SearchConfig(TypedDict, total=False):
    """检索参数配置"""
    max_rounds: int
    papers_per_round: int
    final_papers: int
    temperature_initial: float
    top_p_initial: float
    search_sources: str  # 逗号分隔的检索源列表


class StructuredPaper(TypedDict, total=False):
    """结构化提取后的论文数据"""
    paper_id: str
    title: str
    authors: List[str]
    journal: str
    year: int
    url: str
    source: str
    relevance_score: float
    relevance_level: str        # "high" | "mid" | "low"
    sections: Dict[str, str]    # {"abstract": ..., "method": ..., ...}
    key_findings: List[str]
    key_citations: List[Dict[str, Any]]


class Conflict(TypedDict, total=False):
    """观点冲突"""
    type: str                   # "conclusion" | "methodology" | "open_question"
    description: str
    involved_papers: List[str]
    positions: List[Dict[str, str]]
    resolution_status: str


class TopicCluster(TypedDict, total=False):
    """主题聚类"""
    cluster_name: str
    description: str
    paper_ids: List[str]
    key_themes: List[str]


class ReviewChapter(TypedDict, total=False):
    """综述章节"""
    id: str
    title: str
    description: str
    depends_on: List[str]
    key_citations: List[str]
    content: str                # 生成后填充


class AgentState(TypedDict, total=False):
    """
    LangGraph 全局 Agent 状态。

    所有 Agent 共享此状态，通过 LangGraph 的 StateGraph 进行读写。
    """

    # === 用户输入 ===
    user_query: str
    config: SearchConfig

    # === 检索状态 ===
    keywords: List[Dict[str, Any]]          # [{"keyword": "...", "score": 9.5}]
    keywords_en: List[str]                   # 英文关键词
    keywords_zh: List[str]                   # 中文关键词
    round_num: int                           # 当前检索轮数
    raw_papers: List[PaperRecord]            # 本轮原始检索结果
    merged_papers: List[PaperRecord]         # 多轮去重合并后的全部文献

    # === 筛选状态 ===
    ranked_papers: List[PaperRecord]         # RRF+BGE 重排序后
    relevance_scores: Dict[str, float]       # {paper_id: score}

    # === 摘要状态 ===
    structured_papers: List[StructuredPaper]

    # === 分析状态 ===
    timeline: str                            # 时间线分析结果（自然语言）
    timeline_data: Dict[str, Any]            # 时间线分析结果（结构化）
    topic_clusters: List[TopicCluster]
    conflicts: List[Conflict]
    open_questions: List[str]

    # === 生成状态 ===
    chapter_plan: List[ReviewChapter]
    draft: str                               # 综述 Markdown 草稿
    final_review: str                        # 润色后最终综述

    # === 控制状态 ===
    need_more_papers: bool                   # 是否需要补充检索
    current_stage: str                       # 当前阶段标识
    error_message: str                       # 错误消息（非空时中止生成）
    errors: List[str]                        # 错误记录
    logs: List[str]                          # 流程日志

    # === 元数据 ===
    task_id: str
    started_at: str
