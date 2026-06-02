"""
API 请求/响应 Pydantic Schema 定义。
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class ReviewGenerateRequest(BaseModel):
    """创建综述生成任务请求"""
    query: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="研究主题或问题，自然语言描述",
        examples=["扩散模型在医学图像分割中的最新进展"],
    )
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="可选配置覆盖",
        examples=[{
            "max_rounds": 3,
            "papers_per_round": 20,
            "temperature_initial": 0.3,
        }],
    )

    @validator("query")
    def query_must_be_meaningful(cls, v: str) -> str:
        v = v.strip()
        if len(v.split()) < 2:
            raise ValueError("查询内容过短，请提供更详细的研究主题描述")
        return v


class ReviewStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    status: str                     # "pending" | "running" | "completed" | "failed"
    stage: str                      # 当前阶段标识
    progress: float                 # 0.0 - 1.0
    message: str
    started_at: Optional[str] = None
    estimated_completion: Optional[str] = None


class ReviewResultResponse(BaseModel):
    """综述结果响应"""
    task_id: str
    status: str
    final_review: Optional[str] = None
    draft: Optional[str] = None
    structured_papers: Optional[List[Dict[str, Any]]] = None
    topic_clusters: Optional[List[Dict[str, Any]]] = None
    conflicts: Optional[List[Dict[str, Any]]] = None
    chapter_plan: Optional[List[Dict[str, Any]]] = None
    statistics: Optional[Dict[str, Any]] = None
    logs: Optional[List[str]] = None
    errors: Optional[List[str]] = None


class ErrorResponse(BaseModel):
    """错误响应"""
    error: str
    detail: Optional[str] = None
    task_id: Optional[str] = None
