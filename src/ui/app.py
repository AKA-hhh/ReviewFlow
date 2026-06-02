"""
Streamlit Web UI - 双页面架构。

主页面: 综述生成（输入主题 + 快速参数 + 生成 + 结果展示）
设置页: 系统配置（LLM、检索源、输出目录等，可保存到本地）
"""

import os
from pathlib import Path

# 必须在 sentence-transformers 导入前设置
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
if "HF_HOME" not in os.environ:
    _project_root = Path(__file__).parent.parent.parent
    os.environ.setdefault("HF_HOME", str(_project_root / "models" / "huggingface"))

# 确保 .env 已加载，后续 load_settings() 需要读取其中的 API Key / Model 等
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

import asyncio
import json
import sys
from datetime import datetime

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

st.set_page_config(
    page_title="Noir Scholar · 科研文献智能综述系统",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject Google Fonts for Noir Scholar typography
GOOGLE_FONTS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,500;0,600;0,700;0,800;1,400;1,500&family=Source+Serif+4:ital,opsz,wght@0,8..60,300;0,8..60,400;0,8..60,500;0,8..60,600;0,8..60,700;1,8..60,400&family=JetBrains+Mono:ital,wght@0,300;0,400;0,500;1,400&family=Inter:opsz,wght@14..32,300;14..32,400;14..32,500;14..32,600;14..32,700&display=swap');
</style>
"""
st.markdown(GOOGLE_FONTS, unsafe_allow_html=True)

PROJECT_ROOT = Path(__file__).parent.parent.parent
SETTINGS_FILE = PROJECT_ROOT / "config" / "user_settings.json"


# ============================================================
#  设置管理
# ============================================================
def load_settings() -> dict:
    """从文件加载用户设置，不存在则返回默认值"""
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
        "max_rounds": 2,
        "papers_per_round": 30,
        "final_papers": 10,
        "language": "zh",  # zh=中文 / en=English
        "search_sources": ["arxiv", "semantic_scholar"],
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "reranker_model": "BAAI/bge-reranker-v2-m3",
        "output_dir": str(PROJECT_ROOT / "output"),
    }
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_settings(settings: dict):
    """保存用户设置到本地文件"""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def init_session_state():
    """初始化 session_state"""
    if "settings" not in st.session_state:
        st.session_state.settings = load_settings()
    if "page" not in st.session_state:
        st.session_state.page = "generate"


# ============================================================
#  CSS
# ============================================================
PAGE_CSS = """
<style>
/* ============================================================
   Noir Scholar — Streamlit Edition
   Warm parchment tones · Gold accents · Serif typography
   ============================================================ */

/* ===== CSS Variables (injected into :root) ===== */
:root {
  --ns-accent: #8b6914;
  --ns-accent-dim: #6b4f10;
  --ns-accent-glow: rgba(139, 105, 20, 0.08);
  --ns-bg: #f7f3ea;
  --ns-surface: #ffffff;
  --ns-border: #ddd4c4;
  --ns-text: #2d2416;
  --ns-text-secondary: #6b6050;
  --ns-text-muted: #968b78;
  --ns-heading: #1a1008;
  --ns-success: #5a9e6f;
  --ns-warning: #c9954e;
  --ns-error: #c85554;
  --ns-info: #5b8ca8;
  --ns-radius: 10px;
  --ns-radius-sm: 6px;
  --font-display: 'Playfair Display', Georgia, 'Times New Roman', serif;
  --font-body: 'Source Serif 4', Georgia, serif;
  --font-ui: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
}

/* ===== Global Typography ===== */
html, body, [data-testid="stAppViewContainer"] {
  font-family: var(--font-ui) !important;
  color: var(--ns-text) !important;
}

h1, h2, h3, h4, h5, h6 {
  font-family: var(--font-display) !important;
  color: var(--ns-heading) !important;
  font-weight: 600 !important;
}

/* Main app background */
[data-testid="stAppViewContainer"] {
  background: var(--ns-bg) !important;
}

/* ===== Page Headers ===== */
.main-header {
  font-family: var(--font-display) !important;
  font-size: 2.2rem !important;
  font-weight: 700 !important;
  margin-bottom: 0 !important;
  color: var(--ns-heading) !important;
  letter-spacing: -0.02em !important;
}

.main-caption {
  font-family: var(--font-body) !important;
  color: var(--ns-text-secondary) !important;
  margin-top: -8px !important;
  margin-bottom: 24px !important;
  font-style: italic !important;
  font-size: 1rem !important;
}

/* ===== Sidebar ===== */
[data-testid="stSidebar"] {
  background: #ede6d8 !important;
  border-right: 1px solid var(--ns-border) !important;
}

[data-testid="stSidebar"] .stMarkdown h3 {
  font-family: var(--font-display) !important;
  font-size: 1.15rem !important;
  font-weight: 700 !important;
  color: var(--ns-heading) !important;
}

[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] .stCaption {
  color: var(--ns-text-secondary) !important;
}

/* ===== Sidebar Nav (segmented control) ===== */
div[data-testid="stSidebar"] .segmented-row {
  display: flex;
  background: #e0d8c8;
  border-radius: 10px;
  padding: 3px;
  margin-bottom: 16px;
  gap: 2px;
}
div[data-testid="stSidebar"] .segmented-row .stButton {
  flex: 1;
}
div[data-testid="stSidebar"] .segmented-row button {
  width: 100% !important;
  padding: 8px 4px !important;
  border-radius: 8px !important;
  border: none !important;
  background: transparent !important;
  color: #6b6050 !important;
  font-size: 0.82rem !important;
  font-weight: 500 !important;
  cursor: pointer !important;
  transition: all 0.2s !important;
  box-shadow: none !important;
  min-height: unset !important;
  line-height: 1.4 !important;
  font-family: var(--font-ui) !important;
}
div[data-testid="stSidebar"] .segmented-row button:hover {
  color: var(--ns-heading) !important;
  background: rgba(255,255,255,0.5) !important;
}
div[data-testid="stSidebar"] .segmented-row button[kind="primary"] {
  background: #fff !important;
  color: var(--ns-accent) !important;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08) !important;
  font-weight: 600 !important;
}
div[data-testid="stSidebar"] .segmented-row button[kind="primary"]:hover {
  background: #fff !important;
}

/* Sidebar slider labels */
div[data-testid="stSidebar"] .stSlider label {
  font-size: 0.8rem !important;
  color: var(--ns-text-secondary) !important;
  font-family: var(--font-ui) !important;
  font-weight: 500 !important;
}

/* Sidebar section titles */
.sidebar-section-title {
  font-family: var(--font-ui) !important;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ns-text-muted);
  margin: 16px 0 4px 0;
  padding: 0 4px;
}

/* Sidebar status card */
.sidebar-status {
  background: #fff;
  border: 1px solid var(--ns-border);
  border-radius: 10px;
  padding: 10px 14px;
  margin: 8px 0;
  font-size: 0.76rem;
  line-height: 1.6;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.sidebar-status .label { color: var(--ns-text-muted); }
.sidebar-status .value { color: var(--ns-heading); font-weight: 500; }
.sidebar-status .dot {
  display: inline-block; width: 6px; height: 6px;
  border-radius: 50%; margin-right: 6px;
}
.sidebar-status .dot.green { background: var(--ns-success); }
.sidebar-status .dot.blue { background: var(--ns-info); }
.sidebar-status .dot.orange { background: var(--ns-warning); }
.sidebar-status .dot.purple { background: #8b7ec8; }

/* ===== Buttons ===== */
.stButton > button {
  font-family: var(--font-ui) !important;
  font-size: 0.9rem !important;
  padding: 10px 28px !important;
  border-radius: var(--ns-radius-sm) !important;
  font-weight: 600 !important;
  transition: all 0.2s !important;
  letter-spacing: 0.01em !important;
  border: 1px solid transparent !important;
}

/* Primary button */
.stButton > button[kind="primary"] {
  background: var(--ns-accent) !important;
  color: #fff !important;
  border-color: var(--ns-accent) !important;
  box-shadow: 0 2px 8px rgba(139, 105, 20, 0.2) !important;
}
.stButton > button[kind="primary"]:hover {
  background: var(--ns-accent-dim) !important;
  border-color: var(--ns-accent-dim) !important;
  box-shadow: 0 4px 16px rgba(139, 105, 20, 0.3) !important;
  transform: translateY(-1px);
}

/* Secondary button */
.stButton > button[kind="secondary"] {
  background: #fff !important;
  color: var(--ns-accent) !important;
  border-color: var(--ns-accent) !important;
}
.stButton > button[kind="secondary"]:hover {
  background: var(--ns-accent-glow) !important;
}

/* ===== Inputs ===== */
.stTextInput input, .stTextArea textarea, .stSelectbox select,
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
  font-family: var(--font-ui) !important;
  border-radius: var(--ns-radius-sm) !important;
  border: 1px solid var(--ns-border) !important;
  color: var(--ns-text) !important;
  background: #fff !important;
  transition: all 0.2s !important;
}

.stTextInput input:focus, .stTextArea textarea:focus,
[data-testid="stTextInput"] input:focus {
  border-color: var(--ns-accent) !important;
  box-shadow: 0 0 0 3px var(--ns-accent-glow) !important;
}

.stTextArea textarea {
  font-family: var(--font-body) !important;
  font-size: 1rem !important;
  line-height: 1.7 !important;
}

/* ===== Dividers ===== */
hr {
  border: none !important;
  border-top: 1px solid var(--ns-border) !important;
  margin: 10px 0 !important;
}

/* ===== Setting Section Cards ===== */
.setting-section {
  border: 1px solid var(--ns-border) !important;
  border-radius: var(--ns-radius) !important;
  padding: 18px 24px !important;
  margin: 14px 0 !important;
  background: #fff !important;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;
  transition: box-shadow 0.2s !important;
}
.setting-section:hover {
  box-shadow: 0 2px 12px rgba(0,0,0,0.06) !important;
}
.setting-section h4 {
  font-family: var(--font-display) !important;
  margin-top: 0 !important;
  color: var(--ns-heading) !important;
  font-weight: 600 !important;
}

/* ===== Metrics (stats display) ===== */
[data-testid="stMetric"] {
  background: #fff;
  border: 1px solid var(--ns-border);
  border-radius: var(--ns-radius);
  padding: 16px 14px;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  transition: all 0.2s;
}
[data-testid="stMetric"]:hover {
  border-color: var(--ns-accent);
  box-shadow: 0 2px 12px var(--ns-accent-glow);
}
[data-testid="stMetric"] label {
  font-family: var(--font-ui) !important;
  font-size: 0.65rem !important;
  font-weight: 600 !important;
  color: var(--ns-text-muted) !important;
  text-transform: uppercase !important;
  letter-spacing: 0.06em !important;
}
[data-testid="stMetric"] [data-testid="stMetricValue"] {
  font-family: var(--font-display) !important;
  font-size: 1.8rem !important;
  font-weight: 700 !important;
  color: var(--ns-accent) !important;
}

/* ===== Tabs ===== */
.stTabs [data-baseweb="tab"] {
  font-family: var(--font-ui) !important;
  font-size: 0.85rem !important;
  font-weight: 500 !important;
  color: var(--ns-text-muted) !important;
  transition: all 0.2s !important;
}
.stTabs [data-baseweb="tab"]:hover {
  color: var(--ns-text) !important;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
  color: var(--ns-accent) !important;
  font-weight: 600 !important;
}
.stTabs [data-baseweb="tab-highlight"] {
  background-color: var(--ns-accent) !important;
}

/* ===== Expander ===== */
.streamlit-expanderHeader {
  font-family: var(--font-ui) !important;
  font-weight: 500 !important;
  color: var(--ns-text) !important;
}

/* ===== Select / Radio ===== */
.stRadio [data-baseweb="radio"] label,
.stSelectbox label {
  font-family: var(--font-ui) !important;
}

/* Radio accent color */
.stRadio [data-baseweb="radio"] [aria-checked="true"] {
  background-color: var(--ns-accent) !important;
}

/* ===== Containers with border ===== */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: var(--ns-border) !important;
  border-radius: var(--ns-radius) !important;
}

/* ===== Info/Warning/Success/Error boxes ===== */
.stAlert {
  border-radius: var(--ns-radius-sm) !important;
  font-family: var(--font-ui) !important;
}

/* ===== Checkbox ===== */
.stCheckbox [data-baseweb="checkbox"] [aria-checked="true"] {
  background-color: var(--ns-accent) !important;
}

/* ===== Slider ===== */
.stSlider [data-baseweb="slider"] [role="slider"] {
  background-color: var(--ns-accent) !important;
}
.stSlider [data-baseweb="slider"] div[style*="background"] {
  background-color: var(--ns-accent) !important;
}

/* ===== Progress ===== */
.stProgress > div > div {
  background: linear-gradient(90deg, var(--ns-accent-dim), var(--ns-accent)) !important;
}

/* ===== Code blocks ===== */
code {
  font-family: var(--font-mono) !important;
  background: #f4efe4 !important;
  padding: 2px 6px !important;
  border-radius: 3px !important;
  color: var(--ns-accent-dim) !important;
  font-size: 0.85em !important;
}

pre {
  background: #f4efe4 !important;
  border: 1px solid var(--ns-border) !important;
  border-radius: var(--ns-radius-sm) !important;
  font-family: var(--font-mono) !important;
}

/* ===== Markdown in expanders ===== */
.streamlit-expanderContent p {
  font-family: var(--font-ui) !important;
  line-height: 1.6 !important;
}

/* ===== Multiselect chips ===== */
[data-baseweb="tag"] {
  background: var(--ns-accent-glow) !important;
  border: 1px solid rgba(139, 105, 20, 0.2) !important;
  border-radius: 12px !important;
  font-family: var(--font-ui) !important;
  font-size: 0.75rem !important;
  color: var(--ns-accent) !important;
}

/* ===== Streamlit hamburger menu ===== */
[data-testid="stMainMenu"] { display: none; }

/* ===== Deploy button ===== */
[data-testid="stDeployButton"] { display: none; }
</style>
"""


# ============================================================
#  侧边栏导航
# ============================================================
def render_sidebar_nav():
    with st.sidebar:
        st.markdown("### 📚 科研综述系统")

        # 当前配置状态卡片（两页通用）
        s = st.session_state.settings
        _src_labels = {"arxiv": "arXiv", "semantic_scholar": "S2", "pubmed": "PubMed", "dblp": "DBLP"}
        source_names = s.get("search_sources", ["arxiv", "semantic_scholar"])
        _src_display = ", ".join(_src_labels.get(x, x) for x in source_names)
        _emb_short = s.get("embedding_model", "?").split("/")[-1][:18]
        _rerank_short = s.get("reranker_model", "?").split("/")[-1][:20]
        output_short = Path(s.get("output_dir", "output/")).name
        st.markdown(f"""
        <div class="sidebar-status">
          <div><span class="dot blue"></span><span class="label">检索源</span> <span class="value">{_src_display}</span></div>
          <div style="margin-top:4px"><span class="dot green"></span><span class="label">Embedding</span> <span class="value">{_emb_short}</span></div>
          <div style="margin-top:2px"><span class="dot orange"></span><span class="label">Reranker</span> <span class="value">{_rerank_short}</span></div>
          <div style="margin-top:4px"><span class="dot purple"></span><span class="label">输出</span> <span class="value">{output_short}/</span></div>
        </div>
        """, unsafe_allow_html=True)

        # 页面专属侧边栏内容
        if st.session_state.page == "settings":
            st.markdown('<p class="sidebar-section-title">📋 配置区块</p>', unsafe_allow_html=True)
            st.caption("🤖 LLM 配置  ·  🔍 检索参数  ·  🧩 本地模型  ·  💾 输出配置")
        # generate 页的侧边栏在 render_generate_page 中渲染


def render_sidebar_bottom_nav():
    """侧边栏底部页面切换"""
    with st.sidebar:
        st.divider()
        if st.session_state.page == "generate":
            if st.button("⚙️ 设置", key="bottom_nav_settings", help="系统设置"):
                st.session_state.page = "settings"
                st.rerun()
        else:
            if st.button("📝 生成", key="bottom_nav_generate", help="综述生成"):
                st.session_state.page = "generate"
                st.rerun()


# ============================================================
#  设置页面
# ============================================================
def render_settings_page():
    st.markdown('<p class="main-header">⚙️ 系统设置</p>', unsafe_allow_html=True)
    st.caption("配置 LLM、检索源、输出路径等参数，设置将保存到本地文件。")

    s = st.session_state.settings

    # ---- LLM 配置 ----
    st.markdown('<div class="setting-section">', unsafe_allow_html=True)
    st.subheader("🤖 LLM 配置")

    # ===== 🧠 Pro 模型 =====
    st.markdown("##### 🧠 Pro 模型（深度推理）")
    _llm_providers = {
        "DeepSeek": ("https://api.deepseek.com", ["deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"]),
        "OpenAI": ("https://api.openai.com/v1", ["gpt-4o", "gpt-4-turbo", "gpt-4o-mini", "o3-mini"]),
        "Ollama (本地)": ("http://localhost:11434/v1", ["qwen2.5:7b", "llama3:8b", "mistral:7b", "gemma3:12b"]),
    }

    col1, col2 = st.columns(2)
    with col1:
        _pro_url = s.get("llm_base_url", "")
        _pro_idx = 0
        for i, (label, (url, _)) in enumerate(_llm_providers.items()):
            if url in _pro_url:
                _pro_idx = i
                break
        else:
            _pro_idx = 3  # 自定义
        _pro_preset = st.selectbox(
            "Pro 服务商",
            options=list(_llm_providers.keys()) + ["自定义"],
            index=_pro_idx,
            key="pro_provider",
        )
        if _pro_preset in _llm_providers:
            s["llm_base_url"] = _llm_providers[_pro_preset][0]
        else:
            s["llm_base_url"] = st.text_input(
                "Pro Base URL", value=s.get("llm_base_url", ""),
                placeholder="https://api.example.com/v1", key="pro_base_url_custom",
            )

    with col2:
        _pro_cur_provider = _pro_preset if _pro_preset in _llm_providers else None
        _pro_presets = list(_llm_providers.get(_pro_cur_provider, [None, []])[1]) if _pro_cur_provider else []
        _cur_pro_model = s.get("llm_model", "")
        if _cur_pro_model and _cur_pro_model not in _pro_presets:
            _pro_presets.insert(0, _cur_pro_model)
        _pro_presets.append("__custom__")
        _pro_model_idx = _pro_presets.index(_cur_pro_model) if _cur_pro_model in _pro_presets else 0
        _pro_chosen = st.selectbox(
            "Pro 模型名称",
            options=_pro_presets,
            index=_pro_model_idx,
            format_func=lambda x: "✏️ 自定义..." if x == "__custom__" else x,
            key="pro_model_preset",
        )
        if _pro_chosen == "__custom__":
            s["llm_model"] = st.text_input(
                "Pro 自定义模型名", value=_cur_pro_model,
                placeholder="输入模型名称...", key="pro_model_custom_input",
            )
        else:
            s["llm_model"] = _pro_chosen

    _api_key_set = bool(s.get("llm_api_key", ""))
    s["llm_api_key"] = st.text_input(
        "Pro API Key",
        value=s.get("llm_api_key", ""),
        type="password", placeholder="sk-...",
        help="留空则使用 .env 中配置的 API Key",
    )
    if _api_key_set:
        st.caption("✅ 已配置")

    st.divider()

    # ===== ⚡ Flash 模型 =====
    st.markdown("##### ⚡ Flash 模型（快速任务）")
    _flash_providers = {
        "DeepSeek": ("https://api.deepseek.com", ["deepseek-v4-flash", "deepseek-chat"]),
        "OpenAI": ("https://api.openai.com/v1", ["gpt-4o-mini", "gpt-3.5-turbo"]),
        "Ollama (本地)": ("http://localhost:11434/v1", ["qwen2.5:3b", "llama3.2:3b"]),
    }
    col1f, col2f = st.columns(2)
    with col1f:
        _flash_url = s.get("flash_base_url", "")
        _flash_idx = 0
        for i, (label, (url, _)) in enumerate(_flash_providers.items()):
            if url in _flash_url:
                _flash_idx = i
                break
        else:
            _flash_idx = 3
        _flash_preset = st.selectbox(
            "Flash 服务商",
            options=list(_flash_providers.keys()) + ["自定义"],
            index=_flash_idx,
            key="flash_provider",
        )
        if _flash_preset in _flash_providers:
            s["flash_base_url"] = _flash_providers[_flash_preset][0]
        else:
            s["flash_base_url"] = st.text_input(
                "Flash Base URL", value=s.get("flash_base_url", ""),
                placeholder="https://api.example.com/v1", key="flash_base_url_custom",
            )

    with col2f:
        _flash_cur_provider = _flash_preset if _flash_preset in _flash_providers else None
        _flash_presets = list(_flash_providers.get(_flash_cur_provider, [None, []])[1]) if _flash_cur_provider else []
        _cur_flash_model = s.get("flash_model", "deepseek-v4-flash")
        if _cur_flash_model and _cur_flash_model not in _flash_presets:
            _flash_presets.insert(0, _cur_flash_model)
        _flash_presets.append("__custom__")
        _flash_model_idx = _flash_presets.index(_cur_flash_model) if _cur_flash_model in _flash_presets else 0
        _flash_chosen = st.selectbox(
            "Flash 模型名称",
            options=_flash_presets,
            index=_flash_model_idx,
            format_func=lambda x: "✏️ 自定义..." if x == "__custom__" else x,
            key="flash_model_preset",
        )
        if _flash_chosen == "__custom__":
            s["flash_model"] = st.text_input(
                "Flash 自定义模型名", value=_cur_flash_model,
                placeholder="输入模型名称...", key="flash_model_custom_input",
            )
        else:
            s["flash_model"] = _flash_chosen

    s["flash_api_key"] = st.text_input(
        "Flash API Key",
        value=s.get("flash_api_key", ""),
        type="password", placeholder="sk-...",
        help="留空则复用 Pro API Key",
    )

    # 分阶段模型选择
    with st.expander("⚡ 各阶段模型分配", expanded=False):
        stage_labels = {
            "keyword_extraction": "🔑 关键词提取",
            "relevance_scoring": "📊 相关性评分",
            "structured_extraction": "📝 结构化抽取",
            "timeline_analysis": "📅 时间线分析",
            "topic_clustering": "🧩 主题聚类",
            "conflict_detection": "⚔️ 冲突检测",
            "chapter_planning": "📋 章节规划",
            "review_writing": "✍️ 综述撰写",
            "citation_checking": "✅ 引文校验",
            "polishing": "✨ 综述润色",
        }
        sm = s.get("stage_models", {})
        for stage_key, stage_label in stage_labels.items():
            cur = sm.get(stage_key, "flash")
            sm[stage_key] = st.radio(
                stage_label,
                options=["flash", "pro"],
                index=0 if cur == "flash" else 1,
                format_func=lambda x: "⚡ Flash（快速）" if x == "flash" else "🧠 Pro（深度）",
                key=f"stage_{stage_key}",
                horizontal=True,
            )
        s["stage_models"] = sm
    st.markdown('</div>', unsafe_allow_html=True)

    # ---- 检索参数 ----
    st.markdown('<div class="setting-section">', unsafe_allow_html=True)
    st.subheader("🔍 检索参数")

    col1, col2, col3 = st.columns(3)
    with col1:
        s["max_rounds"] = st.number_input("最大检索轮数", min_value=1, max_value=5,
                                          value=s.get("max_rounds", 1))
    with col2:
        s["papers_per_round"] = st.number_input("每轮检索候选数", min_value=10, max_value=100,
                                                value=s.get("papers_per_round", 30), step=5)
    with col3:
        s["final_papers"] = st.number_input("最终使用文献数", min_value=5, max_value=50,
                                            value=s.get("final_papers", 10), step=5)

    from src.retrieval.sources import SOURCE_REGISTRY, SOURCE_DESCRIPTIONS
    source_names = list(SOURCE_REGISTRY.keys())
    source_labels = {
        "arxiv": "arXiv",
        "semantic_scholar": "Semantic Scholar",
        "pubmed": "PubMed",
        "dblp": "DBLP",
    }

    # 初始化 widget 状态（确保永不为空——必须在 widget 渲染前修正）
    _ss_key = "settings_search_sources"
    _cur_ss_val = st.session_state.get(_ss_key)
    if _cur_ss_val is None:
        st.session_state[_ss_key] = s.get("search_sources", ["arxiv", "semantic_scholar"])
    elif not _cur_ss_val:
        # 上一轮被清空了，在 widget 渲染前恢复
        st.session_state[_ss_key] = s.get("search_sources", ["arxiv", "semantic_scholar"])

    # 渲染 multiselect（显式 key，format_func 只用短标签避免 chips 渲染异常）
    selected = st.multiselect(
        "检索源（按优先级排序）",
        options=source_names,
        key=_ss_key,
        format_func=lambda x: source_labels.get(x, x),
    )
    s["search_sources"] = selected
    if not s["search_sources"]:
        st.warning("⚠️ 请至少选择一个检索源，已自动恢复为默认")
        s["search_sources"] = ["arxiv"]
        # 不在此处修改 st.session_state[_ss_key]（widget 渲染后禁止修改）
        # 下次渲染时 pre-widget 检查会自动恢复
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # ---- 本地模型配置 ----
    st.markdown('<div class="setting-section">', unsafe_allow_html=True)
    st.subheader("🧩 本地模型配置")

    col_e1, col_e2 = st.columns(2)
    with col_e1:
        emb_presets = {
            "BAAI/bge-small-zh-v1.5": "BGE Small 中文 (~92MB)",
            "BAAI/bge-large-zh-v1.5": "BGE Large 中文 (~650MB)",
            "BAAI/bge-small-en-v1.5": "BGE Small 英文 (~130MB)",
            "BAAI/bge-micro-v2": "BGE Micro 超轻量 (~17MB)",
            "sentence-transformers/all-MiniLM-L6-v2": "MiniLM 英文 (~80MB)",
            "intfloat/multilingual-e5-small": "E5 Small 多语言 (~120MB)",
        }
        _emb_key = "embedding_model_select"
        if _emb_key not in st.session_state:
            st.session_state[_emb_key] = s.get("embedding_model", "BAAI/bge-small-zh-v1.5")
        _emb_options = list(emb_presets.keys())
        _cur_emb = st.session_state[_emb_key]
        _emb_idx = _emb_options.index(_cur_emb) if _cur_emb in _emb_options else 0
        s["embedding_model"] = st.selectbox(
            "Embedding 向量模型",
            options=_emb_options,
            index=_emb_idx,
            key=_emb_key,
            format_func=lambda x: emb_presets.get(x, x),
            help="用于向量语义检索，4080S 本地运行",
        )
    with col_e2:
        rerank_presets = {
            "BAAI/bge-reranker-v2-m3": "BGE Reranker V2 M3 推荐 (~2.2GB)",
            "BAAI/bge-reranker-base": "BGE Reranker Base (~440MB)",
            "BAAI/bge-reranker-v2-minicpm-layerwise": "BGE Reranker MiniCPM 轻量 (~120MB)",
            "cross-encoder/ms-marco-MiniLM-L-4-v2": "MiniLM 超轻量 (~25MB)",
        }
        _rerank_key = "reranker_model_select"
        if _rerank_key not in st.session_state:
            st.session_state[_rerank_key] = s.get("reranker_model", "BAAI/bge-reranker-v2-m3")
        _rerank_options = list(rerank_presets.keys())
        _cur_rerank = st.session_state[_rerank_key]
        _rerank_idx = _rerank_options.index(_cur_rerank) if _cur_rerank in _rerank_options else 0
        s["reranker_model"] = st.selectbox(
            "CrossEncoder 重排序模型",
            options=_rerank_options,
            index=_rerank_idx,
            key=_rerank_key,
            format_func=lambda x: rerank_presets.get(x, x),
            help="用于 BGE 精细重排序，4080S 本地运行",
        )

    # 流程模型映射表（全流程详细说明 + 实际使用的模型 + 预计耗时）
    with st.expander("📋 各流程使用的模型", expanded=False):
        _emb = s.get('embedding_model', '?')
        _rerank = s.get('reranker_model', '?')
        _sm = s.get('stage_models', {})
        def _m(stage_key):
            """返回阶段对应的模型标签"""
            choice = _sm.get(stage_key, "flash")
            return "⚡ Flash" if choice == "flash" else "🧠 Pro"
        st.markdown(f"""
| 流程步骤 | 使用的模型 | 运行位置 | ⏱ 预计耗时 |
|---------|----------|:--:|:--:|
| Jieba 分词 | jieba (算法) | 本地 CPU | <1s |
| 关键词提取与打分 | {_m("keyword_extraction")} | API 云端 | 3-8s |
| 多源学术检索 (arXiv/S2/PubMed/DBLP) | HTTP API | 网络 | 15-45s |
| PDF 全文下载与章节切分 | pypdf (算法) | 本地 CPU | 2-10s |
| BM25 关键词检索 | rank_bm25 (算法) | 本地 CPU | 1-3s |
| 向量语义检索 | `{_emb}` | 4080S GPU | 2-5s |
| RRF 多路融合排序 | RRF (算法) | 本地 CPU | <1s |
| CrossEncoder 精细重排序 | `{_rerank}` | 4080S GPU | 3-10s |
| 论文相关性评分 | {_m("relevance_scoring")} | API 云端 | 10-20s |
| 论文结构化信息抽取 | {_m("structured_extraction")} | API 云端 | 20-60s |
| 时间线/演进分析 | {_m("timeline_analysis")} | API 云端 | 5-15s |
| 研究主题聚类 | {_m("topic_clustering")} | API 云端 | 5-15s |
| 观点冲突检测 | {_m("conflict_detection")} | API 云端 | 5-15s |
| 综述章节规划 | {_m("chapter_planning")} | API 云端 | 5-15s |
| 综述正文撰写 | {_m("review_writing")} | API 云端 | 30-90s |
| 引文真实性校验 | {_m("citation_checking")} | API 云端 | 10-20s |
| 综述润色与格式化 | {_m("polishing")} | API 云端 | 10-20s |
| **合计** | | | **≈ 2-6 分钟** |
""")
    st.markdown('</div>', unsafe_allow_html=True)

    # ---- 输出配置 ----
    st.markdown('<div class="setting-section">', unsafe_allow_html=True)
    st.subheader("💾 输出配置")
    s["output_dir"] = st.text_input(
        "综述和日志保存目录",
        value=s.get("output_dir", str(PROJECT_ROOT / "output")),
        help="生成的综述 Markdown 和执行日志将保存在此目录",
    )
    st.markdown('</div>', unsafe_allow_html=True)

    # ---- 保存 ----
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("💾 保存设置", type="primary", use_container_width=True):
            save_settings(dict(s))
            st.session_state.settings = s
            st.success("✅ 设置已保存到 config/user_settings.json")
    with col2:
        if st.button("🔄 恢复默认", use_container_width=True):
            SETTINGS_FILE.unlink(missing_ok=True)
            st.session_state.settings = load_settings()
            st.success("已恢复默认设置")
            st.rerun()

    st.divider()
    st.caption(f"设置文件位置: `{SETTINGS_FILE}`")


# ============================================================
#  生成页面
# ============================================================
def render_generate_page():
    st.markdown('<p class="main-header">📚 科研文献智能综述系统</p>', unsafe_allow_html=True)
    st.markdown('<p class="main-caption">基于 LangGraph 多 Agent 协作的自动文献综述生成平台</p>', unsafe_allow_html=True)

    s = st.session_state.settings
    source_names = s.get("search_sources", ["arxiv", "semantic_scholar"])

    # ---- 侧边栏快捷参数 ----
    with st.sidebar:
        st.markdown('<p class="sidebar-section-title">📐 检索参数</p>', unsafe_allow_html=True)
        max_rounds = st.slider("最大轮数", 1, 3, s.get("max_rounds", 1),
                               help="文献不足时自动补充检索的轮数上限")
        papers_per_round = st.slider("候选数/轮", 10, 100, s.get("papers_per_round", 30), 5,
                                     help="每轮从检索源获取的候选文献数")
        final_papers = st.slider("最终使用", 5, 50, s.get("final_papers", 10), 5,
                                 help="重排序后保留的高相关文献数")
        language = st.selectbox("综述语言", ["zh", "en"],
                                index=0 if s.get("language", "zh") == "zh" else 1,
                                format_func=lambda x: "🇨🇳 中文" if x == "zh" else "🇺🇸 English",
                                help="选择综述生成的语言")

    # ---- 生成状态初始化 ----
    if "generating" not in st.session_state:
        st.session_state.generating = False

    # ---- 输入区 ----
    with st.container(border=True):
        query = st.text_area(
            "🔍 研究主题",
            placeholder=(
                "请输入您想综述的研究主题，例如：\n"
                "• 扩散模型在医学图像分割中的最新进展\n"
                "• Transformer架构在NLP中的演进与变体\n"
                "• 联邦学习中的隐私保护技术综述"
            ),
            height=100,
            label_visibility="collapsed",
        )
        col_btn1, col_btn2, col_btn3 = st.columns([2, 1, 2])
        with col_btn2:
            _btn_disabled = (
                st.session_state.generating
                or not query
                or len(query.strip()) < 10
            )
            _btn_label = "⏳ 生成中..." if st.session_state.generating else "🚀 开始生成综述"
            generate_btn = st.button(
                _btn_label,
                type="primary",
                use_container_width=True,
                disabled=_btn_disabled,
            )

    # ---- 生成逻辑 ----
    if generate_btn and not st.session_state.generating:
        st.session_state.generating = True
        st.session_state.review_result = None
        st.rerun()

    if st.session_state.generating:
        result = run_generation(query, max_rounds, papers_per_round, final_papers, language, s)
        st.session_state.review_result = result
        st.session_state.generating = False
        st.rerun()

    # 展示已有结果
    _cached = st.session_state.get("review_result")
    if _cached:
        display_review_result(_cached)

    if not query and not _cached:
        st.info("👆 在上方输入研究主题，点击按钮开始生成综述")

    st.divider()
    st.caption(
        "⚠️ 本系统生成内容仅供参考，关键结论请查阅原始论文核实。"
        "引用标注为 [待核实] 的条目可能存在幻觉，请谨慎使用。"
    )


def _fix_reference_format(text: str) -> str:
    """修复参考文献格式：每个引用独立一行 + 移除 [待核实] 标记"""
    import re
    # 移除 [待核实] 标记
    text = re.sub(r'\s*\[待核实\]', '', text)
    # 每个 [N] 引用前换行（不在行首时）
    text = re.sub(r'(?<=[。.…])(\s*\[\d+\])', r'\n\1', text)
    # 数字序号引用 (1. 2. 等) 前确保换行
    text = re.sub(r'(?<=[。.])(\s*\d+\.\s+(?=[A-Z]))', r'\n\1', text)
    return text


def run_generation(query, max_rounds, papers_per_round, final_papers, language, s) -> dict | None:
    """执行综述生成流程，返回结果字典或 None"""
    from src.agents.supervisor import SupervisorAgent

    config = {
        "max_rounds": max_rounds,
        "papers_per_round": papers_per_round,
        "final_papers": final_papers,
        "search_sources": ",".join(s.get("search_sources", ["arxiv", "semantic_scholar"])),
        "llm_api_key": s.get("llm_api_key", ""),
        "llm_base_url": s.get("llm_base_url", ""),
        "llm_model": s.get("llm_model", ""),
        "flash_api_key": s.get("flash_api_key", ""),
        "flash_base_url": s.get("flash_base_url", ""),
        "flash_model": s.get("flash_model", "deepseek-v4-flash"),
        "stage_models": s.get("stage_models", {}),
        "language": language,
        "embedding_model": s.get("embedding_model", ""),
        "reranker_model": s.get("reranker_model", ""),
    }

    output_dir = Path(s.get("output_dir", PROJECT_ROOT / "output"))
    log_dir = output_dir / "logs"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    task_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"review_{task_id}.log"

    # 进度展示
    progress_bar = st.progress(0.0)
    status_col1, status_col2 = st.columns([1, 3])
    with status_col1:
        stage_badge = st.empty()
    with status_col2:
        status_text = st.empty()

    logs = []
    stage_icons = {
        "init": "🚀", "extracting_keywords": "🔑", "searching": "🔍",
        "ranking": "📊", "extracting": "📝", "analyzing": "🧠",
        "generating": "✍️", "done": "✅", "adjust_search_params": "🔄",
    }

    def _flush_log():
        log_file.write_text("\n".join(logs), encoding="utf-8")

    async def on_progress(stage, progress, message):
        progress_bar.progress(progress)
        pct = int(progress * 100)
        icon = stage_icons.get(stage, "⏳")
        stage_badge.markdown(f"### {icon} {pct}%")
        status_text.markdown(f"**{message}**")
        timestamp = datetime.now().strftime("%H:%M:%S")
        logs.append(f"[{timestamp}] {message}")
        if len(logs) % 5 == 0:
            _flush_log()

    try:
        supervisor = SupervisorAgent()
        result = asyncio.run(supervisor.generate_review(query, config, on_progress=on_progress))
    except Exception as e:
        st.error(f"生成失败: {e}")
        _flush_log()
        return None

    _flush_log()
    progress_bar.progress(1.0)
    with status_col1:
        stage_badge.markdown("### ✅ 100%")
    status_text.success("综述生成完毕！")

    # 保存综述（修复参考文献格式）
    final_review = result.get("final_review", "")
    if final_review:
        final_review = _fix_reference_format(final_review)
        result["final_review"] = final_review
        review_file = output_dir / f"review_{task_id}.md"
        review_file.write_text(final_review, encoding="utf-8")

    # 附加元信息
    result["task_id"] = task_id
    result["review_file"] = output_dir / f"review_{task_id}.md"
    result["log_file"] = log_file
    result["logs"] = logs
    return result


def display_review_result(result: dict):
    """展示综述生成结果（统计面板 + Tab 页）"""
    stats = result.get("statistics", {})
    final_review = result.get("final_review", "")
    review_file = result.get("review_file", "")
    log_file = result.get("log_file", "")
    logs = result.get("logs", [])
    task_id = result.get("task_id", "")

    st.divider()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("检索文献", stats.get("total_papers_retrieved", 0))
    c2.metric("最终使用", stats.get("final_papers_used", 0))
    c3.metric("检索轮数", stats.get("retrieval_rounds", 0))
    c4.metric("主题聚类", stats.get("topic_clusters", 0))
    c5.metric("综述字数", f"{stats.get('review_length_chars', 0):,}")
    st.info(f"💾 综述: `{review_file}` | 📋 日志: `{log_file}`")

    tab1, tab2, tab3, tab4 = st.tabs(["📄 综述全文", "📊 分析结果", "📚 文献列表", "📋 执行日志"])

    with tab1:
        if final_review:
            st.download_button(
                "📥 下载综述 (Markdown)", data=final_review,
                file_name=f"review_{task_id}.md", mime="text/markdown",
            )
            st.divider()
            st.markdown(final_review)
        else:
            st.warning("尚未生成综述内容")

    with tab2:
        st.subheader("主题聚类")
        for i, cluster in enumerate(result.get("topic_clusters", [])):
            with st.expander(f"**{cluster.get('cluster_name', f'Cluster {i+1}')}** "
                             f"({len(cluster.get('paper_ids', []))} 篇)"):
                st.write(cluster.get("description", ""))
                if cluster.get("key_themes"):
                    st.write("**关键主题:**", ", ".join(cluster["key_themes"]))
        if not result.get("topic_clusters"):
            st.info("未生成主题聚类")

        st.divider()
        st.subheader("观点冲突")
        for conflict in result.get("conflicts", []):
            st.markdown(f"- **{conflict.get('type', '')}**: {conflict.get('description', '')}")
        if not result.get("conflicts"):
            st.info("未发现明显观点冲突")

    with tab3:
        for paper in result.get("structured_papers", []):
            with st.expander(f"{paper.get('title', 'Untitled')[:100]} "
                             f"({paper.get('year', '')}) [{paper.get('relevance_level', '?')}]"):
                st.write(f"**作者:** {', '.join(paper.get('authors', [])[:5])}")
                st.write(f"**期刊:** {paper.get('journal', '')}")
                st.write(f"**相关性:** {paper.get('relevance_score', 0):.2f}")
                for f in paper.get("key_findings", [])[:3]:
                    st.write(f"  • {f}")
        if not result.get("structured_papers"):
            st.info("暂无文献数据")

    with tab4:
        st.subheader("执行日志")
        st.caption(f"完整日志: `{log_file}`")
        st.code("\n".join(logs), language="text")


# ============================================================
#  主入口
# ============================================================
def main():
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    init_session_state()
    render_sidebar_nav()

    if st.session_state.page == "settings":
        render_settings_page()
    else:
        render_generate_page()

    render_sidebar_bottom_nav()


if __name__ == "__main__":
    main()
