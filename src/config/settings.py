"""
全局配置管理，从环境变量和 .env 文件加载配置。
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# 加载 .env 文件
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

# 必须在任何 huggingface 相关 import 之前设置
os.environ.setdefault("HF_ENDPOINT", os.getenv("HF_ENDPOINT", "https://hf-mirror.com"))
# 模型下载目录 → 项目本地，避免撑爆 C 盘
_hf_home = os.getenv("HF_HOME", "./models/huggingface")
if not os.path.isabs(_hf_home):
    _hf_home = str(Path(__file__).parent.parent.parent / _hf_home)
os.environ["HF_HOME"] = _hf_home
os.environ.setdefault("HF_HUB_CACHE", _hf_home)
os.environ.setdefault("TRANSFORMERS_CACHE", _hf_home)
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", _hf_home)


class Settings(BaseSettings):
    """应用全局配置"""

    # === 项目路径 ===
    PROJECT_ROOT: Path = Path(__file__).parent.parent.parent
    SRC_DIR: Path = PROJECT_ROOT / "src"
    CONFIG_DIR: Path = PROJECT_ROOT / "config"
    PROMPTS_DIR: Path = CONFIG_DIR / "prompts"
    CACHE_DIR: Path = Path(os.getenv("CACHE_DIR", PROJECT_ROOT / "cache"))
    LOG_DIR: Path = Path(os.getenv("LOG_DIR", PROJECT_ROOT / "logs"))

    # === OpenAI / LLM (Pro) ===
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_BASE_URL: str = Field(default="https://api.openai.com/v1")
    LLM_MODEL: str = Field(default="gpt-4o")
    LLM_TEMPERATURE: float = Field(default=0.3)
    LLM_MAX_TOKENS: int = Field(default=4096)

    # === Flash 模型（快速任务） ===
    FLASH_API_KEY: str = Field(default="")
    FLASH_BASE_URL: str = Field(default="https://api.deepseek.com")
    FLASH_MODEL: str = Field(default="deepseek-v4-flash")

    # === HuggingFace ===
    HF_ENDPOINT: str = Field(default="https://hf-mirror.com")

    # === Embedding ===
    EMBEDDING_MODEL: str = Field(default="BAAI/bge-small-zh-v1.5")

    # === Reranker ===
    RERANKER_MODEL: str = Field(default="BAAI/bge-reranker-v2-m3")

    # === ChromaDB ===
    CHROMA_PERSIST_DIR: str = Field(default="./chroma_data")
    CHROMA_COLLECTION_NAME: str = Field(default="research_papers")

    # === 检索配置 ===
    SEARCH_MAX_ROUNDS: int = Field(default=3, ge=1, le=5)
    SEARCH_PAPERS_PER_ROUND: int = Field(default=20, ge=10, le=100)
    SEARCH_TEMPERATURE_INITIAL: float = Field(default=0.1, ge=0.0, le=1.0)
    SEARCH_TOP_P_INITIAL: float = Field(default=0.85, ge=0.0, le=1.0)

    # === arXiv 配置 ===
    ARXIV_API_URL: str = Field(default="https://export.arxiv.org")
    ARXIV_TIMEOUT: int = Field(default=60, ge=10, le=300)

    # === 检索源配置（逗号分隔的优先级列表） ===
    SEARCH_SOURCES: str = Field(default="arxiv,semantic_scholar")

    # === LLM 并发控制 ===
    LLM_MAX_CONCURRENT: int = Field(default=15, ge=1, le=50)

    # === 相关性阈值 ===
    RELEVANCE_THRESHOLD_HIGH: float = Field(default=0.9)
    RELEVANCE_THRESHOLD_MID: float = Field(default=0.8)
    RELEVANCE_THRESHOLD_LOW: float = Field(default=0.7)

    # === 缓存 ===
    CACHE_ENABLED: bool = Field(default=True)

    # === 日志 ===
    LOG_LEVEL: str = Field(default="INFO")

    class Config:
        env_file = str(env_path)
        env_file_encoding = "utf-8"
        extra = "ignore"  # 忽略 .env 中未映射的环境变量（如 HF_HOME）


# 全局单例
settings = Settings()

# 注入 HF_ENDPOINT 到系统环境变量（sentence-transformers 依赖此变量）
if settings.HF_ENDPOINT:
    os.environ["HF_ENDPOINT"] = settings.HF_ENDPOINT

# 确保必要目录存在
settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
