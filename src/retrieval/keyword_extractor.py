"""
关键词提取模块。

使用 JieBa 分词 + LLM 打分提取 Top3 核心检索关键词。
"""

import json
import logging
import re
from typing import Any, Dict, List

import jieba
import jieba.posseg as pseg
from langchain_core.language_models import BaseChatModel

from src.config.settings import settings
from src.storage.cache import get_search_cache

logger = logging.getLogger(__name__)

# 停用词
STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "latest", "recent", "new", "research", "study", "paper", "survey",
    "最新", "研究", "进展", "论文", "相关", "综述", "方法", "技术",
    "the", "this", "that", "these", "those", "基于", "及其", "一个",
}


class KeywordExtractor:
    """
    JieBa 分词 + LLM 打分的关键词提取器。

    流程：
    1. JieBa 分词 + 词性标注
    2. 停用词过滤 + 专业术语提取
    3. LLM 对候选词进行重要性打分
    4. 输出中英文 Top3 关键词
    """

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self._cache = get_search_cache()

    def _jieba_extract(self, query: str) -> List[str]:
        """使用 JieBa 分词提取候选关键词"""
        # 精确模式分词 + 词性标注
        words = pseg.cut(query)

        candidates = []
        for word, flag in words:
            word = word.strip().lower()
            if len(word) < 2:
                continue
            if word in STOP_WORDS:
                continue
            # 保留名词、动词、英文词、专业术语
            if flag.startswith(("n", "v", "eng")) or re.match(r"[a-zA-Z]", word):
                candidates.append(word)

        # 去重保序
        seen = set()
        unique = []
        for w in candidates:
            if w not in seen:
                seen.add(w)
                unique.append(w)

        logger.info("JieBa 分词候选词: %s", unique)
        return unique

    async def _llm_score(self, query: str, candidates: List[str]) -> List[Dict[str, Any]]:
        """使用 LLM 对候选词打分"""
        prompt_path = settings.PROMPTS_DIR / "keyword_scoring.txt"
        template = prompt_path.read_text(encoding="utf-8")

        prompt = template.format(
            query=query,
            candidates=json.dumps(candidates, ensure_ascii=False),
        )

        # 由于模板已经是完整 prompt，这里需要处理一下
        # 先手动替换 {candidates} 占位
        prompt = template.replace("{query}", query)
        # 构建候选词展示
        candidates_str = "\n".join(f"{i+1}. {c}" for i, c in enumerate(candidates))
        prompt = prompt.replace("{candidates}", candidates_str)

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            # 清理 JSON（可能包裹在 markdown 代码块中，或有格式问题）
            content = re.sub(r"```(?:json)?\s*", "", content)
            content = re.sub(r"```", "", content)
            # LLM 可能输出单引号 JSON
            content = content.strip()
            if content.startswith("'") and content.endswith("'"):
                content = content[1:-1]
            # 尝试修复常见的 LLM JSON 错误：未加引号的 key
            content = re.sub(r'(?<=\{|\s)(\w+)(?=\s*:)', r'"\1"', content)

            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                # 二次尝试：只提取花括号内的内容
                m = re.search(r'\{[^{}]*"keywords"\s*:\s*\[.*?\]\s*[^{}]*\}', content, re.DOTALL)
                if m:
                    content = m.group(0)
                    content = re.sub(r'(?<=\{|\s)(\w+)(?=\s*:)', r'"\1"', content)
                result = json.loads(content)
            keywords = result.get("keywords", [])

            logger.info("LLM 关键词打分完成: %s", keywords[:3])
            return keywords

        except Exception as e:
            logger.error("LLM 关键词打分失败: %s", e)
            # 降级：返回权重相同的前3个候选词
            return [
                {"keyword": c, "score": 5.0, "language": "unknown"}
                for c in candidates[:3]
            ]

    async def extract(self, query: str, round_num: int = 0) -> Dict[str, Any]:
        """
        提取核心关键词。

        Args:
            query: 用户查询
            round_num: 当前检索轮数（用于避免缓存命中，每轮可产生不同关键词）

        Returns:
            {"keywords": [...], "keywords_zh": [...], "keywords_en": [...]}
        """
        cache_key = f"keywords:{query}:r{round_num}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.info("关键词缓存命中")
            return cached

        # Step 1: JieBa 分词
        candidates = self._jieba_extract(query)

        # Step 2: LLM 打分
        scored = await self._llm_score(query, candidates)

        # Step 3: 提取 Top3 核心词
        top3 = sorted(scored, key=lambda x: x.get("score", 0), reverse=True)[:3]

        # Step 4: 分离中英文
        zh_keywords = [k["keyword"] for k in top3 if k.get("language") != "en"]
        en_keywords = [k["keyword"] for k in top3 if k.get("language") == "en"]

        # 如果全是中文，尝试生成英文变体；反之亦然
        if not en_keywords:
            en_keywords = [k["keyword"] for k in top3]  # 后续检索时翻译
        if not zh_keywords:
            zh_keywords = [k["keyword"] for k in top3]

        result = {
            "keywords": top3,
            "keywords_zh": zh_keywords,
            "keywords_en": en_keywords,
        }

        self._cache.set(cache_key, result, ttl=3600)
        return result
