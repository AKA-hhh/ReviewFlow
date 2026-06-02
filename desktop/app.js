// ============================================================
// Custom Source Modal
// ============================================================
var customSources = [];
var sourceTestPassed = false;

// Task history (persisted to localStorage)
var taskHistory = [];

function loadHistory() {
  if (typeof pywebview !== 'undefined') {
    pywebview.api.get_history().then(function(json) {
      taskHistory = JSON.parse(json);
      // 去重（防止文件损坏或重复保存导致相同 taskId 出现多次）
      var seen = {};
      taskHistory = taskHistory.filter(function(t) {
        if (!t.taskId || seen[t.taskId]) return false;
        seen[t.taskId] = true;
        return true;
      });
      saveHistory();
      renderHistorySidebar();
    }).catch(function() {
      // fallback to localStorage
      try {
        var saved = localStorage.getItem('noir-scholar-history');
        if (saved) taskHistory = JSON.parse(saved);
      } catch(e) { taskHistory = []; }
      renderHistorySidebar();
    });
  } else {
    try {
      var saved = localStorage.getItem('noir-scholar-history');
      if (saved) taskHistory = JSON.parse(saved);
    } catch(e) { taskHistory = []; }
    renderHistorySidebar();
  }
}

function saveHistory() {
  var data = JSON.stringify(taskHistory.slice(0, 20));
  // 持久化到文件（通过 Python 后端）
  if (typeof pywebview !== 'undefined') {
    pywebview.api.save_history(data).catch(function() {});
  }
  // 同时存 localStorage 作为备份
  try { localStorage.setItem('noir-scholar-history', data); } catch(e) {}
}

function addHistoryEntry(taskId, query, stats, resultData) {
  // Dedup by taskId
  taskHistory = taskHistory.filter(function(t) { return t.taskId !== taskId; });
  taskHistory.unshift({
    taskId: taskId,
    query: query,
    stats: { papers: stats.final_papers_used || 0, chars: stats.review_length_chars || 0 },
    date: new Date().toLocaleDateString('zh-CN'),
    result: resultData,
    liveLogs: liveLogEntries.slice(),  // 保存实时日志快照
  });
  // Sort by taskId descending (newest first)
  taskHistory.sort(function(a, b) { return (b.taskId || '').localeCompare(a.taskId || ''); });
  // Keep last 10 full results (trim older ones to summary only to save space)
  if (taskHistory.length > 10) {
    for (var i = 10; i < taskHistory.length; i++) { taskHistory[i].result = null; }
  }
  if (taskHistory.length > 20) taskHistory = taskHistory.slice(0, 20);
  saveHistory();
  renderHistorySidebar();
}

function renderHistorySidebar() {
  var container = document.getElementById('sidebarHistory');
  var listEl = document.getElementById('historyList');
  if (!taskHistory.length) {
    container.style.display = 'none';
    return;
  }
  container.style.display = 'block';
  // 确保新的在上面（按 taskId 时间戳降序）
  taskHistory.sort(function(a, b) {
    return (b.taskId || '').localeCompare(a.taskId || '');
  });
  var html = '';
  taskHistory.slice(0, 8).forEach(function(h) {
    html += '<div class="history-item' + (h.result ? ' has-result' : '') + '" title="' + esc(h.query) + '">';
    html += '<span onclick="viewHistory(\'' + h.taskId + '\')" style="flex:1;cursor:pointer;">';
    // 从 taskId 提取时间: rev_20260601_120722 → 12:07
    var timeTag = '';
    // taskId 格式: rev_YYYYMMDD_HHMMSS_xxx → 跳过日期，提取 HH:MM
    // taskId 格式: rev_YYYYMMDD_HHMMSS_xxx → 显示完整时间
    var m = (h.taskId || '').match(/_(\d{8})_(\d{2})(\d{2})(\d{2})/);
    if (m) timeTag = m[2] + ':' + m[3] + ':' + m[4];
    html += '<span style="line-height:1.3;">' + esc(h.query.substring(0, 40)) + (h.query.length > 40 ? '...' : '') + '</span>';
    html += '<span class="hi-date">' + timeTag + ' · ' + h.stats.papers + '篇</span>';
    html += '</span>';
    html += '<button class="hi-delete" onclick="event.stopPropagation();deleteHistory(\'' + h.taskId + '\')" title="删除">×</button>';
    html += '</div>';
  });
  listEl.innerHTML = html;
}

var pendingDeleteTaskId = null;

function deleteHistory(taskId) {
  pendingDeleteTaskId = taskId;
  document.getElementById('confirmModal').classList.add('visible');
  document.getElementById('confirmModalMsg').textContent = '确定要删除这条历史记录吗？此操作不可撤销。';
}

function confirmDelete() {
  if (!pendingDeleteTaskId) return;
  taskHistory = taskHistory.filter(function(t) { return t.taskId !== pendingDeleteTaskId; });
  saveHistory();
  renderHistorySidebar();
  showToast('已删除', 'info');
  pendingDeleteTaskId = null;
  document.getElementById('confirmModal').classList.remove('visible');
}

function cancelDelete() {
  pendingDeleteTaskId = null;
  document.getElementById('confirmModal').classList.remove('visible');
}

function viewHistory(taskId) {
  var entry = taskHistory.find(function(t) { return t.taskId === taskId; });
  if (!entry) { showToast('该记录已失效', 'info'); return; }
  if (!entry.result) { showToast('该记录详情已被清理（仅保留最近10条完整结果）', 'info'); return; }
  // Reset page state before displaying
  document.getElementById('pipelineBox').style.display = 'none';
  document.getElementById('liveLogArea').style.display = 'none';
  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('resultArea').style.display = 'none';
  // Display the stored result
  displayResult(entry.result, entry.liveLogs);
  showToast('已加载: ' + entry.query.substring(0, 30), 'info');
}

var API_PRESETS = {
  openalex: {
    name: 'OpenAlex', url: 'https://api.openalex.org',
    search_path: '/works', query_param: 'search',
    limit_param: 'per_page', results_path: 'results',
  },
  crossref: {
    name: 'Crossref', url: 'https://api.crossref.org',
    search_path: '/works', query_param: 'query.bibliographic',
    limit_param: 'rows', results_path: 'message.items',
  },
};

function onPresetSelect() {
  var preset = document.getElementById('modalPreset').value;
  if (!preset || !API_PRESETS[preset]) return;
  var p = API_PRESETS[preset];
  document.getElementById('modalSourceName').value = p.name;
  document.getElementById('modalSourceUrl').value = p.url;
  document.getElementById('modalSearchPath').value = p.search_path;
  document.getElementById('modalQueryParam').value = p.query_param;
  document.getElementById('modalLimitParam').value = p.limit_param;
  document.getElementById('modalResultsPath').value = p.results_path;
  document.getElementById('modalSourceKey').value = '';
}

function openAddSourceModal() {
  document.getElementById('addSourceModal').classList.add('visible');
  document.getElementById('modalPreset').value = '';
  document.getElementById('modalSourceName').value = '';
  document.getElementById('modalSourceUrl').value = '';
  document.getElementById('modalSearchPath').value = '/search';
  document.getElementById('modalQueryParam').value = 'q';
  document.getElementById('modalLimitParam').value = 'limit';
  document.getElementById('modalResultsPath').value = 'data';
  document.getElementById('modalSourceKey').value = '';
  document.getElementById('modalTestResult').className = 'modal-test-result';
  document.getElementById('modalTestResult').innerHTML = '';
  document.getElementById('modalAddBtn').disabled = true;
  document.getElementById('modalTestBtn').disabled = false;
  sourceTestPassed = false;
}

function closeAddSourceModal() {
  document.getElementById('addSourceModal').classList.remove('visible');
}

function testCustomSource() {
  var name = document.getElementById('modalSourceName').value.trim();
  var url = document.getElementById('modalSourceUrl').value.trim();
  var key = document.getElementById('modalSourceKey').value.trim();
  var searchPath = document.getElementById('modalSearchPath').value.trim() || '/search';
  var queryParam = document.getElementById('modalQueryParam').value.trim() || 'q';
  var limitParam = document.getElementById('modalLimitParam').value.trim() || 'limit';
  var resultsPath = document.getElementById('modalResultsPath').value.trim() || 'data';
  if (!name || !url) {
    showToast('请填写检索源名称和 URL', 'error');
    return;
  }
  var resultEl = document.getElementById('modalTestResult');
  resultEl.className = 'modal-test-result';
  resultEl.innerHTML = '⏳ 正在检测...';
  resultEl.style.display = 'block';
  document.getElementById('modalTestBtn').disabled = true;

  pywebview.api.test_custom_source(name, url, key, searchPath, queryParam, limitParam, resultsPath).then(function(json) {
    var r = JSON.parse(json);
    if (r.ok) {
      resultEl.className = 'modal-test-result success';
      var html = '✅ ' + r.message;
      if (r.samples && r.samples.length) {
        html += '<div class="sample">示例文献：<br>· ' + r.samples.join('<br>· ') + '</div>';
      }
      resultEl.innerHTML = html;
      document.getElementById('modalAddBtn').disabled = false;
      sourceTestPassed = true;
    } else {
      resultEl.className = 'modal-test-result error';
      resultEl.innerHTML = '❌ ' + r.message;
      document.getElementById('modalAddBtn').disabled = true;
      sourceTestPassed = false;
    }
    document.getElementById('modalTestBtn').disabled = false;
  });
}

function addCustomSource() {
  if (!sourceTestPassed) {
    showToast('请先通过检测再添加', 'error');
    return;
  }
  var name = document.getElementById('modalSourceName').value.trim();
  var url = document.getElementById('modalSourceUrl').value.trim();
  var key = document.getElementById('modalSourceKey').value.trim();
  var searchPath = document.getElementById('modalSearchPath').value.trim() || '/search';
  var queryParam = document.getElementById('modalQueryParam').value.trim() || 'q';
  var limitParam = document.getElementById('modalLimitParam').value.trim() || 'limit';
  var resultsPath = document.getElementById('modalResultsPath').value.trim() || 'data';

  pywebview.api.add_custom_source(name, url, key, searchPath, queryParam, limitParam, resultsPath).then(function(json) {
    var r = JSON.parse(json);
    if (r.ok) {
      showToast('✅ ' + r.message, 'success');
      closeAddSourceModal();
      loadCustomSources();
      loadSettings();
    } else {
      showToast(r.message, 'error');
    }
  });
}

function removeCustomSource(name) {
  pywebview.api.remove_custom_source(name).then(function(json) {
    var r = JSON.parse(json);
    showToast(r.ok ? '✅ 已移除' : r.message, r.ok ? 'success' : 'error');
    loadCustomSources();
    loadSettings();
  });
}

function testSourceConnection(key, label) {
  var btns = document.querySelectorAll('.btn-test-source');
  var targetBtn = null;
  btns.forEach(function(b) {
    if (b.closest('.chip') && b.closest('.chip').dataset.src === key) targetBtn = b;
  });
  if (!targetBtn) return;
  targetBtn.className = 'btn-test-source testing';
  targetBtn.textContent = '↻';

  pywebview.api.test_source_connection(key).then(function(json) {
    var r = JSON.parse(json);
    if (r.ok) {
      targetBtn.className = 'btn-test-source ok';
      targetBtn.textContent = '✓';
      showToast(label + ': ✅ ' + r.message, 'success');
    } else {
      targetBtn.className = 'btn-test-source fail';
      targetBtn.textContent = '✗';
      showToast(label + ': ❌ ' + r.message, 'error');
    }
    setTimeout(function() {
      targetBtn.className = 'btn-test-source';
      targetBtn.textContent = '🔍';
    }, 3000);
  });
}

function loadCustomSources() {
  pywebview.api.get_custom_sources().then(function(json) {
    customSources = JSON.parse(json);
    var container = document.getElementById('customSourcesList');
    if (!customSources.length) {
      container.innerHTML = '<p style="font-size:0.78rem;color:var(--text-muted);padding:4px 0;">暂无自定义检索源</p>';
      return;
    }
    var html = '<div class="custom-source-list">';
    customSources.forEach(function(cs) {
      html += '<div class="custom-source-item">';
      html += '<div class="cs-info"><div class="cs-name">' + esc(cs.name) + '</div>';
      html += '<div class="cs-url">' + esc(cs.base_url || '') + '</div></div>';
      html += '<button class="btn-remove-source" onclick="removeCustomSource(\'' + esc(cs.name) + '\')">移除</button>';
      html += '</div>';
    });
    html += '</div>';
    container.innerHTML = html;
  });
}

// ============================================================
// Toast
// ============================================================
function showToast(message, type, duration) {
  type = type || 'success';
  duration = duration || 2500;
  var container = document.getElementById('toastContainer');
  var toast = document.createElement('div');
  toast.className = 'toast ' + type;
  var icons = { success: '✓', error: '✗', info: 'ℹ' };
  toast.innerHTML = '<span style="font-weight:700">' + (icons[type] || '') + '</span> ' + message;
  container.appendChild(toast);
  setTimeout(function() {
    toast.classList.add('out');
    setTimeout(function() { toast.remove(); }, 250);
  }, duration);
}

// ============================================================
// Pipeline Config
// ============================================================
var PIPELINE_STAGES = [
  { key: 'extracting_keywords', icon: '🔑', label: '关键词提取' },
  { key: 'searching',           icon: '🔍', label: '文献检索' },
  { key: 'ranking',             icon: '📊', label: '排序筛选' },
  { key: 'extracting',          icon: '📝', label: '结构化抽取' },
  { key: 'analyzing',           icon: '🧠', label: '多维分析' },
  { key: 'generating',          icon: '✍️', label: '综述生成' },
];

var pipelineInitialized = false;

function initPipelineDOM() {
  if (pipelineInitialized) return;
  var container = document.getElementById('pipelineStages');
  var html = '';
  for (var i = 0; i < PIPELINE_STAGES.length; i++) {
    var s = PIPELINE_STAGES[i];
    html +=
      '<div class="pipeline-stage" id="ps-' + s.key + '">' +
        '<div class="pipeline-node" id="pn-' + s.key + '">' +
          '<span class="pipeline-icon">' + s.icon + '</span>' +
          '<span class="pipeline-check">✓</span>' +
        '</div>' +
        '<div class="pipeline-label">' + s.label + '</div>' +
      '</div>';
    if (i < PIPELINE_STAGES.length - 1) {
      html += '<div class="pipeline-connector" id="pc-' + i + '"></div>';
    }
  }
  container.innerHTML = html;
  pipelineInitialized = true;
}

function updatePipeline(stageKey, progress) {
  initPipelineDOM();
  var keys = PIPELINE_STAGES.map(function(s){ return s.key; });
  var curIdx = keys.indexOf(stageKey);
  if (curIdx < 0) curIdx = 0;

  for (var i = 0; i < PIPELINE_STAGES.length; i++) {
    var stage = PIPELINE_STAGES[i];
    var stageEl = document.getElementById('ps-' + stage.key);
    var nodeEl = document.getElementById('pn-' + stage.key);
    if (!stageEl || !nodeEl) continue;

    stageEl.className = 'pipeline-stage';
    nodeEl.className = 'pipeline-node';

    if (i < curIdx) { stageEl.classList.add('done'); nodeEl.classList.add('done'); }
    else if (i === curIdx) { stageEl.classList.add('active'); nodeEl.classList.add('active'); }

    if (i < PIPELINE_STAGES.length - 1) {
      var conn = document.getElementById('pc-' + i);
      conn.className = 'pipeline-connector';
      if (i < curIdx) conn.classList.add('done');
      else if (i === curIdx) conn.classList.add('active');
    }
  }
}

// ============================================================
// Page Navigation
// ============================================================
function switchPage(page) {
  document.getElementById('navGenerate').classList.toggle('active', page === 'generate');
  document.getElementById('navSettings').classList.toggle('active', page === 'settings');
  document.getElementById('pageGenerate').classList.toggle('active', page === 'generate');
  document.getElementById('pageSettings').classList.toggle('active', page === 'settings');
  document.getElementById('sidebarGenerate').style.display = page === 'generate' ? '' : 'none';
  document.getElementById('sidebarSettings').style.display = page === 'settings' ? '' : 'none';
}

// ============================================================
// Theme
// ============================================================
function toggleTheme() {
  var html = document.documentElement;
  var isDark = html.getAttribute('data-theme') === 'dark';
  html.setAttribute('data-theme', isDark ? 'light' : 'dark');
  document.getElementById('themeIcon').textContent = isDark ? '☀' : '☽';
}

// ============================================================
// Slider helpers
// ============================================================
function updateSlider(id, val) { document.getElementById(id).textContent = val; checkInput(); }
function checkInput() { document.getElementById('generateBtn').disabled = document.getElementById('queryInput').value.trim().length < 10; }

// ============================================================
// Settings
// ============================================================
var currentSettings = {};

var modelStatus = {};

function loadSettings() {
  pywebview.api.get_settings().then(function(json) {
    currentSettings = JSON.parse(json);
    applySettingsToForm(currentSettings);
    bindAutoSave();
    loadCustomSources();
    checkModelStatus();
  });
}

function checkModelStatus() {
  pywebview.api.check_models_status().then(function(json) {
    modelStatus = JSON.parse(json);
    updateModelStatusUI();
  });
}

function updateModelStatusUI() {
  // Embedding
  var embSel = document.getElementById('setEmbedding');
  var embId = embSel.options[embSel.selectedIndex].dataset.id;
  var embInfo = modelStatus[embId];
  var embEl = document.getElementById('embeddingStatus');
  if (embInfo && embInfo.downloaded) {
    embEl.innerHTML = '<span style="color:var(--success);">✅ 已下载</span>';
  } else {
    embEl.innerHTML = '<span style="color:var(--warning);">⚠ 未下载</span>';
  }

  // Reranker
  var rerankSel = document.getElementById('setReranker');
  var rerankId = rerankSel.options[rerankSel.selectedIndex].dataset.id;
  var rerankInfo = modelStatus[rerankId];
  var rerankEl = document.getElementById('rerankerStatus');
  if (rerankInfo && rerankInfo.downloaded) {
    rerankEl.innerHTML = '<span style="color:var(--success);">✅ 已下载</span>';
  } else {
    rerankEl.innerHTML = '<span style="color:var(--warning);">⚠ 未下载</span>';
  }

  updateDownloadBtn();
}

function onModelSelect() {
  updateModelStatusUI();
  autoSaveHandler();
}

function updateDownloadBtn() {
  var embSel = document.getElementById('setEmbedding');
  var embId = embSel.options[embSel.selectedIndex].dataset.id;
  var rerankSel = document.getElementById('setReranker');
  var rerankId = rerankSel.options[rerankSel.selectedIndex].dataset.id;
  var embInfo = modelStatus[embId];
  var rerankInfo = modelStatus[rerankId];

  var needDownload = (embInfo && !embInfo.downloaded) || (rerankInfo && !rerankInfo.downloaded);
  var container = document.getElementById('modelDownloadBtn');
  if (needDownload) {
    container.style.display = 'block';
    if (embInfo && !embInfo.downloaded) {
      document.getElementById('btnDownloadModel').textContent = '⬇ 下载 ' + embId.split('/').pop();
      document.getElementById('btnDownloadModel').dataset.model = embId;
    } else if (rerankInfo && !rerankInfo.downloaded) {
      document.getElementById('btnDownloadModel').textContent = '⬇ 下载 ' + rerankId.split('/').pop();
      document.getElementById('btnDownloadModel').dataset.model = rerankId;
    }
  } else {
    container.style.display = 'none';
  }
}

function downloadSelectedModel() {
  var modelId = document.getElementById('btnDownloadModel').dataset.model;
  if (!modelId) return;
  var btn = document.getElementById('btnDownloadModel');
  btn.disabled = true;
  btn.textContent = '⏳ 下载中...';
  pywebview.api.download_model(modelId).then(function(json) {
    var r = JSON.parse(json);
    if (r.ok) {
      showToast('✅ ' + r.message, 'success');
      checkModelStatus();
    } else {
      showToast('❌ 下载失败: ' + r.message, 'error');
      btn.disabled = false;
      btn.textContent = '⬇ 重试';
    }
  });
}

// Stage model config
var STAGE_MODEL_KEYS = [
  'keyword_extraction', 'relevance_scoring', 'structured_extraction',
  'timeline_analysis', 'topic_clustering', 'conflict_detection',
  'chapter_planning', 'review_writing', 'citation_checking', 'polishing',
];

var STAGE_MODEL_LABELS = {
  keyword_extraction: '🔑 关键词提取',
  relevance_scoring: '📊 相关性评分',
  structured_extraction: '📝 结构化抽取',
  timeline_analysis: '📅 时间线分析',
  topic_clustering: '🧩 主题聚类',
  conflict_detection: '⚔️ 冲突检测',
  chapter_planning: '📋 章节规划',
  review_writing: '✍️ 综述撰写',
  citation_checking: '✅ 引文校验',
  polishing: '✨ 综述润色',
};

function renderStageModelToggles(stageModels) {
  var container = document.getElementById('stageModels');
  var html = '';
  for (var i = 0; i < STAGE_MODEL_KEYS.length; i++) {
    var key = STAGE_MODEL_KEYS[i];
    var label = STAGE_MODEL_LABELS[key] || key;
    var isPro = (stageModels && stageModels[key] === 'pro');
    html += '<div class="stage-select-row">';
    html += '<span class="stage-select-label">' + label + '</span>';
    html += '<select class="stage-select" data-stage="' + key + '" onchange="onStageSelect(this)">';
    html += '<option value="flash" ' + (isPro ? '' : 'selected') + '>⚡ Flash</option>';
    html += '<option value="pro" ' + (isPro ? 'selected' : '') + '>🧠 Pro</option>';
    html += '</select>';
    html += '</div>';
  }
  container.innerHTML = html;
}

function onStageSelect(sel) {
  var stage = sel.dataset.stage;
  var model = sel.value;
  updateFlowTableStage(stage, model);
}

function updateFlowTableStage(stage, model) {
  var el = document.getElementById('flow-stage-' + stage);
  if (el) el.textContent = model === 'pro' ? '🧠 Pro' : '⚡ Flash';
}

function updateAllFlowTableStages(stageModels) {
  for (var i = 0; i < STAGE_MODEL_KEYS.length; i++) {
    var key = STAGE_MODEL_KEYS[i];
    var model = (stageModels && stageModels[key] === 'pro') ? 'pro' : 'flash';
    var el = document.getElementById('flow-stage-' + key);
    if (el) el.textContent = model === 'pro' ? '🧠 Pro' : '⚡ Flash';
  }
}

function applySettingsToForm(s) {
  // Pro model
  var proUrl = s.llm_base_url || 'https://api.deepseek.com';
  var presets = ['https://api.deepseek.com', 'https://api.openai.com/v1', 'http://localhost:11434/v1'];
  var proIdx = presets.indexOf(proUrl);
  document.getElementById('setProPreset').value = proIdx >= 0 ? proUrl : '__custom__';
  document.getElementById('setProCustomURL').style.display = proIdx >= 0 ? 'none' : '';
  document.getElementById('setProBaseURL').value = proUrl;
  document.getElementById('setProModel').value = s.llm_model || 'deepseek-v4-pro';
  document.getElementById('setProAPIKey').value = s.llm_api_key || '';

  // Flash model
  var flashUrl = s.flash_base_url || 'https://api.deepseek.com';
  var flashIdx = presets.indexOf(flashUrl);
  document.getElementById('setFlashPreset').value = flashIdx >= 0 ? flashUrl : '__custom__';
  document.getElementById('setFlashCustomURL').style.display = flashIdx >= 0 ? 'none' : '';
  document.getElementById('setFlashBaseURL').value = flashUrl;
  document.getElementById('setFlashModel').value = s.flash_model || 'deepseek-v4-flash';
  document.getElementById('setFlashAPIKey').value = s.flash_api_key || '';

  // Stage models
  var stageModels = s.stage_models || {};
  renderStageModelToggles(stageModels);
  updateAllFlowTableStages(stageModels);

  // Search
  document.getElementById('setMaxRounds').value = s.max_rounds || 1;
  document.getElementById('setPapersPerRound').value = s.papers_per_round || 30;
  document.getElementById('setFinalPapers').value = s.final_papers || 10;
  document.getElementById('setOutputDir').value = s.output_dir || '';

  // Embedding / Reranker
  setSelectValue('setEmbedding', s.embedding_model || 'BAAI/bge-small-zh-v1.5');
  setSelectValue('setReranker', s.reranker_model || 'BAAI/bge-reranker-v2-m3');

  // Flow table: embedding & reranker names
  updateText('flow-full-emb', (s.embedding_model || '').replace('BAAI/', '').replace('sentence-transformers/', ''));
  updateText('flow-full-rerank', (s.reranker_model || '').replace('BAAI/', ''));

  // Sources — render all (built-in + custom) dynamically
  var sources = s.search_sources || ['arxiv', 'semantic_scholar'];
  var builtInSources = [
    { key: 'arxiv', label: 'arXiv' },
    { key: 'semantic_scholar', label: 'Semantic Scholar' },
    { key: 'pubmed', label: 'PubMed' },
    { key: 'dblp', label: 'DBLP' },
  ];
  // Add custom sources
  var allCustom = s.custom_sources || [];
  var allSources = builtInSources.concat(allCustom.map(function(cs) {
    return { key: cs.name, label: cs.name, isCustom: true };
  }));
  var chipsHtml = '';
  allSources.forEach(function(src) {
    var isChecked = sources.indexOf(src.key) >= 0;
    chipsHtml += '<span class="chip' + (isChecked ? ' checked' : '') + '" data-src="' + esc(src.key) + '">';
    chipsHtml += '<span onclick="toggleChip(this.parentElement)" style="cursor:pointer;">' + esc(src.label) + '</span>';
    chipsHtml += '<button class="btn-test-source" onclick="event.stopPropagation();testSourceConnection(\'' + esc(src.key) + '\', \'' + esc(src.label) + '\')" title="检测连通性">🔍</button>';
    chipsHtml += '</span>';
  });
  document.getElementById('sourceChips').innerHTML = chipsHtml;

  // Sidebar status card (matches web version)
  var srcLabels = { arxiv: 'arXiv', semantic_scholar: 'S2', pubmed: 'PubMed', dblp: 'DBLP' };
  var srcDisplay = (s.search_sources || []).map(function(x) { return srcLabels[x] || x; }).join(', ');
  // Bind auto-save to all settings inputs/selects
  bindAutoSave();
  // Sync sidebar sliders
  document.getElementById('maxRounds').value = s.max_rounds || 1;
  document.getElementById('papersPerRound').value = s.papers_per_round || 30;
  document.getElementById('finalPapers').value = s.final_papers || 10;
  updateSlider('roundsVal', s.max_rounds || 1);
  updateSlider('papersVal', s.papers_per_round || 30);
  updateSlider('finalVal', s.final_papers || 10);
}

function setSelectValue(id, val) {
  var sel = document.getElementById(id);
  for (var i = 0; i < sel.options.length; i++) {
    if (sel.options[i].value === val) { sel.selectedIndex = i; return; }
  }
}

function updateText(id, val) { var el = document.getElementById(id); if (el) el.textContent = val; }

function onLLMPreset(which) {
  var presetEl = document.getElementById(which === 'pro' ? 'setProPreset' : 'setFlashPreset');
  var customEl = document.getElementById(which === 'pro' ? 'setProCustomURL' : 'setFlashCustomURL');
  var baseEl = document.getElementById(which === 'pro' ? 'setProBaseURL' : 'setFlashBaseURL');
  var val = presetEl.value;
  customEl.style.display = val === '__custom__' ? '' : 'none';
  if (val !== '__custom__') baseEl.value = val;
}

function resetSettings() {
  // Default settings matching Streamlit
  var defaults = {
    llm_base_url: 'https://api.deepseek.com',
    llm_api_key: '',
    llm_model: 'deepseek-v4-pro',
    flash_base_url: 'https://api.deepseek.com',
    flash_model: 'deepseek-v4-flash',
    flash_api_key: '',
    stage_models: {
      keyword_extraction: 'flash', relevance_scoring: 'flash',
      structured_extraction: 'pro', timeline_analysis: 'pro',
      topic_clustering: 'pro', conflict_detection: 'pro',
      chapter_planning: 'flash', review_writing: 'pro',
      citation_checking: 'flash', polishing: 'flash',
    },
    max_rounds: 2, papers_per_round: 30, final_papers: 10,
    language: 'zh',
    search_sources: ['pubmed', 'dblp'],
    embedding_model: 'BAAI/bge-small-zh-v1.5',
    reranker_model: 'BAAI/bge-reranker-v2-m3',
    output_dir: '',
  };
  currentSettings = defaults;
  pywebview.api.save_settings(JSON.stringify(defaults)).then(function() {
    showToast('🔄 已恢复默认设置', 'info');
    applySettingsToForm(defaults);
  });
}

function toggleChip(chip) {
  chip.classList.toggle('checked');
  // 即时同步到 currentSettings
  var src = chip.dataset.src;
  if (!currentSettings.search_sources) currentSettings.search_sources = [];
  if (chip.classList.contains('checked')) {
    if (currentSettings.search_sources.indexOf(src) < 0) currentSettings.search_sources.push(src);
  } else {
    currentSettings.search_sources = currentSettings.search_sources.filter(function(s) { return s !== src; });
  }
  // 即时更新侧边栏 + 触发自动保存
  autoSaveHandler();
}

function getCheckedSources() {
  // 直接从 DOM 读取 chips 的勾选状态（确保和用户看到的一致）
  var chips = document.querySelectorAll('#sourceChips .chip.checked');
  var sources = [];
  chips.forEach(function(c) { sources.push(c.dataset.src); });
  if (!sources.length) sources = ['pubmed', 'dblp'];  // 兜底，默认只用可用的源
  return sources;
}

function updateSidebarSources() {
  var srcLabels = { arxiv: 'arXiv', semantic_scholar: 'S2', pubmed: 'PubMed', dblp: 'DBLP' };
  var sources = getCheckedSources();
  var srcDisplay = sources.map(function(x) { return srcLabels[x] || x; }).join(', ');
  var srcEl2 = document.getElementById('sidebarSources');
  if (srcEl2) srcEl2.textContent = srcDisplay || '-';
}

var autoSaveTimer = null;

function bindAutoSave() {
  // Auto-save when any input/select in settings changes
  var settingsPage = document.getElementById('pageSettings');
  if (!settingsPage) return;
  var fields = settingsPage.querySelectorAll('input, select');
  fields.forEach(function(el) {
    el.removeEventListener('change', autoSaveHandler);
    el.removeEventListener('input', autoSaveHandler);
    el.addEventListener('change', autoSaveHandler);
    el.addEventListener('input', autoSaveHandler);
  });
}

function autoSaveHandler() {
  // Debounce: save 800ms after last change
  if (autoSaveTimer) clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(function() {
    saveSettings(true);
  }, 800);
}

function saveSettings(silent) {
  var proUrl = document.getElementById('setProPreset').value;
  if (proUrl === '__custom__') proUrl = document.getElementById('setProBaseURL').value;

  var flashUrl = document.getElementById('setFlashPreset').value;
  if (flashUrl === '__custom__') flashUrl = document.getElementById('setFlashBaseURL').value;

  var sources = [];
  document.querySelectorAll('#sourceChips .chip.checked').forEach(function(c) { sources.push(c.dataset.src); });

  // Collect stage models from select dropdowns
  var stageModels = {};
  document.querySelectorAll('#stageModels select.stage-select').forEach(function(sel) {
    stageModels[sel.dataset.stage] = sel.value;
  });

  var s = {
    llm_base_url: proUrl,
    llm_api_key: document.getElementById('setProAPIKey').value,
    llm_model: document.getElementById('setProModel').value,
    flash_base_url: flashUrl,
    flash_model: document.getElementById('setFlashModel').value,
    flash_api_key: document.getElementById('setFlashAPIKey').value,
    stage_models: stageModels,
    embedding_model: document.getElementById('setEmbedding').value,
    reranker_model: document.getElementById('setReranker').value,
    max_rounds: parseInt(document.getElementById('setMaxRounds').value) || 1,
    papers_per_round: parseInt(document.getElementById('setPapersPerRound').value) || 30,
    final_papers: parseInt(document.getElementById('setFinalPapers').value) || 10,
    search_sources: sources.length ? sources : ['arxiv', 'semantic_scholar'],
    output_dir: document.getElementById('setOutputDir').value,
  };

  currentSettings = s;
  pywebview.api.save_settings(JSON.stringify(s)).then(function() {
    if (!silent) showToast('✅ 设置已保存', 'success');
    applySettingsToForm(s);
  });
}

// ============================================================
// Generate Review
// ============================================================
var queryInputValue = '';

function startReview() {
  var query = document.getElementById('queryInput').value.trim();
  if (query.length < 10) return;

  // 检查本地模型是否已下载
  var embId = document.getElementById('setEmbedding').options[document.getElementById('setEmbedding').selectedIndex].dataset.id;
  var rerankId = document.getElementById('setReranker').options[document.getElementById('setReranker').selectedIndex].dataset.id;
  var embOk = modelStatus[embId] && modelStatus[embId].downloaded;
  var rerankOk = modelStatus[rerankId] && modelStatus[rerankId].downloaded;
  if (!embOk || !rerankOk) {
    var missing = [];
    if (!embOk) missing.push(embId.split('/').pop());
    if (!rerankOk) missing.push(rerankId.split('/').pop());
    showToast('⚠ 模型未下载: ' + missing.join(', ') + '。请先在设置页下载模型再运行。', 'error', 5000);
    return;
  }

  queryInputValue = query;

  // Pass all current config (matching Streamlit behavior)
  // currentSettings holds the latest form values from settings page
  var s = currentSettings || {};
  // 同步更新 currentSettings 中的检索源
  currentSettings.search_sources = getCheckedSources();
  var config = {
    max_rounds: parseInt(document.getElementById('maxRounds').value),
    papers_per_round: parseInt(document.getElementById('papersPerRound').value),
    final_papers: parseInt(document.getElementById('finalPapers').value),
    search_sources: getCheckedSources().join(','),
    llm_api_key: s.llm_api_key || '',
    llm_base_url: s.llm_base_url || '',
    llm_model: s.llm_model || '',
    flash_api_key: s.flash_api_key || '',
    flash_base_url: s.flash_base_url || '',
    flash_model: s.flash_model || 'deepseek-v4-flash',
    language: document.getElementById('reviewLanguage').value,
    stage_models: s.stage_models || {},
    embedding_model: s.embedding_model || '',
    reranker_model: s.reranker_model || '',
  };

  initPipelineDOM();
  document.getElementById('pipelineBox').style.display = 'block';
  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('liveLogArea').style.display = 'flex';
  document.getElementById('resultArea').style.display = 'none';
  document.getElementById('generateBtn').disabled = true;
  document.getElementById('progressBar').style.width = '0%';
  document.getElementById('progressText').textContent = '正在初始化...';
  document.getElementById('progressPct').textContent = '0%';
  liveLogEntries = [];
  document.getElementById('liveLogBody').innerHTML = '';
  appendLiveLog('正在初始化...');
  updatePipeline('init', 0);

  pywebview.api.generate_review(query, JSON.stringify(config));
}

var liveLogEntries = [];

function appendLiveLog(message) {
  var now = new Date();
  var time = now.getHours().toString().padStart(2,'0') + ':' +
             now.getMinutes().toString().padStart(2,'0') + ':' +
             now.getSeconds().toString().padStart(2,'0');
  liveLogEntries.push({time: time, msg: message});
  var body = document.getElementById('liveLogBody');
  var atBottom = !body.lastElementChild || (body.scrollTop + body.clientHeight >= body.scrollHeight - 30);
  var entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = '<span class="time">' + esc(time) + '</span>' + esc(message);
  body.appendChild(entry);
  if (atBottom) body.scrollTop = body.scrollHeight;
}

// Map stage names to pipeline keys
var STAGE_TO_PIPELINE = {
  'init': 'extracting_keywords',
  'extracting_keywords': 'extracting_keywords',
  'searching': 'searching',
  'ranking': 'ranking',
  'adjust_search_params': 'searching',
  'extracting': 'extracting',
  'analyzing': 'analyzing',
  'generating': 'generating',
  'done': 'generating',
};

var lastPipelineKey = '';

function onProgress(stage, progress, message) {
  document.getElementById('progressBar').style.width = (progress * 100) + '%';
  document.getElementById('progressText').textContent = message;
  document.getElementById('progressPct').textContent = Math.round(progress * 100) + '%';
  appendLiveLog(message);

  // Update pipeline
  var pipeKey = STAGE_TO_PIPELINE[stage] || stage;
  if (pipeKey !== lastPipelineKey) {
    if (pipeKey === 'extracting_keywords' && progress < 0.02) pipeKey = 'extracting_keywords';
    updatePipeline(pipeKey, progress);
    lastPipelineKey = pipeKey;
  }
}

function onComplete(result) {
  if (typeof result === 'string') { try { result = JSON.parse(result); } catch(e) {} }
  if (typeof result === 'string') { try { result = JSON.parse(result); } catch(e) {} }
  displayResult(result);
  addHistoryEntry(result.task_id || '', queryInputValue || '', result.statistics || {}, result);
}

// Reusable result display (used by onComplete and viewHistory)
function displayResult(result, storedLiveLogs) {
  var stats = result.statistics || {};
  var noPapers = (stats.total_papers_retrieved === 0);

  document.getElementById('pipelineBox').style.display = 'none';
  document.getElementById('liveLogArea').style.display = 'none';
  document.getElementById('generateBtn').disabled = false;

  // 检索完全失败 → 显示错误提示，不展示空结果
  if (noPapers) {
    document.getElementById('resultArea').style.display = 'none';
    document.getElementById('emptyState').style.display = 'flex';
    document.getElementById('emptyState').innerHTML =
      '<div class="empty-icon" style="font-size:3rem;">⚠️</div>' +
      '<h3 style="color:var(--error);">检索失败</h3>' +
      '<p style="max-width:480px;line-height:1.6;">所有检索源均无法获取论文，请检查网络连接后重试。</p>' +
      '<div style="margin-top:12px;font-size:0.78rem;color:var(--text-muted);max-width:520px;line-height:1.6;">' +
        '<b>建议</b>：<br>' +
        '1. 在设置中启用 <b>PubMed</b> 和 <b>DBLP</b>（通常更稳定）<br>' +
        '2. 检查 arXiv 是否需要配置代理（ARXIV_API_URL）<br>' +
        '3. 确认网络可以访问学术 API 端点' +
      '</div>';
    return;
  }

  document.getElementById('resultArea').style.display = 'block';
  document.getElementById('emptyState').style.display = 'none';

  document.getElementById('statRetrieved').textContent = stats.total_papers_retrieved || '-';
  document.getElementById('statUsed').textContent = stats.final_papers_used || '-';
  document.getElementById('statRounds').textContent = stats.retrieval_rounds || '-';
  document.getElementById('statClusters').textContent = stats.topic_clusters || '-';
  document.getElementById('statChars').textContent = (stats.review_length_chars || 0).toLocaleString();

  // Review — fix reference format before rendering
  var review = result.final_review || result.draft || '';
  if (review) review = fixReferenceFormat(review);
  document.getElementById('panelReview').innerHTML = review
    ? '<div class="review-body">' + renderMarkdown(review) + '</div>'
    : '<p style="color:var(--text-muted);text-align:center;padding:40px">未能生成综述内容</p>';

  document.getElementById('saveBtnContainer').innerHTML =
    '<div class="save-group">' +
      '<select id="saveFormat" class="save-format-select">' +
        '<option value="md">📝 Markdown</option>' +
        '<option value="doc">📄 Word (.doc)</option>' +
        '<option value="html">🌐 HTML</option>' +
      '</select>' +
      '<button class="btn-save" onclick="saveReview()">📥 保存</button>' +
    '</div>';

  // Analysis
  var a = '<h3 class="section-title">🧩 主题聚类</h3>';
  (result.topic_clusters || []).forEach(function(c) {
    a += '<div class="cluster-item"><h4>' + esc(c.cluster_name || '未命名') + ' <span style="font-weight:400;color:var(--text-muted);font-size:0.72rem;">' + (c.paper_ids || []).length + ' 篇</span></h4>';
    a += '<p>' + esc(c.description || '') + '</p>';
    if (c.key_themes) a += '<small style="color:var(--accent);">主题: ' + esc(c.key_themes.join(', ')) + '</small>';
    a += '</div>';
  });
  if (!result.topic_clusters || !result.topic_clusters.length) a += '<p style="color:var(--text-muted)">未生成主题聚类</p>';

  a += '<h3 class="section-title">⚔️ 观点冲突</h3>';
  (result.conflicts || []).forEach(function(c) {
    var typeLabel = (c.type || '观点分歧');
    var typeMap = {
      'conclusion': '🔴 结论冲突',
      'methodology': '🔧 方法论分歧',
      'open_question': '❓ 开放问题',
    };
    var displayType = typeMap[c.type] || ('⚡ ' + typeLabel);
    a += '<div class="conflict-card">';
    a += '<div class="conflict-type-badge">' + esc(displayType) + '</div>';
    a += '<div class="conflict-desc">' + esc(c.description || '无描述') + '</div>';
    if (c.involved_papers && c.involved_papers.length) {
      a += '<div class="conflict-papers">📄 涉及文献: ' + esc(c.involved_papers.slice(0, 5).join(', ')) + '</div>';
    }
    if (c.positions && c.positions.length) {
      c.positions.forEach(function(pos) {
        var pid = pos.paper_id || pos.paper || '';
        var view = pos.position || pos.view || '';
        // 用 paper_id 查找论文标题
        var title = pid;
        (result.structured_papers || []).forEach(function(sp) {
          if (sp.paper_id === pid) { title = sp.title || pid; }
        });
        a += '<div class="conflict-position"><strong>' + esc(title) + '</strong><br>' + esc(view) + '</div>';
      });
    }
    a += '</div>';
  });
  if (!result.conflicts || !result.conflicts.length) a += '<p style="color:var(--text-muted);padding:20px;text-align:center;">✅ 未发现明显观点冲突</p>';

  document.getElementById('panelAnalysis').innerHTML = a;

  // Papers
  var p = '';
  (result.structured_papers || []).forEach(function(pp) {
    var bc = pp.relevance_level === 'high' ? 'badge-high' : pp.relevance_level === 'mid' ? 'badge-mid' : 'badge-low';
    p += '<div class="paper-item">';
    p += '<div class="title">' + esc(pp.title || 'Untitled') + ' <span class="badge ' + bc + '">' + (pp.relevance_level || '?') + '</span></div>';
    p += '<div class="meta">' + (pp.authors || []).slice(0, 4).join(', ') + ' · ' + (pp.year || '?') + ' · ' + esc(pp.journal || '') + ' · 相关性 ' + (pp.relevance_score || 0).toFixed(2) + '</div>';
    if (pp.key_findings && pp.key_findings.length) p += '<div class="findings">🔑 ' + esc(pp.key_findings.slice(0, 2).join('; ')) + '</div>';
    p += '</div>';
  });
  document.getElementById('panelPapers').innerHTML = p || '<p style="color:var(--text-muted);text-align:center;padding:40px">暂无数据</p>';

  // Logs — 完全复制实时日志内容，追加后端日志
  var lgEl = document.getElementById('panelLogs');
  // 实时日志按原始格式：每行 "[HH:MM:SS] message"
  var sourceLogs = storedLiveLogs || liveLogEntries;
  var liveLines = sourceLogs.map(function(e) { return '[' + e.time + '] ' + e.msg; });
  // 合并后端日志（去重，完成消息放在最后）
  var seen = {};
  liveLines.forEach(function(line) { seen[line] = true; });
  var backendLines = (result.logs || []).filter(function(line) { return !seen[line]; });
  // 把包含"完成"/"完毕"的最后一条实时日志移到末尾
  var completionLine = '';
  for (var i = liveLines.length - 1; i >= 0; i--) {
    if (/完毕|完成|100%|done/i.test(liveLines[i])) {
      completionLine = liveLines[i];
      liveLines.splice(i, 1);
      break;
    }
  }
  lgEl._logs = liveLines.concat(backendLines);
  if (completionLine) lgEl._logs.push(completionLine);
  var l = '';
  lgEl._logs.forEach(function(ll, i) {
    l += '<div class="log-entry">';
    l += '<span class="log-index">' + (i + 1) + '</span>';
    l += '<span class="log-text">' + esc(ll) + '</span>';
    l += '</div>';
  });
  lgEl.innerHTML = l
    ? '<div class="log-viewer">' + l + '</div>'
    : '<p style="color:var(--text-muted);text-align:center;padding:40px">暂无执行日志</p>';
}

function onError(msg) {
  document.getElementById('pipelineBox').style.display = 'none';
  document.getElementById('liveLogArea').style.display = 'none';
  document.getElementById('resultArea').style.display = 'none';
  document.getElementById('generateBtn').disabled = false;
  document.getElementById('emptyState').style.display = 'flex';
  document.getElementById('emptyState').innerHTML =
    '<div class="empty-icon" style="font-size:3rem;">⚠️</div>' +
    '<h3 style="color:var(--error);">生成失败</h3>' +
    '<p style="max-width:480px;line-height:1.6;">' + esc(msg) + '</p>' +
    '<p style="font-size:0.78rem;color:var(--text-muted);margin-top:8px;">请检查网络连接和 API 配置后重试</p>';
}

function saveReview() {
  var format = document.getElementById('saveFormat').value;
  var content = document.getElementById('panelReview').innerText || '';
  if (content) {
    pywebview.api.save_review(content, format).then(function(path) {
      showToast('✅ 已保存至: ' + path, 'success', 4000);
    });
  }
}

function switchResultTab(name) {
  document.querySelectorAll('#resultArea .tab-btn').forEach(function(b) { b.classList.remove('active'); });
  document.querySelectorAll('#resultArea .tab-panel').forEach(function(p) { p.classList.remove('active'); });
  event.target.classList.add('active');
  document.getElementById('panel' + name.charAt(0).toUpperCase() + name.slice(1)).classList.add('active');
}

// ============================================================
// Reference Format Fix
// ============================================================
function fixReferenceFormat(text) {
  if (!text) return text;
  // Remove [待核实] markers
  text = text.replace(/\s*\[待核实\]/g, '');
  // Add line break before [N] citations (after Chinese/English sentence endings)
  text = text.replace(/(?<=[。.…])(\s*\[\d+\])/g, '\n$1');
  // Fix numbered reference lists (e.g., "1. Author...")
  text = text.replace(/(?<=[。.])(\s*\d+\.\s+(?=[A-Z]))/g, '\n$1');
  return text;
}

// ============================================================
// Markdown Renderer
// ============================================================
function renderMarkdown(md) {
  var h = md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  h = h.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  h = h.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  h = h.replace(/\*(.+?)\*/g, '<i>$1</i>');
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
  h = h.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
  h = h.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
  h = h.replace(/\n\n/g, '</p><p>');
  return '<p>' + h + '</p>';
}

function esc(s) { return s ? String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;') : ''; }

// ============================================================
// Init
// ============================================================
window.addEventListener('pywebviewready', function() {
  loadHistory();
  loadSettings();
  checkModelStatus();
});
setTimeout(function() {
  if (typeof pywebview !== 'undefined') { loadHistory(); loadSettings(); checkModelStatus(); }
}, 500);
