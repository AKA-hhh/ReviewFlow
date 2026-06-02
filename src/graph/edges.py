"""
LangGraph 条件边定义。

定义状态机中的条件分支逻辑，包括：
- 是否需要补充检索
- 检索质量检查
- 文献数量是否足够
"""

import logging
from typing import Literal

from src.config.settings import settings
from src.graph.state import AgentState

logger = logging.getLogger(__name__)


def should_continue_retrieval(state: AgentState) -> Literal["adjust_and_retry", "summarize"]:
    """
    判断检索后是否需要补充更多文献。

    决策逻辑：
    1. 已达最大轮数 → 强制进入摘要阶段
    2. 高相关文献数量不足 → 触发补充检索
    3. 文献总量不足 → 触发补充检索
    4. 否则 → 进入摘要阶段

    注意：relevance_score 由 RelevanceScorer 设置（如未启用则检查 rerank_score 降级）。
    """
    round_num = state.get("round_num", 0)
    max_rounds = state.get("config", {}).get("max_rounds", settings.SEARCH_MAX_ROUNDS)
    ranked_papers = state.get("ranked_papers", [])

    # 已达最大轮数 — 但若论文太少（<5篇），再给一次紧急补充机会
    if round_num + 1 >= max_rounds:
        if len(ranked_papers) < 5 and max_rounds < 3:
            logger.info("已达最大轮数但文献严重不足 (%d篇)，触发紧急补充检索", len(ranked_papers))
            # 临时扩一轮上限
            state["config"]["max_rounds"] = max_rounds + 1
            return "adjust_and_retry"
        logger.info("已达最大检索轮数 (%d/%d)，进入摘要阶段", round_num + 1, max_rounds)
        return "summarize"

    # 统计高相关文献：优先用 relevance_score，降级用 rerank_score
    high_relevance = sum(
        1 for p in ranked_papers
        if p.get("relevance_score", p.get("rerank_score", 0)) >= settings.RELEVANCE_THRESHOLD_HIGH
    )

    # 第一轮：文献数量本身就是信号，放宽阈值
    if round_num == 0:
        min_papers = 15  # 第一轮 15 篇即可通过
        min_high = 5
    else:
        min_papers = 30
        min_high = 15

    if len(ranked_papers) < min_papers:
        reason = (
            f"文献数量不足 ({len(ranked_papers)}/{min_papers} 篇, "
            f"高相关 {high_relevance} 篇)，触发第{round_num+2}轮补充检索"
        )
        logger.info(reason)
        state["retrieval_reason"] = reason
        return "adjust_and_retry"

    if high_relevance < min_high:
        reason = (
            f"高相关文献不足 ({high_relevance}/{min_high} 篇)，"
            f"触发第{round_num+2}轮补充检索"
        )
        logger.info(reason)
        state["retrieval_reason"] = reason
        return "adjust_and_retry"

    logger.info(
        "检索质量达标 (第%d轮, %d篇, 高相关%d篇)，进入摘要阶段",
        round_num, len(ranked_papers), high_relevance,
    )
    return "summarize"
