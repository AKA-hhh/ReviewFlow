"""
FastAPI 路由定义。

提供综述生成任务的创建、查询、获取和删除接口。
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.agents.supervisor import SupervisorAgent
from src.api.schemas import (
    ErrorResponse,
    ReviewGenerateRequest,
    ReviewResultResponse,
    ReviewStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/review", tags=["review"])

# 任务存储（生产环境应替换为 Redis/DB）
_tasks: Dict[str, dict] = {}

# 全局 Supervisor Agent 单例
_supervisor = SupervisorAgent()


async def _run_review_task(task_id: str, query: str, config: dict = None):
    """后台执行综述生成任务"""
    try:
        _tasks[task_id]["status"] = "running"

        result = await _supervisor.generate_review(query, config)

        _tasks[task_id].update({
            "status": "completed",
            "result": result,
            "completed_at": datetime.now().isoformat(),
        })
        logger.info("任务完成: %s", task_id)

    except Exception as e:
        logger.error("任务失败 [%s]: %s", task_id, e, exc_info=True)
        _tasks[task_id].update({
            "status": "failed",
            "errors": [str(e)],
        })


@router.post(
    "/generate",
    response_model=ReviewStatusResponse,
    summary="创建综述生成任务",
    description="提交研究主题，启动端到端文献综述自动生成流程",
)
async def create_review_task(req: ReviewGenerateRequest):
    """创建综述生成任务（异步后台执行）"""
    task_id = f"rev_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    _tasks[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "stage": "init",
        "progress": 0.0,
        "message": "任务已创建，等待执行...",
        "started_at": datetime.now().isoformat(),
        "query": req.query,
        "config": req.config,
    }

    # 启动后台任务
    asyncio.create_task(
        _run_review_task(task_id, req.query, req.config)
    )

    return ReviewStatusResponse(
        task_id=task_id,
        status="pending",
        stage="init",
        progress=0.0,
        message="任务已创建，正在启动...",
        started_at=_tasks[task_id]["started_at"],
    )


@router.get(
    "/{task_id}/status",
    response_model=ReviewStatusResponse,
    summary="查询任务状态",
    description="获取综述生成任务的实时进度",
)
async def get_task_status(task_id: str):
    """查询任务进度"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    return ReviewStatusResponse(
        task_id=task_id,
        status=task.get("status", "unknown"),
        stage=task.get("stage", ""),
        progress=task.get("progress", 0.0),
        message=task.get("message", ""),
        started_at=task.get("started_at"),
    )


@router.get(
    "/{task_id}/result",
    response_model=ReviewResultResponse,
    summary="获取综述结果",
    description="获取已完成任务的完整综述结果",
)
async def get_task_result(task_id: str):
    """获取生成的综述结果"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    status = task.get("status", "unknown")
    if status == "pending" or status == "running":
        raise HTTPException(
            status_code=202,
            detail=f"任务尚未完成 (当前状态: {status})",
        )
    if status == "failed":
        return ReviewResultResponse(
            task_id=task_id,
            status="failed",
            errors=task.get("errors", []),
        )

    result = task.get("result", {})
    return ReviewResultResponse(
        task_id=task_id,
        status="completed",
        final_review=result.get("final_review", ""),
        draft=result.get("draft", ""),
        structured_papers=result.get("structured_papers", []),
        topic_clusters=result.get("topic_clusters", []),
        conflicts=result.get("conflicts", []),
        chapter_plan=result.get("chapter_plan", []),
        statistics=result.get("statistics", {}),
        logs=result.get("logs", []),
    )


@router.get(
    "/{task_id}/intermediate",
    response_model=ReviewResultResponse,
    summary="获取中间结果",
    description="获取任务执行的中间产物（如检索文献列表、结构化数据等）",
)
async def get_intermediate_results(task_id: str):
    """获取中间结果"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    result = task.get("result", {})
    return ReviewResultResponse(
        task_id=task_id,
        status=task.get("status", "unknown"),
        structured_papers=result.get("structured_papers", []),
        topic_clusters=result.get("topic_clusters", []),
        conflicts=result.get("conflicts", []),
        chapter_plan=result.get("chapter_plan", []),
    )


@router.delete(
    "/{task_id}",
    summary="取消/删除任务",
)
async def delete_task(task_id: str):
    """取消或删除任务"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    if task.get("status") in ("pending", "running"):
        task["status"] = "cancelled"
        return {"message": "任务已取消", "task_id": task_id}

    del _tasks[task_id]
    return {"message": "任务已删除", "task_id": task_id}
