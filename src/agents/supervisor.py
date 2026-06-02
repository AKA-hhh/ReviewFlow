"""
Supervisor Agent — 主编排 Agent。

作为系统的顶层控制器，负责协调各个 Agent 的执行顺序和数据流转。
实际上，LangGraph StateGraph 已经完成了编排工作，
此模块提供更高层的封装和对外接口。
"""

import logging
from typing import Any, Callable, Coroutine, Dict, Optional

from src.graph.workflow import ReviewWorkflow

logger = logging.getLogger(__name__)

# 每个主阶段在整个流程中的权重（用于计算整体进度百分比）
STAGE_WEIGHTS = {
    "extracting_keywords": 0.06,
    "searching": 0.10,
    "ranking": 0.14,
    "adjust_search_params": 0.02,  # 极短——仅参数调整
    "extracting": 0.30,
    "analyzing": 0.15,
    "generating": 0.25,
}

# 每个 stage 的起始百分比
STAGE_STARTS = {
    "init": 0.0,
    "extracting_keywords": 0.0,
    "searching": 0.06,
    "ranking": 0.16,
    "adjust_search_params": 0.28,
    "extracting": 0.30,
    "analyzing": 0.60,
    "generating": 0.75,
    "done": 1.0,
}


class SupervisorAgent:
    """
    主编排 Agent。

    封装 ReviewWorkflow，提供简化的调用接口和进度回调。
    """

    def __init__(self):
        self._workflow = ReviewWorkflow()

    async def generate_review(
        self,
        query: str,
        config: Optional[Dict[str, Any]] = None,
        on_progress: Optional[Callable[[str, float, str], Coroutine]] = None,
    ) -> Dict[str, Any]:
        """
        生成文献综述。

        Args:
            query: 研究主题
            config: 可选参数覆盖，如 {"max_rounds": 2, "papers_per_round": 15}
            on_progress: 进度回调 async def(stage: str, progress: float, message: str)
                - stage: 当前子阶段标识
                - progress: 整体进度 0.0~1.0
                - message: 用户可读消息

        Returns:
            {
                "task_id": str,
                "final_review": str,
                "structured_papers": [...],
                "topic_clusters": [...],
                "conflicts": [...],
                "logs": [...],
                "statistics": {...}
            }
        """
        # 将 workflow 的细粒度回调桥接到 on_progress
        if on_progress:
            # 进度防回退：多轮检索时 stage 会重复进入，记录已报告的最大值
            _max_reported: Dict[str, float] = {}
            _last_overall: float = 0.0

            async def progress_bridge(stage: str, sub_stage: str,
                                      fraction: float, message: str):
                """将 workflow 内部回调转为整体进度百分比，防回退"""
                nonlocal _last_overall
                stage_start = STAGE_STARTS.get(stage, 0.5)
                stage_weight = STAGE_WEIGHTS.get(stage, 0.10)

                # 多轮场景：同一 stage 再次进入时，从上次离开的位置继续
                stage_key = f"{stage}_round"
                prev_max = _max_reported.get(stage_key, stage_start)
                overall = stage_start + fraction * stage_weight
                # 如果新计算值低于此前的同一阶段最大值，用历史最高值
                if overall < prev_max and fraction < 0.5:
                    overall = prev_max
                else:
                    _max_reported[stage_key] = max(prev_max, overall)

                # 全局防回退
                if overall < _last_overall:
                    overall = _last_overall
                else:
                    _last_overall = overall

                overall = min(overall, 0.99)  # 留 1% 给最终完成
                # 传递主阶段名（stage），方便前端做管道可视化
                await on_progress(stage, overall, message)

            self._workflow.set_progress_callback(progress_bridge)
        else:
            self._workflow.set_progress_callback(None)

        # 通知开始
        if on_progress:
            await on_progress("init", 0.0, "正在初始化...")

        result = await self._workflow.run(query, config)

        # 通知完成
        if on_progress:
            await on_progress("done", 1.0, "✅ 综述生成完毕！")

        # 构建统计信息
        structured = result.get("structured_papers", [])
        cfg = result.get("config") or {}
        max_final = cfg.get("final_papers", len(structured)) if hasattr(cfg, 'get') else len(structured)
        statistics = {
            "total_papers_retrieved": len(result.get("merged_papers", [])),
            "final_papers_used": min(len(structured), max_final),
            "retrieval_rounds": result.get("round_num", 0) + 1,
            "topic_clusters": len(result.get("topic_clusters", [])),
            "conflicts_found": len(result.get("conflicts", [])),
            "review_length_chars": len(result.get("final_review", "")),
            "stages_completed": len(result.get("logs", [])),
        }

        return {
            "task_id": result.get("task_id", ""),
            "final_review": result.get("final_review", ""),
            "draft": result.get("draft", ""),
            "structured_papers": result.get("structured_papers", []),
            "topic_clusters": result.get("topic_clusters", []),
            "conflicts": result.get("conflicts", []),
            "chapter_plan": result.get("chapter_plan", []),
            "logs": result.get("logs", []),
            "statistics": statistics,
        }
