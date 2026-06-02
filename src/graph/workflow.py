"""
LangGraph 主工作流编排。

定义从用户提问到综述生成的完整状态机流程。
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from src.config.settings import settings
from src.graph.edges import should_continue_retrieval
from src.graph.state import AgentState, PaperRecord, SearchConfig
from src.retrieval.keyword_extractor import KeywordExtractor
from src.retrieval.sources import SOURCE_REGISTRY, DEFAULT_SOURCES
from src.retrieval.sources.arxiv import ArxivSource
from src.retrieval.bm25_search import BM25Search
from src.retrieval.vector_search import VectorSearch
from src.retrieval.rrf import RRFFusion
from src.retrieval.reranker import Reranker
from src.extraction.section_splitter import SectionSplitter
from src.extraction.structured_extractor import StructuredExtractor
from src.extraction.relevance_scorer import RelevanceScorer
from src.analysis.timeline import TimelineAnalyzer
from src.analysis.clustering import TopicClusterer
from src.analysis.conflict import ConflictDetector
from src.generation.planner import ReviewPlanner
from src.generation.writer import ReviewWriter
from src.generation.citation_checker import CitationChecker
from src.generation.polisher import ReviewPolisher
from src.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


class ReviewWorkflow:
    """
    科研文献智能综述系统主工作流。

    基于 LangGraph StateGraph 构建端到端的多 Agent 协作流程：
    keywords → search → filter → summarize → analyze → generate → polish
    """

    def __init__(self, llm: Optional[BaseChatModel] = None):
        # LLM
        self.llm = llm or ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            openai_api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )

        # 并发控制：避免打爆 API 限流（DeepSeek 等 API 通常限 20-30 并发）
        _max_concurrent = getattr(settings, "LLM_MAX_CONCURRENT", 15)
        self._semaphore = asyncio.Semaphore(_max_concurrent)

        # 进度回调：(node_name, sub_stage, fraction, message) -> None
        self._progress_callback = None

        # 耗时统计
        self._overall_start: float = 0.0
        self._stage_start: Dict[str, float] = {}
        self._stage_elapsed: Dict[str, float] = {}

        # 检索模块
        self.keyword_extractor = KeywordExtractor(self.llm)
        self._search_sources: Dict[str, Any] = {}  # 懒加载
        self.bm25 = BM25Search()
        self.vector_store = VectorStore()
        self.vector_search = VectorSearch(self.vector_store)
        self.rrf = RRFFusion()
        self.reranker = Reranker()

        # 抽取模块
        self.section_splitter = SectionSplitter()
        self.structured_extractor = StructuredExtractor(self.llm)
        self.relevance_scorer = RelevanceScorer(self.llm)

        # 分析模块
        self.timeline_analyzer = TimelineAnalyzer(self.llm)
        self.topic_clusterer = TopicClusterer(self.llm)
        self.conflict_detector = ConflictDetector(self.llm)

        # 生成模块
        self.planner = ReviewPlanner(self.llm)
        self.writer = ReviewWriter(self.llm)
        self.citation_checker = CitationChecker(self.llm)
        self.polisher = ReviewPolisher(self.llm)

        # 构建图
        self._graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态机"""
        workflow = StateGraph(AgentState)

        # 添加节点
        workflow.add_node("extract_keywords", self._node_extract_keywords)
        workflow.add_node("search_papers", self._node_search_papers)
        workflow.add_node("rank_and_filter", self._node_rank_and_filter)
        workflow.add_node("adjust_search_params", self._node_adjust_search_params)
        workflow.add_node("extract_structured", self._node_extract_structured)
        workflow.add_node("analyze", self._node_analyze)
        workflow.add_node("generate_review", self._node_generate_review)

        # 添加边
        workflow.add_edge("extract_keywords", "search_papers")
        workflow.add_edge("search_papers", "rank_and_filter")

        # 条件边：检索质量检查
        workflow.add_conditional_edges(
            "rank_and_filter",
            should_continue_retrieval,
            {
                "adjust_and_retry": "adjust_search_params",
                "summarize": "extract_structured",
            },
        )
        workflow.add_edge("adjust_search_params", "extract_keywords")

        workflow.add_edge("extract_structured", "analyze")
        workflow.add_edge("analyze", "generate_review")
        workflow.add_edge("generate_review", END)

        # 设置入口
        workflow.set_entry_point("extract_keywords")

        return workflow.compile()

    @property
    def graph(self):
        return self._graph

    def _get_sources(self, config: dict) -> list:
        """根据配置获取已启用的检索源实例列表（懒加载，按优先级排序）"""
        source_names_str = config.get("search_sources", settings.SEARCH_SOURCES)
        if isinstance(source_names_str, str):
            source_names = [s.strip() for s in source_names_str.split(",") if s.strip()]
        else:
            source_names = source_names_str or DEFAULT_SOURCES

        # 加载自定义检索源配置
        custom_sources = config.get("custom_sources", [])

        sources = []
        for name in source_names:
            if name not in self._search_sources:
                cls = SOURCE_REGISTRY.get(name)
                if cls:
                    self._search_sources[name] = cls()
                else:
                    # 尝试从自定义源中查找
                    custom = next((s for s in custom_sources if s.get("name") == name), None)
                    if custom:
                        from src.retrieval.sources.custom import CustomApiSource
                        self._search_sources[name] = CustomApiSource(
                            name=custom["name"],
                            base_url=custom["base_url"],
                            api_key=custom.get("api_key", ""),
                            search_path=custom.get("search_path", "/search"),
                            query_param=custom.get("query_param", "q"),
                            limit_param=custom.get("limit_param", "limit"),
                            results_path=custom.get("results_path", "data"),
                        )
                        logger.info("已加载自定义检索源: %s (%s)", name, custom["base_url"])
                    else:
                        logger.warning("未知检索源: %s，跳过", name)
                        continue
            sources.append(self._search_sources[name])
        return sources

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        """格式化秒数为可读字符串"""
        if seconds < 1:
            return f"{seconds*1000:.0f}ms"
        elif seconds < 60:
            return f"{seconds:.1f}s"
        else:
            m, s = divmod(int(seconds), 60)
            return f"{m}m{s}s"

    def _start_stage(self, stage: str):
        """记录阶段开始时间"""
        now = time.time()
        if self._overall_start == 0.0:
            self._overall_start = now
        self._stage_start[stage] = now

    def _elapsed_total(self) -> float:
        """整体已用时间（秒）"""
        if self._overall_start == 0.0:
            return 0.0
        return time.time() - self._overall_start

    def _elapsed_stage(self, stage: str) -> float:
        """当前阶段已用时间（秒）"""
        start = self._stage_start.get(stage)
        if start is None:
            return 0.0
        return time.time() - start

    def _setup_llms(self, pro_api_key: str, pro_base_url: str, pro_model: str,
                    flash_api_key: str = "", flash_base_url: str = "",
                    flash_model: str = "deepseek-v4-flash", stage_models: dict = None):
        """按阶段分配不同的 LLM（flash vs pro），支持用户自定义每个阶段的模型选择"""
        # 默认阶段分配：简单任务用 flash，复杂任务用 pro
        _defaults = {
            "keyword_extraction": "flash",
            "relevance_scoring": "flash",
            "structured_extraction": "pro",
            "timeline_analysis": "pro",
            "topic_clustering": "pro",
            "conflict_detection": "pro",
            "chapter_planning": "flash",
            "review_writing": "pro",
            "citation_checking": "flash",
            "polishing": "flash",
        }
        stages = {**_defaults, **(stage_models or {})}

        # 创建 Flash LLM（快速模型，适用于简单格式化/校验任务）
        _flash_key = flash_api_key or pro_api_key
        _flash_url = flash_base_url or "https://api.deepseek.com"
        _flash_model = flash_model or "deepseek-v4-flash"
        flash_llm = ChatOpenAI(
            model=_flash_model,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            openai_api_key=_flash_key,
            base_url=_flash_url,
        )

        # 创建 Pro LLM（推理模型，适用于深度分析/撰写任务）
        pro_llm = ChatOpenAI(
            model=pro_model or settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            openai_api_key=pro_api_key or settings.OPENAI_API_KEY,
            base_url=pro_base_url or settings.OPENAI_BASE_URL,
        )

        # 阶段 → 子模块映射
        _stage_modules = {
            "keyword_extraction": [self.keyword_extractor],
            "relevance_scoring": [self.relevance_scorer],
            "structured_extraction": [self.structured_extractor],
            "timeline_analysis": [self.timeline_analyzer],
            "topic_clustering": [self.topic_clusterer],
            "conflict_detection": [self.conflict_detector],
            "chapter_planning": [self.planner],
            "review_writing": [self.writer],
            "citation_checking": [self.citation_checker],
            "polishing": [self.polisher],
        }

        # 按阶段分配 LLM
        flash_count = pro_count = 0
        for stage, modules in _stage_modules.items():
            choice = stages.get(stage, "pro")
            llm = flash_llm if choice == "flash" else pro_llm
            for m in modules:
                m.llm = llm
            if choice == "flash":
                flash_count += 1
            else:
                pro_count += 1

        logger.info("LLM 分阶段配置: flash=%d 阶段, pro=%d 阶段 → %s",
                    flash_count, pro_count, stages)

    def _override_embedding(self, model_name: str):
        """运行时切换 Embedding 模型"""
        if model_name and model_name != self.vector_search.model_name:
            logger.info("切换 Embedding: %s → %s", self.vector_search.model_name, model_name)
            self.vector_search.model_name = model_name
            self.vector_search._model = None  # 触发重新加载

    def _override_reranker(self, model_name: str):
        """运行时切换 Reranker 模型"""
        if model_name and model_name != self.reranker.model_name:
            logger.info("切换 Reranker: %s → %s", self.reranker.model_name, model_name)
            self.reranker.model_name = model_name
            self.reranker._model = None  # 触发重新加载

    def set_progress_callback(self, callback):
        """
        设置进度回调。

        callback(stage: str, sub_stage: str, fraction: float, message: str)
          - stage: 主阶段名 (extracting_keywords/searching/ranking/extracting/analyzing/generating)
          - sub_stage: 子步骤名
          - fraction: 当前阶段内进度 (0.0~1.0)
          - message: 用户可读的进度消息
        """
        self._progress_callback = callback

    async def _report_progress(self, stage: str, sub_stage: str, fraction: float,
                               message: str, extra: str = ""):
        """
        向外部报告进度（如果设置了回调）。

        Args:
            stage: 主阶段名
            sub_stage: 子步骤名
            fraction: 当前阶段内进度 (0.0~1.0)
            message: 用户可读的进度消息
            extra: 额外信息（如耗时），附加到消息末尾
        """
        if self._progress_callback:
            try:
                total_elapsed = self._elapsed_total()
                stage_elapsed = self._elapsed_stage(stage)
                timing = f"[总耗时 {self._fmt_time(total_elapsed)}"
                if stage_elapsed > 0:
                    timing += f" | 本阶段 {self._fmt_time(stage_elapsed)}"
                timing += "]"
                full_msg = f"{timing} {message}{extra}"
                result = self._progress_callback(stage, sub_stage, fraction, full_msg)
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                pass  # 进度回调失败不应影响主流程

    # ========== 节点实现 ==========

    async def _node_extract_keywords(self, state: AgentState) -> AgentState:
        """节点1: 关键词提取"""
        state["current_stage"] = "extracting_keywords"
        self._start_stage("extracting_keywords")
        query = state.get("user_query", "")
        round_num = state.get("round_num", 0)

        await self._report_progress("extracting_keywords", "jieba_tokenize", 0.0,
                                   f"JieBa 分词中...（第{round_num+1}轮）")
        state["logs"] = state.get("logs", []) + [
            f"[{datetime.now().isoformat()}] 开始提取关键词 (第{round_num+1}轮)"
        ]

        result = await self.keyword_extractor.extract(query, round_num=round_num)
        state["keywords"] = result.get("keywords", [])
        state["keywords_zh"] = result.get("keywords_zh", [])
        state["keywords_en"] = result.get("keywords_en", [])

        keywords_str = ", ".join(k["keyword"] for k in state["keywords"])
        await self._report_progress("extracting_keywords", "done", 1.0,
                                   f"关键词: {keywords_str}")

        logger.info("关键词: %s", [k["keyword"] for k in state["keywords"]])
        return state

    async def _node_search_papers(self, state: AgentState) -> AgentState:
        """节点2: 多源文献检索"""
        state["current_stage"] = "searching"
        self._start_stage("searching")

        all_keywords = state.get("keywords_en", []) + state.get("keywords_zh", [])
        if not all_keywords:
            all_keywords = [k["keyword"] for k in state.get("keywords", [])]

        config = state.get("config", {})
        papers_per_round = config.get("papers_per_round", settings.SEARCH_PAPERS_PER_ROUND)
        search_sources = self._get_sources(config)
        source_names = [s.source_name() for s in search_sources]

        await self._report_progress("searching", "multi_source", 0.2,
                                   f"检索中: {', '.join(source_names)} (目标 {papers_per_round} 篇)...")

        # 并行检索，各源自行管理超时（requests.get(timeout=30)）
        tasks = [source.search(all_keywords, max_results=papers_per_round)
                 for source in search_sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_papers: List[PaperRecord] = []
        failed_sources = 0
        empty_sources = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_sources += 1
                logger.warning("数据源 [%s] 检索异常: %s", source_names[i], result)
            else:
                count = len(result) if isinstance(result, list) else 0
                all_papers.extend(result)
                if count == 0:
                    empty_sources += 1
                logger.info("数据源 [%s]: %d 篇", source_names[i], count)

        total_sources = len(search_sources)
        # 全部检索源异常或返回空 → 立即中断
        if failed_sources + empty_sources >= total_sources and not all_papers:
            source_detail = ", ".join(source_names)
            error_msg = (
                f"所有检索源均无结果（{source_detail} 超时、失败或返回空列表）。"
                "请检查网络连接，或在 .env 中配置 ARXIV_API_URL 代理地址，"
                "或尝试启用其他检索源（PubMed/DBLP 通常更稳定）。"
            )
            state["error_message"] = error_msg
            state["current_stage"] = "searching"
            state["logs"] = state.get("logs", []) + [
                f"[{datetime.now().isoformat()}] ❌ {error_msg}"
            ]
            await self._report_progress("searching", "all_failed", 1.0, f"❌ {error_msg}")
            return state

        # 与之前轮次合并去重
        merged = state.get("merged_papers", [])
        existing_ids = {p.get("id") for p in merged}
        new_papers = [p for p in all_papers if p.get("id") not in existing_ids]
        merged.extend(new_papers)

        state["raw_papers"] = all_papers
        state["merged_papers"] = merged

        # 将新检索到的论文索引到向量数据库
        if new_papers:
            indexed = False
            for attempt in range(2):
                try:
                    self.vector_search.index_papers(new_papers)
                    logger.info("向量索引成功: %d 篇", len(new_papers))
                    indexed = True
                    break
                except Exception as e:
                    if attempt == 0:
                        logger.warning("向量索引第1次失败: %s，清空数据库重试...", e)
                        try:
                            self.vector_store.clear()
                        except Exception:
                            pass
                    else:
                        logger.error("向量索引失败，向量检索将不可用，仅使用 BM25: %s", e)
                        state["logs"] = state.get("logs", []) + [
                            f"[{datetime.now().isoformat()}] ⚠ 向量索引失败（已重试），仅 BM25 可用: {e}"
                        ]
            if not indexed:
                state["logs"] = state.get("logs", []) + [
                    f"[{datetime.now().isoformat()}] ⚠ 向量检索不可用，排序质量可能下降"
                ]

        await self._report_progress("searching", "done", 1.0,
                                   f"检索完成: {len(all_papers)} 篇新文献，累计 {len(merged)} 篇")

        state["logs"] = state.get("logs", []) + [
            f"[{datetime.now().isoformat()}] 检索到 {len(all_papers)} 篇新文献，累计 {len(merged)} 篇"
        ]

        logger.info("检索: 本轮 %d 篇, 累计 %d 篇", len(all_papers), len(merged))
        return state

    async def _node_rank_and_filter(self, state: AgentState) -> AgentState:
        """节点3: 混合排序 + 重排序 + 相关性筛选"""
        # 上游错误 → 跳过
        if state.get("error_message"):
            return state
        state["current_stage"] = "ranking"
        self._start_stage("ranking")

        all_keywords = state.get("keywords_en", []) + state.get("keywords_zh", [])
        query = " ".join(all_keywords) if all_keywords else state.get("user_query", "")
        config = state.get("config", {})
        final_papers = config.get("final_papers", config.get("papers_per_round", settings.SEARCH_PAPERS_PER_ROUND))
        merged = state.get("merged_papers", [])

        await self._report_progress("ranking", "bm25", 0.1,
                                   f"BM25 关键词检索中...（{len(merged)} 篇索引）")

        # 1. BM25 检索（在累积文献上建索引）
        if merged:
            self.bm25.index(merged)
            bm25_results = self.bm25.search(query, top_k=100)
        else:
            bm25_results = []

        await self._report_progress("ranking", "vector", 0.3, "向量语义检索中...")

        # 2. 向量检索
        vector_results = await self.vector_search.search(query, top_k=100)

        await self._report_progress("ranking", "rrf", 0.5,
                                   f"RRF 融合: BM25({len(bm25_results)}) + 向量({len(vector_results)})")

        # 3. RRF 融合
        fused = self.rrf.fuse(bm25_results, vector_results)

        await self._report_progress("ranking", "rerank", 0.7,
                                   f"BGE CrossEncoder 重排序中...（{len(fused)} 篇候选）")

        # 4. BGE 重排序（使用用户指定的最终文献数）
        ranked = self.reranker.rerank(
            query=state.get("user_query", query),
            papers=fused,
            top_k=final_papers,
        )
        # 二次保障：绝不超出用户指定的 final_papers
        ranked = ranked[:final_papers]

        state["ranked_papers"] = ranked
        await self._report_progress("ranking", "done", 1.0,
                                   f"排序完成: Top{len(ranked)} 篇高相关文献")

        state["logs"] = state.get("logs", []) + [
            f"[{datetime.now().isoformat()}] 排序完成: Top{len(ranked)}"
        ]

        logger.info("排序: RRF融合 %d 篇 → BGE重排 Top%d", len(fused), len(ranked))
        return state

    async def _node_adjust_search_params(self, state: AgentState) -> AgentState:
        """节点4: 调整检索参数（动态扩大检索范围）"""
        round_num = state.get("round_num", 0) + 1
        config = state.get("config", {})

        reason = state.get("retrieval_reason", "")

        # 逐轮增加随机性
        config["temperature_initial"] = min(0.3 + 0.15 * round_num, 0.7)
        config["top_p_initial"] = min(0.85 + 0.05 * round_num, 0.95)

        state["round_num"] = round_num
        state["config"] = config

        await self._report_progress(
            "adjust_search_params", f"round_{round_num}", 0.5,
            f"🔄 {reason}（temperature → {config['temperature_initial']:.2f}，扩大搜索范围）"
        )

        state["logs"] = state.get("logs", []) + [
            f"[{datetime.now().isoformat()}] {reason}: "
            f"temperature={config['temperature_initial']:.2f}, "
            f"top_p={config['top_p_initial']:.2f}"
        ]

        logger.info(
            "调整检索参数: round=%d, temp=%.2f, top_p=%.2f",
            round_num, config["temperature_initial"], config["top_p_initial"],
        )
        return state

    async def _node_extract_structured(self, state: AgentState) -> AgentState:
        """节点5: 分层摘要与结构化抽取（并行处理全部论文）"""
        # 上游错误 → 跳过
        if state.get("error_message"):
            return state
        state["current_stage"] = "extracting"
        self._start_stage("extracting")

        ranked = state.get("ranked_papers", [])
        query = state.get("user_query", "")

        if not ranked:
            state["structured_papers"] = []
            error_msg = "未检索到任何相关文献，请尝试更换检索词或降低检索条件。"
            state["error_message"] = error_msg
            state["logs"] = state.get("logs", []) + [
                f"[{datetime.now().isoformat()}] ⚠️ {error_msg}"
            ]
            await self._report_progress("extracting", "empty", 1.0, f"⚠️ {error_msg}")
            return state

        total = len(ranked)
        completed_count = 0
        completed_lock = asyncio.Lock()

        await self._report_progress("extracting", "start", 0.0,
                                   f"开始结构化抽取 {total} 篇论文（并行，最多 {self._semaphore._value} 并发）...")

        # 并行抽取全部论文（信号量控制并发数，避免 API 限流）
        sem = self._semaphore

        async def _extract_one(idx: int, paper: PaperRecord):
            nonlocal completed_count
            title = paper.get("title", "")[:60]
            async with sem:
                result = await self.structured_extractor.extract(paper, {}, query)

            # 每完成一篇更新进度
            async with completed_lock:
                completed_count += 1
                fraction = completed_count / total
                await self._report_progress(
                    "extracting", f"paper_{completed_count}_of_{total}", fraction,
                    f"结构化抽取中... ({completed_count}/{total}) {title}"
                )
            return result

        tasks = [_extract_one(i, p) for i, p in enumerate(ranked)]
        structured_papers = await asyncio.gather(*tasks, return_exceptions=True)

        # 过滤掉异常的抽取结果
        valid_papers = []
        for i, result in enumerate(structured_papers):
            if isinstance(result, Exception):
                logger.warning("论文抽取异常 [%s]: %s", ranked[i].get("id", "?"), result)
            else:
                valid_papers.append(result)

        state["structured_papers"] = valid_papers
        await self._report_progress("extracting", "done", 1.0,
                                   f"结构化抽取完成: {len(valid_papers)}/{total} 篇成功")

        state["logs"] = state.get("logs", []) + [
            f"[{datetime.now().isoformat()}] 结构化抽取完成: {len(valid_papers)}/{total} 篇"
        ]

        logger.info("结构化抽取: %d/%d 篇完成 (并行)", len(valid_papers), total)
        return state

    async def _node_analyze(self, state: AgentState) -> AgentState:
        """节点6: 关联分析（时间线 + 聚类 + 冲突）"""
        # 上游错误 → 跳过
        if state.get("error_message"):
            return state
        state["current_stage"] = "analyzing"
        self._start_stage("analyzing")

        structured = state.get("structured_papers", [])
        query = state.get("user_query", "")

        if not structured:
            await self._report_progress("analyzing", "skipped", 1.0, "无文献可分析，跳过")
            state["timeline"] = ""
            state["topic_clusters"] = []
            state["conflicts"] = []
            return state

        await self._report_progress("analyzing", "start", 0.0,
                                   f"开始分析 {len(structured)} 篇论文的关联关系...")

        # 并行执行三类分析，每个完成后上报
        async def _timeline_with_progress():
            result = await self.timeline_analyzer.analyze(structured, query)
            await self._report_progress("analyzing", "timeline_done", 0.35, "时间线分析完成 ✓")
            return result

        async def _cluster_with_progress():
            result = await self.topic_clusterer.cluster(structured, query)
            await self._report_progress("analyzing", "cluster_done", 0.65,
                                       f"主题聚类完成: {len(result.get('clusters', []))} 个聚类")
            return result

        async def _conflict_with_progress():
            result = await self.conflict_detector.detect(structured, query)
            await self._report_progress("analyzing", "conflict_done", 1.0,
                                       f"冲突识别完成: {len(result.get('conflicts', []))} 个冲突")
            return result

        timeline_result, cluster_result, conflict_result = await asyncio.gather(
            _timeline_with_progress(), _cluster_with_progress(), _conflict_with_progress(),
        )

        state["timeline"] = timeline_result.get("timeline", "")
        state["timeline_data"] = timeline_result
        state["topic_clusters"] = cluster_result.get("clusters", [])
        state["conflicts"] = conflict_result.get("conflicts", [])
        state["open_questions"] = conflict_result.get("open_questions", [])

        state["logs"] = state.get("logs", []) + [
            f"[{datetime.now().isoformat()}] 分析完成: "
            f"{len(state['topic_clusters'])} 个聚类, "
            f"{len(state['conflicts'])} 个冲突"
        ]

        logger.info(
            "关联分析: %d 聚类, %d 冲突, %d 开放问题",
            len(state["topic_clusters"]),
            len(state["conflicts"]),
            len(state.get("open_questions", [])),
        )
        return state

    async def _node_generate_review(self, state: AgentState) -> AgentState:
        """节点7: 综述生成 + 引用验证 + 润色"""
        state["current_stage"] = "generating"
        self._start_stage("generating")

        # 空结果保护：避免 LLM 凭空生成不存在的综述
        error_msg = state.get("error_message", "")
        structured = state.get("structured_papers", [])
        if not structured:
            await self._report_progress("generating", "aborted", 1.0,
                                       f"⚠️ 无法生成综述: {error_msg or '未找到相关文献'}")
            state["final_review"] = (
                f"# ⚠️ 综述生成失败\n\n"
                f"**原因**: {error_msg or '未检索到任何相关文献。'}\n\n"
                f"**建议**:\n"
                f"- 尝试使用更通用的英文关键词\n"
                f"- 减少每个关键词的限定条件\n"
                f"- 检查 arXiv API 是否被限流（HTTP 429）\n"
            )
            return state

        query = state.get("user_query", "")
        timeline = state.get("timeline", "")
        clusters = state.get("topic_clusters", [])
        conflicts = state.get("conflicts", [])

        # 1. 规划章节
        await self._report_progress("generating", "planning", 0.05, "正在规划综述章节结构...")
        chapter_plan = await self.planner.plan(
            query, state.get("timeline_data", {}),
            clusters, conflicts, structured,
        )
        state["chapter_plan"] = chapter_plan
        await self._report_progress("generating", "planned", 0.15,
                                   f"章节规划完成: {len(chapter_plan)} 章")

        # 2. 撰写综述
        await self._report_progress("generating", "writing", 0.20,
                                   f"正在撰写综述全文...（基于 {len(structured)} 篇论文）")
        language = (state.get("config") or {}).get("language", "zh")
        draft = await self.writer.write(
            query, chapter_plan, timeline,
            clusters, conflicts, structured,
            language=language,
        )
        state["draft"] = draft
        await self._report_progress("generating", "written", 0.55,
                                   f"综述草稿完成: {len(draft):,} 字符")

        # 3. 引用验证
        await self._report_progress("generating", "verifying_citations", 0.60, "正在验证引用准确性...")
        citation_result = await self.citation_checker.verify(draft, structured)
        await self._report_progress("generating", "citations_verified", 0.75,
                                   f"引用验证: {citation_result['verified_count']}/{citation_result['total_count']} 通过"
                                   + (f"（{citation_result['suspicious_count']} 个可疑）" if citation_result.get('suspicious_count', 0) > 0 else ""))

        # 4. 润色
        await self._report_progress("generating", "polishing", 0.80, "正在润色综述（学术规范检查）...")
        polished = await self.polisher.polish(draft, citation_result)
        state["final_review"] = polished
        await self._report_progress("generating", "done", 1.0,
                                   f"综述生成完毕: {len(polished):,} 字符")

        state["logs"] = state.get("logs", []) + [
            f"[{datetime.now().isoformat()}] 综述生成完成: "
            f"{len(polished)} 字符, "
            f"引用验证: {citation_result['verified_count']}/{citation_result['total_count']} 通过"
        ]

        logger.info("综述生成: %d 字符, 引用 %d/%d 通过",
                     len(polished),
                     citation_result["verified_count"],
                     citation_result["total_count"])
        return state

    # ========== 公共接口 ==========

    async def run(
        self,
        query: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> AgentState:
        """
        运行完整工作流。

        Args:
            query: 用户研究主题
            config: 可选配置覆盖

        Returns:
            完整的 AgentState（含最终综述）
        """
        default_config: SearchConfig = {
            "max_rounds": settings.SEARCH_MAX_ROUNDS,
            "papers_per_round": settings.SEARCH_PAPERS_PER_ROUND,
            "temperature_initial": settings.SEARCH_TEMPERATURE_INITIAL,
            "top_p_initial": settings.SEARCH_TOP_P_INITIAL,
        }
        if config:
            default_config.update(config)

        # 运行时 LLM 分阶段配置（flash vs pro）
        if config:
            pro_key = config.get("llm_api_key", "") or settings.OPENAI_API_KEY
            pro_url = config.get("llm_base_url", "") or settings.OPENAI_BASE_URL
            pro_model = config.get("llm_model", "") or settings.LLM_MODEL
            flash_key = config.get("flash_api_key", "") or settings.FLASH_API_KEY
            flash_url = config.get("flash_base_url", "") or settings.FLASH_BASE_URL
            flash_model = config.get("flash_model", "") or settings.FLASH_MODEL
            stage_models = config.get("stage_models", {})
            logger.info("运行时 LLM: pro=%s, flash=%s", pro_model, flash_model)
            self._setup_llms(pro_key, pro_url, pro_model,
                           flash_key, flash_url, flash_model, stage_models)

        # 运行时 Embedding / Reranker 模型覆盖
        if config:
            emb = config.get("embedding_model", "")
            if emb:
                self._override_embedding(emb)
            rerank = config.get("reranker_model", "")
            if rerank:
                self._override_reranker(rerank)

        # 清空上一次运行的向量索引，避免跨 session 污染
        try:
            self.vector_store.clear()
            logger.info("已清空向量数据库，准备新 session")
        except Exception as e:
            logger.warning("清空向量库失败（非致命）: %s", e)

        # 重置计时器
        self._overall_start = 0.0
        self._stage_start.clear()
        self._stage_elapsed.clear()

        initial_state: AgentState = {
            "user_query": query,
            "config": default_config,
            "round_num": 0,
            "raw_papers": [],
            "merged_papers": [],
            "ranked_papers": [],
            "structured_papers": [],
            "topic_clusters": [],
            "conflicts": [],
            "open_questions": [],
            "chapter_plan": [],
            "draft": "",
            "final_review": "",
            "current_stage": "init",
            "error_message": "",
            "errors": [],
            "logs": [],
            "task_id": f"rev_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "started_at": datetime.now().isoformat(),
        }

        logger.info("=" * 60)
        logger.info("开始综述生成: %s", query)
        logger.info("=" * 60)

        try:
            result = await self._graph.ainvoke(initial_state)
            logger.info("工作流完成: %s", query[:50])
            return result
        except Exception as e:
            logger.error("工作流失败: %s", e, exc_info=True)
            raise
