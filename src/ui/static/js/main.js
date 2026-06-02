/* ============================================================
   Noir Scholar — Application
   Multi-Agent Literature Review System
   ============================================================ */

// ============================================================
// Configuration
// ============================================================
const API_BASE = window.__API_BASE__ || '/api/review';
const POLL_INTERVAL = 2000; // ms between status polls

// ============================================================
// State
// ============================================================
const state = {
  page: 'generate',        // 'generate' | 'history' | 'settings'
  theme: 'dark',           // 'dark' | 'light'

  // Generation
  generating: false,
  currentTaskId: null,
  currentResult: null,
  taskPollTimer: null,

  // History (loaded from localStorage)
  taskHistory: [],

  // Settings
  settings: getDefaultSettings(),
};

// ============================================================
// Default Settings
// ============================================================
function getDefaultSettings() {
  return {
    llm_base_url: 'https://api.deepseek.com',
    llm_api_key: '',
    llm_model: 'deepseek-v4-pro',
    flash_base_url: 'https://api.deepseek.com',
    flash_model: 'deepseek-v4-flash',
    flash_api_key: '',
    stage_models: {
      keyword_extraction: 'flash',
      relevance_scoring: 'flash',
      structured_extraction: 'pro',
      timeline_analysis: 'pro',
      topic_clustering: 'pro',
      conflict_detection: 'pro',
      chapter_planning: 'flash',
      review_writing: 'pro',
      citation_checking: 'flash',
      polishing: 'flash',
    },
    max_rounds: 1,
    papers_per_round: 30,
    final_papers: 10,
    search_sources: ['arxiv', 'semantic_scholar'],
    embedding_model: 'BAAI/bge-small-zh-v1.5',
    reranker_model: 'BAAI/bge-reranker-v2-m3',
    output_dir: 'output',
  };
}

// ============================================================
// Persistence
// ============================================================
function loadState() {
  try {
    const saved = localStorage.getItem('noir-scholar-state');
    if (saved) {
      const parsed = JSON.parse(saved);
      state.taskHistory = parsed.taskHistory || [];
      state.settings = { ...getDefaultSettings(), ...(parsed.settings || {}) };
      state.theme = parsed.theme || 'dark';
    }
  } catch (e) { /* ignore */ }
}

function saveState() {
  try {
    localStorage.setItem('noir-scholar-state', JSON.stringify({
      taskHistory: state.taskHistory.slice(0, 50), // keep last 50
      settings: state.settings,
      theme: state.theme,
    }));
  } catch (e) { /* ignore */ }
}

// ============================================================
// API Client
// ============================================================
const api = {
  async createTask(query, config) {
    const res = await fetch(`${API_BASE}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, config }),
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  },

  async getStatus(taskId) {
    const res = await fetch(`${API_BASE}/${taskId}/status`);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  },

  async getResult(taskId) {
    const res = await fetch(`${API_BASE}/${taskId}/result`);
    if (res.status === 202) return null; // still running
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  },

  async getIntermediate(taskId) {
    const res = await fetch(`${API_BASE}/${taskId}/intermediate`);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  },

  async deleteTask(taskId) {
    const res = await fetch(`${API_BASE}/${taskId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  },
};

// ============================================================
// Router
// ============================================================
function navigate(page, data = null) {
  state.page = page;
  if (data) state._navData = data;
  render();
}

window.addEventListener('hashchange', () => {
  const hash = window.location.hash.replace('#', '') || 'generate';
  if (['generate', 'history', 'settings'].includes(hash)) {
    navigate(hash);
  }
});

// ============================================================
// Theme
// ============================================================
function applyTheme() {
  document.documentElement.setAttribute('data-theme', state.theme);
}

function toggleTheme() {
  state.theme = state.theme === 'dark' ? 'light' : 'dark';
  applyTheme();
  saveState();
}

// ============================================================
// Toast
// ============================================================
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const icons = { success: '✓', error: '✗', info: 'ℹ' };
  toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span> ${message}`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ============================================================
// Render
// ============================================================
function render() {
  applyTheme();

  const app = document.getElementById('app');
  const currentPage = state.page;

  app.innerHTML = `
    <div class="sidebar-overlay ${false ? 'visible' : ''}" id="sidebar-overlay"
         onclick="toggleMobileSidebar()"></div>
    <button class="mobile-menu-btn" onclick="toggleMobileSidebar()">☰</button>

    <aside class="sidebar" id="sidebar">
      <div class="sidebar-brand">
        <h1>Noir Scholar</h1>
        <div class="subtitle">Literature Review System</div>
      </div>

      <nav class="sidebar-nav">
        <button class="nav-item ${currentPage === 'generate' ? 'active' : ''}"
                onclick="navigate('generate')">
          <span class="icon">✧</span> <span>综述生成</span>
        </button>
        <button class="nav-item ${currentPage === 'history' ? 'active' : ''}"
                onclick="navigate('history')">
          <span class="icon">◷</span> <span>任务历史</span>
          ${state.taskHistory.length ? `<span class="badge">${state.taskHistory.length}</span>` : ''}
        </button>
        <button class="nav-item ${currentPage === 'settings' ? 'active' : ''}"
                onclick="navigate('settings')">
          <span class="icon">⚙</span> <span>系统设置</span>
        </button>
      </nav>

      ${renderSidebarStatus()}

      <div class="sidebar-footer">
        <button class="theme-toggle" onclick="toggleTheme()">
          <span>${state.theme === 'dark' ? '☽' : '☀'}</span>
          ${state.theme === 'dark' ? 'Dark' : 'Light'}
        </button>
        <span class="api-status checking" id="api-indicator">
          <span class="indicator"></span> API
        </span>
      </div>
    </aside>

    <main class="main-content" id="main-content">
      ${renderPage()}
    </main>

    <div class="toast-container" id="toast-container"></div>
  `;

  // Post-render actions
  if (currentPage === 'generate') bindGeneratePage();
  if (currentPage === 'history') bindHistoryPage();
  if (currentPage === 'settings') bindSettingsPage();

  checkApiStatus();
}

// ============================================================
// Sidebar Status
// ============================================================
function renderSidebarStatus() {
  const s = state.settings;
  const srcLabels = { arxiv: 'arXiv', semantic_scholar: 'S2', pubmed: 'PubMed', dblp: 'DBLP' };
  const srcDisplay = (s.search_sources || []).map(x => srcLabels[x] || x).join(', ');
  const embShort = (s.embedding_model || '?').split('/').pop().substring(0, 18);
  const rerankShort = (s.reranker_model || '?').split('/').pop().substring(0, 20);

  return `
    <div class="sidebar-status">
      <div class="status-row">
        <span class="dot blue"></span> 检索源: <strong>${srcDisplay}</strong>
      </div>
      <div class="status-row">
        <span class="dot green"></span> Embedding: <strong>${embShort}</strong>
      </div>
      <div class="status-row">
        <span class="dot amber"></span> Reranker: <strong>${rerankShort}</strong>
      </div>
      <div class="status-row">
        <span class="dot purple"></span> 输出: <strong>${s.output_dir || 'output'}/</strong>
      </div>
    </div>
  `;
}

// ============================================================
// Page Router
// ============================================================
function renderPage() {
  switch (state.page) {
    case 'generate': return renderGeneratePage();
    case 'history': return renderHistoryPage();
    case 'settings': return renderSettingsPage();
    default: return renderGeneratePage();
  }
}

// ============================================================
// Generate Page
// ============================================================
function renderGeneratePage() {
  const result = state.currentResult;
  const generating = state.generating;

  return `
    <div class="page active">
      <div class="page-header">
        <h2>文献综述生成</h2>
        <p class="caption">输入研究主题，AI 多智能体协作生成结构化文献综述</p>
      </div>

      ${!result && !generating ? renderQueryInput() : ''}
      ${generating ? renderPipeline() : ''}
      ${result ? renderResults(result) : ''}
      ${!result && !generating ? renderEmptyPrompt() : ''}

      <div style="margin-top:40px;padding-top:20px;border-top:1px solid var(--border);">
        <p style="font-size:0.75rem;color:var(--text-muted);text-align:center;">
          ⚠ 本系统生成内容仅供参考，关键结论请查阅原始论文核实。标记为 [待核实] 的引用可能存在幻觉。
        </p>
      </div>
    </div>
  `;
}

function renderQueryInput() {
  const s = state.settings;

  return `
    <div class="hero-input animate-in">
      <div class="query-label">🔍 研究主题</div>
      <textarea id="query-input" placeholder="请输入您想综述的研究主题，例如：
• 扩散模型在医学图像分割中的最新进展
• Transformer架构在NLP中的演进与变体
• 联邦学习中的隐私保护技术综述"
      ></textarea>

      <div class="query-params-row">
        <div class="quick-param">
          <span class="quick-param-label">最大轮数</span>
          <select id="qp-rounds" class="quick-select">
            ${[1,2,3].map(v => `<option value="${v}" ${v === s.max_rounds ? 'selected' : ''}>${v}</option>`).join('')}
          </select>
        </div>
        <div class="quick-param-divider"></div>
        <div class="quick-param">
          <span class="quick-param-label">候选数/轮</span>
          <select id="qp-papers" class="quick-select">
            ${[10,20,30,50,100].map(v => `<option value="${v}" ${v === s.papers_per_round ? 'selected' : ''}>${v}</option>`).join('')}
          </select>
        </div>
        <div class="quick-param-divider"></div>
        <div class="quick-param">
          <span class="quick-param-label">最终使用</span>
          <select id="qp-final" class="quick-select">
            ${[5,10,15,20,30].map(v => `<option value="${v}" ${v === s.final_papers ? 'selected' : ''}>${v}</option>`).join('')}
          </select>
        </div>
      </div>

      <div class="query-action-row">
        <button class="btn btn-primary btn-hero" id="btn-generate" onclick="startGeneration()">
          <span class="btn-hero-icon">✧</span>
          开始生成综述
        </button>
      </div>
    </div>
  `;
}

function renderEmptyPrompt() {
  return `
    <div class="empty-state">
      <div class="empty-icon">📚</div>
      <h3>开始您的文献探索之旅</h3>
      <p>在上方输入研究主题，AI 智能体将自动检索、分析并生成综述</p>
    </div>
  `;
}

// ============================================================
// Pipeline Visualization
// ============================================================
const PIPELINE_STAGES = [
  { key: 'extracting_keywords', icon: '🔑', label: '关键词\n提取' },
  { key: 'searching', icon: '🔍', label: '文献\n检索' },
  { key: 'ranking', icon: '📊', label: '排序\n筛选' },
  { key: 'extracting', icon: '📝', label: '结构化\n抽取' },
  { key: 'analyzing', icon: '🧠', label: '多维\n分析' },
  { key: 'generating', icon: '✍️', label: '综述\n生成' },
];

function renderPipeline() {
  const currentStage = state._pipelineStage || 'extracting_keywords';
  const progress = state._pipelineProgress || 0;
  const message = state._pipelineMessage || '正在初始化...';

  const stageOrder = PIPELINE_STAGES.map(s => s.key);
  const currentIdx = stageOrder.indexOf(currentStage);

  const stagesHtml = PIPELINE_STAGES.map((stage, i) => {
    let statusClass = '';
    if (i < currentIdx) statusClass = 'done';
    else if (i === currentIdx) statusClass = 'active';

    return `
      <div class="pipeline-stage ${statusClass}">
        <div class="pipeline-node ${statusClass}">
          <span class="pipeline-icon">${stage.icon}</span>
          <span class="pipeline-check">✓</span>
        </div>
        <div class="pipeline-label">${stage.label.replace('\n', '<br>')}</div>
      </div>
      ${i < PIPELINE_STAGES.length - 1 ? `
        <div class="pipeline-connector ${i < currentIdx ? 'done' : (i === currentIdx ? 'active' : '')}"></div>
      ` : ''}
    `;
  }).join('');

  return `
    <div class="animate-in">
      <div class="pipeline">${stagesHtml}</div>
      <div class="progress-bar">
        <div class="fill" style="width:${Math.round(progress * 100)}%"></div>
      </div>
      <div class="status-banner">
        <div class="stage-icon">
          ${currentStage === 'done' ? '✅' : '⏳'}
        </div>
        <div class="stage-info">
          <div class="stage-title">${getStageName(currentStage)}</div>
          <div class="stage-msg">${message}</div>
        </div>
        <div class="stage-pct">${Math.round(progress * 100)}%</div>
      </div>
      <div style="text-align:center;margin-top:12px;">
        <button class="btn btn-ghost btn-sm" onclick="cancelGeneration()">取消生成</button>
      </div>
    </div>
  `;
}

function getStageName(key) {
  const map = {
    init: '初始化',
    extracting_keywords: '关键词提取',
    searching: '文献检索',
    ranking: '排序与筛选',
    adjust_search_params: '调整检索参数',
    extracting: '结构化信息抽取',
    analyzing: '多维度分析',
    generating: '综述撰写与润色',
    done: '完成',
  };
  return map[key] || key;
}

// ============================================================
// Results Display
// ============================================================
function renderResults(result) {
  const stats = result.statistics || {};
  const taskId = result.task_id || '';
  const reviewFile = result.review_file || `review_${taskId}.md`;

  return `
    <div class="animate-in">
      <!-- Stats -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value">${stats.total_papers_retrieved || 0}</div>
          <div class="stat-label">检索文献</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${stats.final_papers_used || 0}</div>
          <div class="stat-label">最终使用</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${stats.retrieval_rounds || 0}</div>
          <div class="stat-label">检索轮数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${stats.topic_clusters || 0}</div>
          <div class="stat-label">主题聚类</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${(stats.review_length_chars || 0) >= 1000 ? ((stats.review_length_chars / 1000).toFixed(1) + 'k') : (stats.review_length_chars || 0)}</div>
          <div class="stat-label">综述字数</div>
        </div>
      </div>

      <!-- Download bar -->
      <div class="download-bar">
        <span class="file-info">📄 ${reviewFile}</span>
        <button class="btn btn-primary btn-sm" onclick="downloadReview('${taskId}')">📥 下载</button>
        <button class="btn btn-secondary btn-sm" onclick="navigate('generate')">🔄 新综述</button>
      </div>

      <!-- Tabs -->
      <div class="tabs" id="result-tabs">
        <button class="tab-btn active" data-tab="tab-review">📄 综述全文</button>
        <button class="tab-btn" data-tab="tab-analysis">📊 分析结果</button>
        <button class="tab-btn" data-tab="tab-papers">📚 文献列表</button>
        <button class="tab-btn" data-tab="tab-logs">📋 执行日志</button>
      </div>

      <!-- Tab: Review -->
      <div class="tab-panel active" id="tab-review">
        <div class="result-layout">
          <aside class="toc-floating" id="toc-container">
            <h4>📑 目录导航</h4>
            <div id="toc-links">正在解析...</div>
          </aside>
          <div class="review-content" id="review-body">
            ${renderMarkdown(result.final_review || '')}
          </div>
        </div>
      </div>

      <!-- Tab: Analysis -->
      <div class="tab-panel" id="tab-analysis">
        ${renderAnalysisTab(result)}
      </div>

      <!-- Tab: Papers -->
      <div class="tab-panel" id="tab-papers">
        ${renderPapersTab(result)}
      </div>

      <!-- Tab: Logs -->
      <div class="tab-panel" id="tab-logs">
        <h3 style="margin-bottom:16px;">📋 执行日志</h3>
        <div class="log-viewer">${(result.logs || []).map(l => `<div class="log-line">${escapeHtml(l)}</div>`).join('\n')}</div>
      </div>
    </div>
  `;
}

function renderAnalysisTab(result) {
  const clusters = result.topic_clusters || [];
  const conflicts = result.conflicts || [];

  return `
    <h3 style="margin-bottom:16px;">🧩 主题聚类</h3>
    ${clusters.length ? `
      <div class="clusters-grid">
        ${clusters.map((c, i) => `
          <div class="cluster-card">
            <div class="cluster-name">${c.cluster_name || `Cluster ${i + 1}`}</div>
            <div class="cluster-count">${(c.paper_ids || []).length} 篇文献</div>
            <div class="cluster-desc">${c.description || ''}</div>
            ${(c.key_themes || []).length ? `
              <div class="cluster-themes">
                ${c.key_themes.map(t => `<span class="theme-tag">${t}</span>`).join('')}
              </div>
            ` : ''}
          </div>
        `).join('')}
      </div>
    ` : '<p style="color:var(--text-muted)">未生成主题聚类</p>'}

    <h3 style="margin:32px 0 16px;">⚔️ 观点冲突</h3>
    ${conflicts.length ? conflicts.map(c => `
      <div class="conflict-item">
        <div class="conflict-type">${c.type || '观点分歧'}</div>
        <div class="conflict-desc">${c.description || ''}</div>
      </div>
    `).join('') : '<p style="color:var(--text-muted)">未发现明显观点冲突</p>'}
  `;
}

function renderPapersTab(result) {
  const papers = result.structured_papers || [];
  if (!papers.length) return '<p style="color:var(--text-muted)">暂无文献数据</p>';

  return papers.map((p, i) => `
    <div class="expander" id="paper-${i}">
      <div class="expander-header" onclick="toggleExpander('paper-${i}')">
        <span>
          <span style="color:var(--accent);margin-right:8px;">[${p.relevance_level || '?'}]</span>
          ${escapeHtml((p.title || 'Untitled').substring(0, 120))}
          <span style="color:var(--text-muted);margin-left:8px;font-size:0.75rem;">${p.year || ''}</span>
        </span>
        <span class="arrow">▾</span>
      </div>
      <div class="expander-body">
        <p><strong>作者:</strong> ${(p.authors || []).slice(0, 8).join(', ')}</p>
        <p><strong>期刊:</strong> ${p.journal || '未知'}</p>
        <p><strong>相关性:</strong> ${(p.relevance_score || 0).toFixed(2)}</p>
        ${(p.key_findings || []).length ? `
          <div style="margin-top:8px;">
            <strong>关键发现:</strong>
            <ul>${p.key_findings.slice(0, 5).map(f => `<li>${escapeHtml(f)}</li>`).join('')}</ul>
          </div>
        ` : ''}
        ${p.url ? `<p style="margin-top:8px;"><a href="${p.url}" target="_blank" rel="noopener">🔗 查看原文</a></p>` : ''}
      </div>
    </div>
  `).join('');
}

// ============================================================
// History Page
// ============================================================
function renderHistoryPage() {
  const tasks = state.taskHistory;

  return `
    <div class="page active">
      <div class="page-header">
        <h2>任务历史</h2>
        <p class="caption">过往综述生成任务记录</p>
      </div>

      ${tasks.length ? `
        <div class="task-list">
          ${tasks.slice().reverse().map(task => `
            <div class="task-item" onclick="viewHistoryTask('${task.taskId}')">
              <div class="task-status ${task.status}">
                ${task.status === 'completed' ? '✓' : task.status === 'running' ? '◷' : task.status === 'failed' ? '✗' : '○'}
              </div>
              <div class="task-info">
                <div class="task-query">${escapeHtml(task.query || '未知主题')}</div>
                <div class="task-meta">
                  ${task.taskId} · ${task.createdAt || ''}
                  ${task.stats ? ` · ${task.stats.final_papers_used || 0} 篇` : ''}
                </div>
              </div>
              <div class="task-actions">
                <button class="btn btn-ghost btn-sm"
                        onclick="event.stopPropagation();deleteHistoryTask('${task.taskId}')"
                        title="删除此任务">
                  🗑
                </button>
              </div>
            </div>
          `).join('')}
        </div>
      ` : `
        <div class="empty-state">
          <div class="empty-icon">◷</div>
          <h3>暂无历史任务</h3>
          <p>生成综述后，任务记录将在此显示</p>
        </div>
      `}
    </div>
  `;
}

function bindHistoryPage() {
  // Currently no dynamic elements needed beyond onclick handlers
}

function viewHistoryTask(taskId) {
  const task = state.taskHistory.find(t => t.taskId === taskId);
  if (task && task.result) {
    state.currentResult = task.result;
    state.currentResult.task_id = taskId;
    navigate('generate');
  } else {
    showToast('任务结果不可用', 'error');
  }
}

function deleteHistoryTask(taskId) {
  state.taskHistory = state.taskHistory.filter(t => t.taskId !== taskId);
  saveState();
  render();
  showToast('任务已删除', 'info');
}

// ============================================================
// Settings Page
// ============================================================
function renderSettingsPage() {
  const s = state.settings;

  return `
    <div class="page active">
      <div class="page-header">
        <h2>系统设置</h2>
        <p class="caption">配置 LLM、检索源与模型参数</p>
      </div>

      <!-- LLM Pro -->
      <div class="settings-section card">
        <h3>🧠 Pro 模型（深度推理）</h3>
        <div class="settings-grid">
          <div class="form-group">
            <label class="form-label">Base URL</label>
            <input class="input" id="set-pro-url" value="${escapeHtml(s.llm_base_url || '')}" placeholder="https://api.deepseek.com">
          </div>
          <div class="form-group">
            <label class="form-label">模型名称</label>
            <input class="input" id="set-pro-model" value="${escapeHtml(s.llm_model || '')}" placeholder="deepseek-v4-pro">
          </div>
        </div>
        <div class="form-group">
          <label class="form-label">API Key</label>
          <input class="input" id="set-pro-key" type="password" value="${escapeHtml(s.llm_api_key || '')}" placeholder="sk-...">
          ${s.llm_api_key ? '<p class="form-hint" style="color:var(--success)">✅ 已配置</p>' : ''}
        </div>
      </div>

      <!-- LLM Flash -->
      <div class="settings-section card">
        <h3>⚡ Flash 模型（快速任务）</h3>
        <div class="settings-grid">
          <div class="form-group">
            <label class="form-label">Base URL</label>
            <input class="input" id="set-flash-url" value="${escapeHtml(s.flash_base_url || '')}" placeholder="https://api.deepseek.com">
          </div>
          <div class="form-group">
            <label class="form-label">模型名称</label>
            <input class="input" id="set-flash-model" value="${escapeHtml(s.flash_model || '')}" placeholder="deepseek-v4-flash">
          </div>
        </div>
        <div class="form-group">
          <label class="form-label">API Key（留空则复用 Pro Key）</label>
          <input class="input" id="set-flash-key" type="password" value="${escapeHtml(s.flash_api_key || '')}" placeholder="sk-...">
        </div>

        <!-- Stage model assignment -->
        <details style="margin-top:16px;">
          <summary style="cursor:pointer;font-weight:600;font-size:0.9rem;color:var(--accent);">⚡ 各阶段模型分配</summary>
          <div style="margin-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:8px;" id="stage-models">
            ${[
              ['keyword_extraction', '🔑 关键词提取'],
              ['relevance_scoring', '📊 相关性评分'],
              ['structured_extraction', '📝 结构化抽取'],
              ['timeline_analysis', '📅 时间线分析'],
              ['topic_clustering', '🧩 主题聚类'],
              ['conflict_detection', '⚔️ 冲突检测'],
              ['chapter_planning', '📋 章节规划'],
              ['review_writing', '✍️ 综述撰写'],
              ['citation_checking', '✅ 引文校验'],
              ['polishing', '✨ 综述润色'],
            ].map(([key, label]) => `
              <div class="toggle-row">
                <span class="toggle-label">${label}</span>
                <label class="toggle">
                  <input type="checkbox" data-stage="${key}"
                         ${(s.stage_models || {})[key] === 'pro' ? 'checked' : ''}>
                  <span class="slider"></span>
                </label>
                <span style="font-size:0.7rem;color:var(--text-muted);min-width:36px;">
                  ${(s.stage_models || {})[key] === 'pro' ? 'Pro' : 'Flash'}
                </span>
              </div>
            `).join('')}
          </div>
        </details>
      </div>

      <!-- Retrieval -->
      <div class="settings-section card">
        <h3>🔍 检索参数</h3>
        <div class="settings-grid cols-3">
          <div class="form-group">
            <label class="form-label">最大检索轮数</label>
            <input class="input" id="set-max-rounds" type="number" min="1" max="5" value="${s.max_rounds || 1}">
          </div>
          <div class="form-group">
            <label class="form-label">每轮候选数</label>
            <input class="input" id="set-papers-per-round" type="number" min="10" max="100" step="5" value="${s.papers_per_round || 30}">
          </div>
          <div class="form-group">
            <label class="form-label">最终使用文献数</label>
            <input class="input" id="set-final-papers" type="number" min="5" max="50" step="5" value="${s.final_papers || 10}">
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">检索源（可多选）</label>
          <div style="display:flex;flex-wrap:wrap;gap:8px;" id="search-sources">
            ${[
              ['arxiv', 'arXiv'],
              ['semantic_scholar', 'Semantic Scholar'],
              ['pubmed', 'PubMed'],
              ['dblp', 'DBLP'],
            ].map(([key, label]) => `
              <label class="source-checkbox-label" style="border-color:${(s.search_sources||[]).includes(key)?'var(--accent)':'var(--border)'};background:${(s.search_sources||[]).includes(key)?'var(--accent-glow)':'var(--bg-input)'};">
                <input type="checkbox" value="${key}" ${(s.search_sources||[]).includes(key)?'checked':''}
                       onchange="toggleSearchSource('${key}', this.checked)">
                ${label}
              </label>
            `).join('')}
          </div>
        </div>
      </div>

      <!-- Local Models -->
      <div class="settings-section card">
        <h3>🧩 本地模型配置</h3>
        <div class="settings-grid">
          <div class="form-group">
            <label class="form-label">Embedding 向量模型</label>
            <select class="select" id="set-emb-model">
              ${[
                ['BAAI/bge-small-zh-v1.5', 'BGE Small 中文 (快)'],
                ['BAAI/bge-large-zh-v1.5', 'BGE Large 中文 (准)'],
                ['BAAI/bge-small-en-v1.5', 'BGE Small 英文'],
                ['sentence-transformers/all-MiniLM-L6-v2', 'MiniLM 英文 (轻量)'],
              ].map(([v, l]) => `<option value="${v}" ${s.embedding_model===v?'selected':''}>${l}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">CrossEncoder 重排序模型</label>
            <select class="select" id="set-rerank-model">
              ${[
                ['BAAI/bge-reranker-v2-m3', 'BGE Reranker V2 M3 (推荐)'],
                ['BAAI/bge-reranker-v2-minicpm-layerwise', 'BGE Reranker MiniCPM (轻量)'],
              ].map(([v, l]) => `<option value="${v}" ${s.reranker_model===v?'selected':''}>${l}</option>`).join('')}
            </select>
          </div>
        </div>
      </div>

      <!-- Output -->
      <div class="settings-section card">
        <h3>💾 输出配置</h3>
        <div class="form-group">
          <label class="form-label">综述和日志保存目录</label>
          <input class="input" id="set-output-dir" value="${escapeHtml(s.output_dir || 'output')}" placeholder="output">
        </div>
      </div>

      <!-- Sticky save bar -->
      <div class="settings-save-bar">
        <button class="btn btn-primary" onclick="saveSettings()">💾 保存设置</button>
        <button class="btn btn-secondary" onclick="resetSettings()">🔄 恢复默认</button>
      </div>
    </div>
  `;
}

function bindSettingsPage() {
  // Bind stage model toggles
  document.querySelectorAll('#stage-models input[type=checkbox]').forEach(cb => {
    cb.addEventListener('change', () => {
      const stage = cb.dataset.stage;
      state.settings.stage_models[stage] = cb.checked ? 'pro' : 'flash';
      // Update label
      const label = cb.closest('.toggle-row')?.querySelector('span:last-child');
      if (label) label.textContent = cb.checked ? 'Pro' : 'Flash';
    });
  });
}

function toggleSearchSource(key, checked) {
  if (checked) {
    if (!state.settings.search_sources.includes(key)) {
      state.settings.search_sources.push(key);
    }
  } else {
    state.settings.search_sources = state.settings.search_sources.filter(s => s !== key);
    if (!state.settings.search_sources.length) {
      state.settings.search_sources = ['arxiv'];
      showToast('至少需要选择一个检索源，已恢复为 arXiv', 'info');
      render();
      return;
    }
  }
}

// ============================================================
// Settings CRUD
// ============================================================
function saveSettings() {
  const s = state.settings;

  // Read input values
  const getVal = (id, fallback) => {
    const el = document.getElementById(id);
    return el ? el.value : fallback;
  };

  s.llm_base_url = getVal('set-pro-url', s.llm_base_url);
  s.llm_model = getVal('set-pro-model', s.llm_model);
  s.llm_api_key = getVal('set-pro-key', s.llm_api_key);
  s.flash_base_url = getVal('set-flash-url', s.flash_base_url);
  s.flash_model = getVal('set-flash-model', s.flash_model);
  s.flash_api_key = getVal('set-flash-key', s.flash_api_key);
  s.max_rounds = parseInt(getVal('set-max-rounds', s.max_rounds)) || 1;
  s.papers_per_round = parseInt(getVal('set-papers-per-round', s.papers_per_round)) || 30;
  s.final_papers = parseInt(getVal('set-final-papers', s.final_papers)) || 10;
  s.embedding_model = getVal('set-emb-model', s.embedding_model);
  s.reranker_model = getVal('set-rerank-model', s.reranker_model);
  s.output_dir = getVal('set-output-dir', s.output_dir);

  saveState();
  showToast('✅ 设置已保存', 'success');
  render();
}

function resetSettings() {
  state.settings = getDefaultSettings();
  saveState();
  render();
  showToast('已恢复默认设置', 'info');
}

// ============================================================
// Generation Logic
// ============================================================
async function startGeneration() {
  const queryEl = document.getElementById('query-input');
  const query = queryEl ? queryEl.value.trim() : '';

  if (!query || query.length < 10) {
    showToast('请输入至少 10 个字符的研究主题', 'error');
    return;
  }

  // Read quick params
  const qpRounds = document.getElementById('qp-rounds');
  const qpPapers = document.getElementById('qp-papers');
  const qpFinal = document.getElementById('qp-final');

  const config = {
    max_rounds: qpRounds ? parseInt(qpRounds.value) : state.settings.max_rounds,
    papers_per_round: qpPapers ? parseInt(qpPapers.value) : state.settings.papers_per_round,
    final_papers: qpFinal ? parseInt(qpFinal.value) : state.settings.final_papers,
    search_sources: (state.settings.search_sources || ['arxiv']).join(','),
    llm_api_key: state.settings.llm_api_key,
    llm_base_url: state.settings.llm_base_url,
    llm_model: state.settings.llm_model,
    flash_api_key: state.settings.flash_api_key,
    flash_base_url: state.settings.flash_base_url,
    flash_model: state.settings.flash_model,
    stage_models: state.settings.stage_models,
    embedding_model: state.settings.embedding_model,
    reranker_model: state.settings.reranker_model,
  };

  state.generating = true;
  state.currentResult = null;
  state._pipelineStage = 'init';
  state._pipelineProgress = 0;
  state._pipelineMessage = '正在创建任务...';
  render();

  try {
    // Create task via API
    const task = await api.createTask(query, config);
    state.currentTaskId = task.task_id;
    state._pipelineMessage = '任务已创建，开始执行...';

    // Add to history
    state.taskHistory.push({
      taskId: task.task_id,
      query: query,
      status: 'running',
      createdAt: new Date().toLocaleString('zh-CN'),
      result: null,
    });
    saveState();
    render();

    // Start polling
    pollTaskStatus(task.task_id);
  } catch (err) {
    state.generating = false;
    state.currentTaskId = null;
    render();
    showToast(`创建任务失败: ${err.message}`, 'error');
  }
}

function pollTaskStatus(taskId) {
  if (state.taskPollTimer) clearInterval(state.taskPollTimer);

  state.taskPollTimer = setInterval(async () => {
    try {
      const status = await api.getStatus(taskId);

      // Update pipeline stage
      state._pipelineStage = status.stage || 'extracting_keywords';
      state._pipelineProgress = status.progress || 0;
      state._pipelineMessage = status.message || '处理中...';

      // Update history entry
      const histEntry = state.taskHistory.find(t => t.taskId === taskId);
      if (histEntry) {
        histEntry.status = status.status;
      }

      render();

      // Check if done
      if (status.status === 'completed') {
        clearInterval(state.taskPollTimer);
        state.taskPollTimer = null;

        // Fetch full result
        const result = await api.getResult(taskId);
        if (result) {
          // Clean up reference format
          if (result.final_review) {
            result.final_review = fixReferenceFormat(result.final_review);
          }
          state.currentResult = result;
          state.currentResult.task_id = taskId;

          // Update history
          if (histEntry) {
            histEntry.status = 'completed';
            histEntry.result = result;
            histEntry.stats = result.statistics || {};
          }
        }

        state.generating = false;
        state._pipelineStage = 'done';
        state._pipelineProgress = 1.0;
        state._pipelineMessage = '✅ 综述生成完毕！';
        saveState();
        render();
        showToast('综述生成完成！', 'success');
      }

      if (status.status === 'failed') {
        clearInterval(state.taskPollTimer);
        state.taskPollTimer = null;
        state.generating = false;

        if (histEntry) histEntry.status = 'failed';

        saveState();
        render();
        showToast('生成失败，请查看日志', 'error');
      }

    } catch (err) {
      console.error('Poll error:', err);
      // Don't stop polling on transient errors
    }
  }, POLL_INTERVAL);
}

function cancelGeneration() {
  if (state.taskPollTimer) {
    clearInterval(state.taskPollTimer);
    state.taskPollTimer = null;
  }

  if (state.currentTaskId) {
    api.deleteTask(state.currentTaskId).catch(() => {});
    const histEntry = state.taskHistory.find(t => t.taskId === state.currentTaskId);
    if (histEntry) histEntry.status = 'cancelled';
  }

  state.generating = false;
  state.currentTaskId = null;
  state.currentResult = null;
  saveState();
  render();
  showToast('任务已取消', 'info');
}

// ============================================================
// Result actions
// ============================================================
function downloadReview(taskId) {
  const result = state.currentResult;
  if (!result || !result.final_review) {
    showToast('没有可下载的综述内容', 'error');
    return;
  }

  const blob = new Blob([result.final_review], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `review_${taskId || 'output'}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast('下载完成', 'success');
}

// ============================================================
// Helpers
// ============================================================
function toggleExpander(id) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('open');
}

function toggleMobileSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  if (sidebar) sidebar.classList.toggle('open');
  if (overlay) overlay.classList.toggle('visible');
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function fixReferenceFormat(text) {
  // Remove [待核实] markers
  text = text.replace(/\s*\[待核实\]/g, '');
  // Add line breaks before [N] references
  text = text.replace(/(?<=[。.…])(\s*\[\d+\])/g, '\n$1');
  // Fix numbered references
  text = text.replace(/(?<=[。.])(\s*\d+\.\s+(?=[A-Z]))/g, '\n$1');
  return text;
}

function renderMarkdown(md) {
  if (!md) return '<p style="color:var(--text-muted)">尚未生成综述内容</p>';

  // Simple markdown to HTML conversion
  let html = md;

  // Headers
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2 id="$1">$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1 id="$1">$1</h1>');

  // Bold and italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Horizontal rules
  html = html.replace(/^---$/gm, '<hr>');

  // Blockquotes
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

  // Unordered lists
  html = html.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

  // Ordered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

  // Paragraphs (double newlines)
  html = html.replace(/\n\n+/g, '</p><p>');
  html = '<p>' + html + '</p>';

  // Clean up empty paragraphs
  html = html.replace(/<p>\s*<\/p>/g, '');
  html = html.replace(/<p>\s*(<h[1-6])/g, '$1');
  html = html.replace(/(<\/h[1-6]>)\s*<\/p>/g, '$1');
  html = html.replace(/<p>\s*(<ul)/g, '$1');
  html = html.replace(/(<\/ul>)\s*<\/p>/g, '$1');
  html = html.replace(/<p>\s*(<blockquote)/g, '$1');
  html = html.replace(/(<\/blockquote>)\s*<\/p>/g, '$1');

  return html;
}

// ============================================================
// API Status Check
// ============================================================
async function checkApiStatus() {
  const indicator = document.getElementById('api-indicator');
  if (!indicator) return;

  indicator.className = 'api-status checking';
  try {
    // Try to reach a known endpoint
    const res = await fetch(`${API_BASE}/generate`, { method: 'OPTIONS' });
    indicator.className = 'api-status connected';
    indicator.innerHTML = '<span class="indicator"></span> API';
  } catch {
    // OPTIONS might not be supported, try the base
    try {
      const res = await fetch(API_BASE.replace(/\/api\/review$/, '/docs'));
      indicator.className = res.ok ? 'api-status connected' : 'api-status disconnected';
    } catch {
      indicator.className = 'api-status disconnected';
    }
    indicator.innerHTML = '<span class="indicator"></span> API';
  }
}

// ============================================================
// TOC Generation
// ============================================================
function generateTOC() {
  const reviewBody = document.getElementById('review-body');
  const tocLinks = document.getElementById('toc-links');
  if (!reviewBody || !tocLinks) return;

  const headings = reviewBody.querySelectorAll('h1, h2');
  if (!headings.length) {
    tocLinks.innerHTML = '<span style="color:var(--text-muted);font-size:0.8rem;">无章节标题</span>';
    return;
  }

  let html = '';
  headings.forEach((h, i) => {
    const level = h.tagName.toLowerCase();
    const text = h.textContent.trim();
    const id = h.id || `section-${i}`;
    h.id = id;
    html += `<a href="#${id}" class="toc-${level}" onclick="scrollToSection('${id}')">${text}</a>`;
  });
  tocLinks.innerHTML = html;
}

function scrollToSection(id) {
  const el = document.getElementById(id);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

// ============================================================
// Event Delegation for Dynamic Content
// ============================================================
document.addEventListener('click', (e) => {
  // Tab switching
  const tabBtn = e.target.closest('.tab-btn');
  if (tabBtn) {
    const tabId = tabBtn.dataset.tab;
    const tabsContainer = tabBtn.closest('.tabs');
    if (tabsContainer) {
      // Deactivate all tabs
      tabsContainer.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      tabBtn.classList.add('active');

      // Show corresponding panel
      const panelsContainer = tabsContainer.parentElement;
      panelsContainer.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      const panel = document.getElementById(tabId);
      if (panel) {
        panel.classList.add('active');
        // Generate TOC if switching to review tab
        if (tabId === 'tab-review') {
          setTimeout(generateTOC, 50);
        }
      }
    }
  }
});

// ============================================================
// Init
// ============================================================
function init() {
  loadState();
  applyTheme();

  // Restore hash-based routing
  const hash = window.location.hash.replace('#', '') || 'generate';
  if (['generate', 'history', 'settings'].includes(hash)) {
    state.page = hash;
  }

  render();

  // If we have a result rendered, generate TOC
  if (state.currentResult) {
    setTimeout(generateTOC, 100);
  }
}

// Boot
document.addEventListener('DOMContentLoaded', init);

// ============================================================
// Keyboard Shortcuts
// ============================================================
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    // Ctrl+Enter to start generation
    if (state.page === 'generate' && !state.generating && !state.currentResult) {
      e.preventDefault();
      startGeneration();
    }
  }
});
