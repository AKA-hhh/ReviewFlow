"""
科研文献智能综述系统 — 桌面版入口

使用 PyWebView 创建原生桌面窗口，内嵌 HTML 前端。
Python 后端复用 src/ 下的所有模块。
"""

import asyncio
import json
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env 和 HF 镜像（必须在其他 import 之前）
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")
os.environ.setdefault("HF_ENDPOINT", os.getenv("HF_ENDPOINT", "https://hf-mirror.com"))

import webview

from src.agents.supervisor import SupervisorAgent
from src.config.settings import settings

# 用户设置文件（与 Web UI 共享）
USER_SETTINGS_FILE = PROJECT_ROOT / "config" / "user_settings.json"


def _load_user_settings() -> dict:
    """加载用户设置"""
    if USER_SETTINGS_FILE.exists():
        try:
            return json.loads(USER_SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_user_settings(s: dict):
    """保存用户设置"""
    USER_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USER_SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def _fix_reference_format(text: str) -> str:
    """修复参考文献格式：每个引用独立一行 + 移除 [待核实] 标记"""
    if not text:
        return text
    # 移除 [待核实] 标记
    text = re.sub(r'\s*\[待核实\]', '', text)
    # 每个 [N] 引用前换行（不在行首时）
    text = re.sub(r'(?<=[。.…])(\s*\[\d+\])', r'\n\1', text)
    # 数字序号引用 (1. 2. 等) 前确保换行
    text = re.sub(r'(?<=[。.])(\s*\d+\.\s+(?=[A-Z]))', r'\n\1', text)
    return text


def _markdown_to_html(md: str) -> str:
    """将 Markdown 转换为 HTML（基础转换）"""
    import html as html_mod
    text = html_mod.escape(md, quote=False)

    # Headers
    text = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)

    # Bold / Italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)

    # Inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # Horizontal rules
    text = re.sub(r'^---$', '<hr>', text, flags=re.MULTILINE)

    # Blockquotes
    text = re.sub(r'^&gt; (.+)$', r'<blockquote>\1</blockquote>', text, flags=re.MULTILINE)

    # Unordered lists
    text = re.sub(r'^[\-\*] (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    text = re.sub(r'(<li>.*</li>\n?)+', r'<ul>\n\g<0></ul>\n', text)

    # Ordered lists
    text = re.sub(r'^\d+\. (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)

    # Paragraphs
    paragraphs = text.split('\n\n')
    result = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if re.match(r'^<(h[1-4]|ul|ol|hr|blockquote|table)', p):
            result.append(p)
        else:
            result.append('<p>' + p.replace('\n', '<br>') + '</p>')

    return '\n'.join(result)


class ReviewAPI:
    """暴露给 JavaScript 的 API 类"""

    def __init__(self, window):
        self._window = window
        self._supervisor = SupervisorAgent()

    @staticmethod
    def _js_str(s: str) -> str:
        """安全地将 Python 字符串转为 JS 字符串字面量"""
        return json.dumps(s, ensure_ascii=False)

    def _emit_progress(self, stage: str, progress: float, message: str):
        """推送进度到前端"""
        self._window.evaluate_js(
            f"onProgress({self._js_str(stage)}, {progress}, {self._js_str(message)})"
        )

    def get_settings(self) -> str:
        """获取当前用户设置（返回 JSON 字符串）"""
        s = _load_user_settings()
        # 填充默认值（与 Streamlit 端保持一致）
        defaults = {
            "llm_base_url": os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
            "llm_api_key": os.getenv("OPENAI_API_KEY", ""),
            "llm_model": os.getenv("LLM_MODEL", "deepseek-v4-pro"),
            "flash_base_url": os.getenv("FLASH_BASE_URL", "https://api.deepseek.com"),
            "flash_model": os.getenv("FLASH_MODEL", "deepseek-v4-flash"),
            "flash_api_key": os.getenv("FLASH_API_KEY", ""),
            "stage_models": {
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
            },
            "embedding_model": os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
            "reranker_model": os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
            "max_rounds": 2,
            "papers_per_round": 30,
            "final_papers": 10,
            "language": "zh",  # zh=中文 / en=English
            "search_sources": ["pubmed", "dblp"],
            "output_dir": str(PROJECT_ROOT / "output"),
        }
        for k, v in defaults.items():
            if k not in s:
                s[k] = v
        return json.dumps(s, ensure_ascii=False)

    def save_settings(self, settings_json: str):
        """保存用户设置（由 JS 调用）"""
        s = json.loads(settings_json)
        # 保留自定义检索源（由 add_custom_source/remove_custom_source 管理）
        existing = _load_user_settings()
        s["custom_sources"] = existing.get("custom_sources", [])
        _save_user_settings(s)
        return "ok"

    def generate_review(self, query: str, config_json: str):
        """
        生成综述（由 JS 调用）。
        在后台线程中运行异步任务。
        """
        config = json.loads(config_json) if config_json else {}
        # 合并已保存的用户设置
        saved = _load_user_settings()
        for key in ("max_rounds", "papers_per_round", "final_papers",
                     "search_sources", "language", "custom_sources",
                     "llm_api_key", "llm_base_url",
                     "llm_model", "flash_api_key", "flash_base_url",
                     "flash_model", "stage_models",
                     "output_dir", "embedding_model", "reranker_model"):
            if key in saved and key not in config:
                config[key] = saved[key]

        async def _run():
            try:
                async def progress_cb(stage, pct, msg):
                    self._emit_progress(stage, pct, msg)

                result = await self._supervisor.generate_review(
                    query, config, on_progress=progress_cb,
                )

                # 序列化结果（移除不可 JSON 序列化的字段）
                safe_result = {
                    "task_id": result.get("task_id", ""),
                    "final_review": _fix_reference_format(result.get("final_review", "")),
                    "draft": result.get("draft", ""),
                    "topic_clusters": result.get("topic_clusters", []),
                    "conflicts": result.get("conflicts", []),
                    "logs": result.get("logs", []),
                    "statistics": result.get("statistics", {}),
                    "structured_papers": [
                        {
                            "paper_id": p.get("paper_id", ""),
                            "title": p.get("title", ""),
                            "authors": p.get("authors", []),
                            "journal": p.get("journal", ""),
                            "year": p.get("year", 0),
                            "relevance_score": p.get("relevance_score", 0),
                            "relevance_level": p.get("relevance_level", ""),
                            "key_findings": p.get("key_findings", []),
                            "sections": p.get("sections", {}),
                        }
                        for p in result.get("structured_papers", [])
                    ],
                }

                result_json = json.dumps(safe_result, ensure_ascii=False)
                # 双重编码：json.dumps 包装确保 JS 收到的是字符串而非对象字面量
                self._window.evaluate_js(f"onComplete({json.dumps(result_json)})")

            except Exception as e:
                self._window.evaluate_js(f"onError({self._js_str(str(e))})")

        # 在新线程中运行异步任务
        def _thread_target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())

        thread = threading.Thread(target=_thread_target, daemon=True)
        thread.start()

    def test_source_connection(self, name: str) -> str:
        """测试已知检索源的连通性（内置或自定义），由 JS 调用"""
        import asyncio as _asyncio

        async def _test():
            # 先检查是否是内置源
            from src.retrieval.sources import SOURCE_REGISTRY
            cls = SOURCE_REGISTRY.get(name)
            if cls:
                try:
                    source = cls()
                    papers = await _asyncio.wait_for(
                        source.search(["test"], max_results=3), timeout=20
                    )
                    return {
                        "ok": True,
                        "message": f"获取到 {len(papers)} 篇文献，连接正常",
                    }
                except _asyncio.TimeoutError:
                    return {"ok": False, "message": "连接超时，请检查网络"}
                except Exception as e:
                    return {"ok": False, "message": str(e)[:200]}

            # 检查是否是自定义源
            saved = _load_user_settings()
            custom_sources = saved.get("custom_sources", [])
            custom = next((s for s in custom_sources if s.get("name") == name), None)
            if custom:
                from src.retrieval.sources.custom import CustomApiSource
                return await CustomApiSource.test_endpoint(
                    custom["base_url"], custom.get("api_key", ""),
                    custom.get("search_path", "/search"),
                    custom.get("query_param", "q"),
                    custom.get("limit_param", "limit"),
                    custom.get("results_path", "data"),
                )

            return {"ok": False, "message": f"未知检索源: {name}"}

        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_test())
        finally:
            loop.close()
        return json.dumps(result, ensure_ascii=False)

    def test_custom_source(self, name: str, url: str, api_key: str = "",
                           search_path: str = "/search", query_param: str = "q",
                           limit_param: str = "limit", results_path: str = "data") -> str:
        """测试自定义检索源端点（由 JS 调用），返回 JSON 结果"""
        import asyncio as _asyncio

        async def _test():
            from src.retrieval.sources.custom import CustomApiSource
            return await CustomApiSource.test_endpoint(
                url, api_key, search_path, query_param, limit_param, results_path,
            )

        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_test())
        finally:
            loop.close()
        return json.dumps(result, ensure_ascii=False)

    def add_custom_source(self, name: str, url: str, api_key: str = "",
                          search_path: str = "/search", query_param: str = "q",
                          limit_param: str = "limit", results_path: str = "data") -> str:
        """添加自定义检索源到本地设置"""
        saved = _load_user_settings()
        custom_sources = saved.get("custom_sources", [])
        # 去重
        existing = [s for s in custom_sources if s.get("name") == name]
        if existing:
            return json.dumps({"ok": False, "message": f"检索源 '{name}' 已存在"})
        custom_sources.append({
            "name": name,
            "base_url": url.rstrip("/"),
            "api_key": api_key,
            "search_path": search_path,
            "query_param": query_param,
            "limit_param": limit_param,
            "results_path": results_path,
        })
        saved["custom_sources"] = custom_sources
        # 自动加入 search_sources
        if name not in saved.get("search_sources", []):
            saved.setdefault("search_sources", []).append(name)
        _save_user_settings(saved)
        return json.dumps({"ok": True, "message": f"检索源 '{name}' 已添加"})

    def remove_custom_source(self, name: str) -> str:
        """删除自定义检索源"""
        saved = _load_user_settings()
        custom_sources = saved.get("custom_sources", [])
        saved["custom_sources"] = [s for s in custom_sources if s.get("name") != name]
        search_sources = saved.get("search_sources", [])
        if name in search_sources:
            search_sources.remove(name)
        _save_user_settings(saved)
        return json.dumps({"ok": True, "message": f"检索源 '{name}' 已移除"})

    def check_models_status(self) -> str:
        """检查 embedding/reranker 模型是否已下载，返回各模型状态"""
        import os as _os
        hf_root = Path(_os.environ.get("HF_HOME", str(PROJECT_ROOT / "models" / "huggingface")))
        hub_dir = hf_root / "hub"

        models = {
            # Embedding 向量模型
            "BAAI/bge-small-zh-v1.5": "Embedding",
            "BAAI/bge-large-zh-v1.5": "Embedding",
            "BAAI/bge-small-en-v1.5": "Embedding",
            "sentence-transformers/all-MiniLM-L6-v2": "Embedding",
            "BAAI/bge-micro-v2": "Embedding",
            "intfloat/multilingual-e5-small": "Embedding",
            # Reranker 重排序模型
            "BAAI/bge-reranker-v2-m3": "Reranker",
            "BAAI/bge-reranker-v2-minicpm-layerwise": "Reranker",
            "BAAI/bge-reranker-base": "Reranker",
            "cross-encoder/ms-marco-MiniLM-L-4-v2": "Reranker",
        }

        def _has_model(dir_path):
            """检查目录下是否有模型文件（支持多种格式和目录结构）"""
            if not dir_path.exists():
                return False
            patterns = ["snapshots/*/*.safetensors", "snapshots/*/*.bin",
                       "snapshots/*/*.pt", "snapshots/*/pytorch_model.bin"]
            for pat in patterns:
                if list(dir_path.glob(pat)):
                    return True
            return False

        result = {}
        for model_id, mtype in models.items():
            safe_name = model_id.replace("/", "--")
            # 兼容两种存储位置：hub/ 子目录（新版）和 HF_HOME 根目录（旧版）
            downloaded = _has_model(hub_dir / f"models--{safe_name}") or \
                        _has_model(hf_root / f"models--{safe_name}")
            result[model_id] = {"type": mtype, "downloaded": downloaded}

        return json.dumps(result, ensure_ascii=False)

    def download_model(self, model_id: str) -> str:
        """下载指定的模型到本地 models 文件夹"""
        import asyncio as _asyncio

        async def _download():
            from sentence_transformers import SentenceTransformer
            try:
                # Reranker 模型（含 cross-encoder 前缀）用 CrossEncoder 下载
                if "cross-encoder" in model_id.lower() or "reranker" in model_id.lower():
                    from sentence_transformers import CrossEncoder
                    _ = CrossEncoder(model_id, max_length=512)
                else:
                    _ = SentenceTransformer(model_id, trust_remote_code=True)
                return {"ok": True, "message": f"模型 {model_id} 下载完成"}
            except Exception as e:
                return {"ok": False, "message": str(e)[:300]}

        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_download())
        finally:
            loop.close()
        return json.dumps(result, ensure_ascii=False)

    def get_history(self) -> str:
        """读取历史记录"""
        history_file = PROJECT_ROOT / "output" / ".review_history.json"
        if history_file.exists():
            try:
                return history_file.read_text(encoding="utf-8")
            except Exception:
                pass
        return "[]"

    def save_history(self, data: str):
        """保存历史记录到文件"""
        history_file = PROJECT_ROOT / "output" / ".review_history.json"
        history_file.parent.mkdir(parents=True, exist_ok=True)
        history_file.write_text(data, encoding="utf-8")

    def get_custom_sources(self) -> str:
        """获取所有自定义检索源"""
        saved = _load_user_settings()
        return json.dumps(saved.get("custom_sources", []), ensure_ascii=False)

    def save_review(self, content: str, fmt: str = "md"):
        """保存综述到文件（支持 Markdown / Word / HTML）"""
        content = _fix_reference_format(content)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved = _load_user_settings()
        output_dir = Path(saved.get("output_dir", str(PROJECT_ROOT / "output")))
        output_dir.mkdir(parents=True, exist_ok=True)

        if fmt == "html":
            save_path = output_dir / f"review_{timestamp}.html"
            html_body = _markdown_to_html(content)
            html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>文献综述 — {timestamp}</title>
<style>
body {{ font-family: 'Source Serif 4', Georgia, serif; max-width: 800px; margin: 40px auto; padding: 0 24px; line-height: 1.85; color: #2d2416; background: #f7f3ea; }}
h1 {{ font-family: 'Playfair Display', Georgia, serif; font-size: 1.6em; border-bottom: 1px solid #ddd4c4; padding-bottom: 8px; }}
h2 {{ font-family: 'Playfair Display', Georgia, serif; font-size: 1.25em; }}
h3 {{ font-family: 'Playfair Display', Georgia, serif; font-size: 1.1em; }}
code {{ background: #f4efe4; padding: 2px 6px; border-radius: 3px; font-family: 'JetBrains Mono', monospace; font-size: 0.9em; }}
blockquote {{ border-left: 3px solid #8b6914; background: rgba(139,105,20,0.06); padding: 8px 16px; margin: 0.8em 0; border-radius: 0 6px 6px 0; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd4c4; padding: 6px 12px; text-align: left; }}
@media print {{ body {{ font-size: 12pt; }} }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""
            save_path.write_text(html_doc, encoding="utf-8")

        elif fmt == "doc":
            save_path = output_dir / f"review_{timestamp}.doc"
            html_body = _markdown_to_html(content)
            html_doc = f"""<html xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:w="urn:schemas-microsoft-com:office:word"
      xmlns="http://www.w3.org/TR/REC-html40">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View></w:WordDocument></xml><![endif]-->
<style>
@page {{ margin: 2cm; }}
body {{ font-family: 'Source Serif 4', Georgia, serif; font-size: 12pt; line-height: 1.8; color: #333; }}
h1 {{ font-size: 18pt; border-bottom: 1px solid #ccc; padding-bottom: 6px; }}
h2 {{ font-size: 14pt; }}
h3 {{ font-size: 12pt; }}
code {{ background: #f5f5f5; padding: 2px 4px; font-family: 'Courier New', monospace; font-size: 10pt; }}
blockquote {{ border-left: 3px solid #ccc; padding: 6px 12px; margin: 0.6em 0; color: #555; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid #ccc; padding: 4px 8px; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""
            save_path.write_text(html_doc, encoding="utf-8")

        else:  # md
            save_path = output_dir / f"review_{timestamp}.md"
            save_path.write_text(content, encoding="utf-8")

        return str(save_path)


def main():
    # 从 app_full.html 加载（自动组装自 app.html + app.css + app.js）
    html_path = Path(__file__).parent / "app_full.html"
    if not html_path.exists():
        # 首次运行：从拆分文件组装
        src_html = Path(__file__).parent / "app.html"
        src_css = Path(__file__).parent / "app.css"
        src_js = Path(__file__).parent / "app.js"
        html_content = src_html.read_text(encoding="utf-8")
        css_content = src_css.read_text(encoding="utf-8")
        js_content = src_js.read_text(encoding="utf-8")
        html_content = html_content.replace(
            '<link rel="stylesheet" href="app.css">',
            '<style>\n' + css_content + '\n</style>'
        )
        html_content = html_content.replace(
            '<script src="app.js"></script>',
            '<script>\n' + js_content + '\n</script>'
        )
        html_path.write_text(html_content, encoding="utf-8")
    else:
        html_content = html_path.read_text(encoding="utf-8")

    # 先创建 API（暂不关联窗口）
    api = ReviewAPI(None)

    # 创建窗口
    window = webview.create_window(
        title="📚 科研文献智能综述系统",
        html=html_content,
        js_api=api,
        width=1200,
        height=850,
        min_size=(900, 600),
        resizable=True,
    )

    # 回设窗口引用
    api._window = window

    webview.start(debug=False, gui="edgechromium")


if __name__ == "__main__":
    main()
