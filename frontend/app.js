// ==========================================================================
// GLOBALS & STATE
// ==========================================================================

const API_BASE = ""; // Relative paths since hosted on same server
let currentTraces = [];
let currentPrompts = [];
let activeTraceId = null;
let activePromptId = null;
let selectedFileToIngest = null;

// ==========================================================================
// TOAST NOTIFICATIONS
// ==========================================================================

function showToast(message, type = "success") {
  const root = document.getElementById("toast-root");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  
  let icon = "✓";
  if (type === "danger") icon = "✕";
  if (type === "warning") icon = "⚠";
  
  toast.innerHTML = `<span class="toast-icon">${icon}</span> <span class="toast-msg">${message}</span>`;
  root.appendChild(toast);
  
  // Auto remove after 3.5s
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    toast.style.transition = "all 0.4s ease";
    setTimeout(() => toast.remove(), 400);
  }, 3500);
}

// ==========================================================================
// NAVIGATION & TABS
// ==========================================================================

document.querySelectorAll(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    // Remove active
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    
    // Add active
    btn.classList.add("active");
    const targetTab = btn.getAttribute("data-tab");
    document.getElementById(targetTab).classList.add("active");
    
    // Lazy loads data based on tab focus
    if (targetTab === "console-view") {
      loadTraces();
    } else if (targetTab === "registry-view") {
      loadPrompts();
    }
  });
});

// ==========================================================================
// TRACE CONSOLE (TAB 1)
// ==========================================================================

async function loadTraces(filter = "all") {
  const container = document.getElementById("traces-list");
  container.innerHTML = '<div class="list-placeholder">Loading execution traces...</div>';
  
  try {
    const isMissesFilter = filter === "misses";
    const res = await fetch(`/api/traces?suggested_only=${isMissesFilter ? "true" : "false"}`);
    currentTraces = await res.json();
    
    // Filter traces if filter is misses (since backend returns evaluation.suggested_miss=True,
    // we also want to catch manually flagged misses)
    let filtered = currentTraces;
    if (isMissesFilter) {
      filtered = currentTraces.filter(t => t.evaluation?.suggested_miss || t.is_manual_miss);
    }
    
    if (filtered.length === 0) {
      container.innerHTML = '<div class="list-placeholder">No matching execution traces found.</div>';
      return;
    }
    
    container.innerHTML = "";
    filtered.forEach(trace => {
      const item = document.createElement("div");
      item.className = `trace-item ${trace.trace_id === activeTraceId ? "active" : ""}`;
      item.setAttribute("data-id", trace.trace_id);
      
      const createdDate = new Date(trace.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      
      // Determine badge status
      let badgeClass = "status-ok";
      let badgeText = "Pass";
      
      if (trace.is_manual_miss) {
        badgeClass = "status-manual-miss";
        badgeText = "Manual Miss";
      } else if (trace.evaluation?.suggested_miss) {
        badgeClass = "status-suggested-miss";
        badgeText = "Auto Miss";
      }
      
      const toolsCount = trace.tool_calls ? trace.tool_calls.length : 0;
      
      item.innerHTML = `
        <div class="trace-meta">
          <span class="trace-date">${createdDate}</span>
          <span class="badge ${badgeClass}">${badgeText}</span>
        </div>
        <div class="trace-query-preview" title="${trace.user_query}">${escapeHtml(trace.user_query)}</div>
        <div class="trace-stats">
          <span>🛠️ ${toolsCount} tools</span>
          <span>Prompt: ${trace.prompt_version_id || 'unknown'}</span>
        </div>
      `;
      
      item.addEventListener("click", () => {
        document.querySelectorAll(".trace-item").forEach(i => i.classList.remove("active"));
        item.classList.add("active");
        activeTraceId = trace.trace_id;
        renderTracePlayer(trace);
      });
      
      container.appendChild(item);
    });
    
    // Auto-select active trace if present in list
    if (activeTraceId) {
      const activeEl = container.querySelector(`[data-id="${activeTraceId}"]`);
      if (activeEl) activeEl.classList.add("active");
    }
    
  } catch (e) {
    container.innerHTML = `<div class="list-placeholder danger">Error loading traces: ${e.message}</div>`;
  }
}

// Filter listeners
document.querySelectorAll(".filter-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    loadTraces(btn.getAttribute("data-filter"));
  });
});

// Render the detailed timeline trace player
function renderTracePlayer(trace) {
  const panel = document.getElementById("trace-player");
  panel.innerHTML = "";
  
  const createdDate = new Date(trace.created_at).toLocaleString();
  const isMiss = trace.is_manual_miss || trace.evaluation?.suggested_miss;
  const missBtnText = trace.is_manual_miss ? "✕ Unflag Miss" : "⚠ Flag as Miss";
  
  // Trace header
  const header = document.createElement("div");
  header.className = "player-header";
  header.innerHTML = `
    <div class="player-title">
      <h2>Trace ID: ${trace.trace_id.substring(0, 8)}...</h2>
      <div class="player-title-meta">
        <span class="trace-date">${createdDate}</span>
        <span class="version-badge">Prompt: ${trace.prompt_version_id || 'unassigned'}</span>
      </div>
    </div>
    <div class="action-bar">
      <button class="action-btn ${trace.is_manual_miss ? 'btn-danger' : 'btn-warn'}" id="toggle-miss-btn">
        ${missBtnText}
      </button>
    </div>
  `;
  panel.appendChild(header);
  
  // Attach toggle miss action listener
  header.querySelector("#toggle-miss-btn").addEventListener("click", () => {
    toggleMissFlag(trace.trace_id);
  });
  
  // Timeline container
  const timeline = document.createElement("div");
  timeline.className = "timeline-container";
  
  // Node 1: User Query
  const queryNode = document.createElement("div");
  queryNode.className = "timeline-node node-query";
  queryNode.innerHTML = `
    <div class="node-label">User Query</div>
    <div class="node-box">
      <pre>${escapeHtml(trace.user_query)}</pre>
    </div>
  `;
  timeline.appendChild(queryNode);
  
  // Node 2: Thoughts / Reasoning (if present)
  if (trace.raw_thoughts) {
    const thoughtsNode = document.createElement("div");
    thoughtsNode.className = "timeline-node node-thought";
    thoughtsNode.innerHTML = `
      <div class="node-label">Internal Thought Processes</div>
      <div class="node-box" style="background: hsla(265, 80%, 60%, 0.03);">
        <pre>${escapeHtml(trace.raw_thoughts)}</pre>
      </div>
    `;
    timeline.appendChild(thoughtsNode);
  }
  
  // Node 3: Tool executions (if tools were called)
  if (trace.tool_calls && trace.tool_calls.length > 0) {
    const toolsNode = document.createElement("div");
    toolsNode.className = "timeline-node node-tool";
    
    let toolsHtml = "";
    trace.tool_calls.forEach((tc, idx) => {
      const isFailed = tc.error ? "failed-tool" : "";
      toolsHtml += `
        <div class="tool-card ${isFailed}">
          <div class="tool-card-header">
            <span>Call #${idx + 1}: ${escapeHtml(tc.tool_name)}</span>
            <span class="badge ${tc.error ? 'status-suggested-miss' : 'status-ok'}">
              ${tc.error ? 'CRASHED' : 'SUCCESS'}
            </span>
          </div>
          <div class="tool-card-body">
            <div class="json-viewer"><strong>Arguments:</strong> <pre>${JSON.stringify(tc.arguments, null, 2)}</pre></div>
            <div class="json-viewer" style="margin-top: 8px;"><strong>Result:</strong> <pre>${escapeHtml(tc.result || tc.error || 'No result returned.')}</pre></div>
          </div>
        </div>
      `;
    });
    
    toolsNode.innerHTML = `
      <div class="node-label">Tool Execution Line (${trace.tool_calls.length} Calls)</div>
      <div class="tool-grid">${toolsHtml}</div>
    `;
    timeline.appendChild(toolsNode);
  }
  
  // Node 4: Final LLM completion
  const responseNode = document.createElement("div");
  responseNode.className = "timeline-node node-response";
  responseNode.innerHTML = `
    <div class="node-label">Final Model Response</div>
    <div class="node-box">
      <pre>${escapeHtml(trace.llm_response || 'No text output returned.')}</pre>
    </div>
  `;
  timeline.appendChild(responseNode);
  
  // Node 5: System Auto-evaluation stats
  if (trace.evaluation) {
    const evalNode = document.createElement("div");
    evalNode.className = "timeline-node node-eval";
    const evalColor = trace.evaluation.suggested_miss ? 'color: var(--warning)' : 'color: var(--success)';
    evalNode.innerHTML = `
      <div class="node-label">Autonomic Evaluator Audit</div>
      <div class="node-box" style="border-style: dashed;">
        <div style="${evalColor}; font-weight: 600;">
          Audit Result: ${trace.evaluation.suggested_miss ? 'POTENTIAL QUERY MISS DETECTED' : 'Trace Passed Rules Check'}
        </div>
        <div style="font-size: 13px; color: var(--text-secondary); margin-top: 6px;">
          Reasoning: ${trace.evaluation.failure_reason || 'Passed checks.'}
        </div>
      </div>
    `;
    timeline.appendChild(evalNode);
  }
  
  panel.appendChild(timeline);
}

async function toggleMissFlag(traceId) {
  try {
    const form = new FormData();
    form.append("trace_id", traceId);
    form.append("reason", "Manual user console override");
    
    const res = await fetch("/api/missed_queries/toggle", {
      method: "POST",
      body: form
    });
    
    const data = await res.json();
    if (data.success) {
      showToast(data.message, data.is_miss ? "warning" : "success");
      // Reload lists and player
      await loadTraces(document.querySelector(".filter-btn.active").getAttribute("data-filter"));
      // Refresh timeline player details
      const trace = currentTraces.find(t => t.trace_id === traceId);
      if (trace) renderTracePlayer(trace);
    }
  } catch (e) {
    showToast(`Failed to toggle miss flag: ${e.message}`, "danger");
  }
}

// ==========================================================================
// PROMPT REGISTRY (TAB 2)
// ==========================================================================

async function loadPrompts() {
  const container = document.getElementById("prompts-registry-list");
  container.innerHTML = '<div class="list-placeholder">Loading system prompts...</div>';
  
  try {
    const res = await fetch("/api/prompts");
    currentPrompts = await res.json();
    
    if (currentPrompts.length === 0) {
      container.innerHTML = '<div class="list-placeholder">No prompts registered yet.</div>';
      return;
    }
    
    container.innerHTML = "";
    currentPrompts.forEach(p => {
      const item = document.createElement("div");
      const isActive = p.metadata?.is_active === true;
      item.className = `prompt-item ${p.prompt_version_id === activePromptId ? "active" : ""}`;
      item.setAttribute("data-id", p.prompt_version_id);
      
      const createdDate = new Date(p.created_at).toLocaleDateString();
      
      item.innerHTML = `
        <div class="prompt-item-header">
          <span>${createdDate}</span>
          ${isActive ? '<span class="badge status-ok">Active</span>' : ''}
        </div>
        <div class="prompt-item-text"><strong>ID: ${p.prompt_version_id}</strong><br>${escapeHtml(p.prompt_text)}</div>
      `;
      
      item.addEventListener("click", () => {
        document.querySelectorAll(".prompt-item").forEach(i => i.classList.remove("active"));
        item.classList.add("active");
        activePromptId = p.prompt_version_id;
        renderPromptDetail(p);
      });
      
      container.appendChild(item);
    });
    
    // Auto load detail for active prompt
    if (!activePromptId && currentPrompts.length > 0) {
      const activePrompt = currentPrompts.find(p => p.metadata?.is_active) || currentPrompts[0];
      activePromptId = activePrompt.prompt_version_id;
      const activeEl = container.querySelector(`[data-id="${activePromptId}"]`);
      if (activeEl) activeEl.classList.add("active");
      renderPromptDetail(activePrompt);
    }
    
  } catch (e) {
    container.innerHTML = `<div class="list-placeholder danger">Error loading prompts: ${e.message}</div>`;
  }
}

function renderPromptDetail(prompt) {
  const panel = document.getElementById("prompt-detail-view");
  panel.innerHTML = "";
  
  const createdDate = new Date(prompt.created_at).toLocaleString();
  const isActive = prompt.metadata?.is_active === true;
  
  panel.innerHTML = `
    <div class="player-header">
      <div class="player-title">
        <h2>Prompt Version Registry</h2>
        <div class="player-title-meta">
          <span>ID: <strong>${prompt.prompt_version_id}</strong></span>
          <span>Created: ${createdDate}</span>
        </div>
      </div>
      <div class="action-bar">
        ${!isActive ? `<button class="action-btn" id="activate-prompt-btn">Set as Active</button>` : `<span class="badge status-ok" style="padding: 8px 16px;">Active Prompt</span>`}
      </div>
    </div>
    
    <div class="prompt-meta-grid">
      <div class="meta-box">
        <span>Parent Prompt Version</span>
        ${prompt.parent_version_id || 'None (Seed Prompt)'}
      </div>
      <div class="meta-box">
        <span>Metadata Notes</span>
        ${prompt.metadata?.description || 'No description provided.'}
      </div>
      <div class="meta-box">
        <span>Optimization Line</span>
        Gen 1 (Initial Config)
      </div>
    </div>

    <h4>System Instructions Prompt Body</h4>
    <div class="prompt-text-container">
      <pre>${escapeHtml(prompt.prompt_text)}</pre>
    </div>
  `;
  
  if (!isActive) {
    panel.querySelector("#activate-prompt-btn").addEventListener("click", async () => {
      try {
        const res = await fetch(`/api/prompts/activate/${prompt.prompt_version_id}`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
          showToast(data.message, "success");
          loadPrompts();
        }
      } catch (e) {
        showToast(`Failed to activate prompt: ${e.message}`, "danger");
      }
    });
  }
}

// Dialog handling
const newPromptDialog = document.getElementById("new-prompt-dialog");
document.getElementById("new-prompt-trigger").addEventListener("click", () => {
  document.getElementById("new-prompt-form").reset();
  newPromptDialog.showModal();
});

document.getElementById("new-prompt-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  
  const parentId = document.getElementById("prompt-parent-id").value.strip || null;
  const promptText = document.getElementById("prompt-text-area").value;
  const description = document.getElementById("prompt-desc").value;
  
  try {
    const payload = {
      prompt_text: promptText,
      parent_version_id: parentId || null,
      metadata: {
        description: description,
        is_active: false // Register first, let user activate
      }
    };
    
    const res = await fetch("/api/prompts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    
    if (res.ok) {
      showToast("New system prompt version successfully registered.");
      newPromptDialog.close();
      loadPrompts();
    }
  } catch (err) {
    showToast(`Failed to save prompt: ${err.message}`, "danger");
  }
});

// ==========================================================================
// DRAG & DROP / INGESTION HUB (TAB 3)
// ==========================================================================

const dropZone = document.getElementById("drop-zone");
const logFileInput = document.getElementById("log-file-input");

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-active");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("drag-active");
});

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-active");
  
  const files = e.dataTransfer.files;
  if (files.length > 0) {
    handleFileSelection(files[0]);
  }
});

logFileInput.addEventListener("change", () => {
  if (logFileInput.files.length > 0) {
    handleFileSelection(logFileInput.files[0]);
  }
});

async function handleFileSelection(file) {
  selectedFileToIngest = file;
  
  // Show analyze sample first to trigger the Ingestion Wizard
  const form = new FormData();
  form.append("file", file);
  
  try {
    showToast("Analyzing file structure...", "warning");
    const res = await fetch("/api/logs/analyze", {
      method: "POST",
      body: form
    });
    
    const data = await res.json();
    if (data.success) {
      showWizard(data);
    }
  } catch (err) {
    showToast(`Failed to analyze log file: ${err.message}`, "danger");
  }
}

function showWizard(data) {
  const wizard = document.getElementById("wizard-container");
  document.getElementById("wizard-format").textContent = data.format_type;
  document.getElementById("wizard-lines").textContent = data.total_lines;
  
  const tbody = document.getElementById("wizard-tbody");
  tbody.innerHTML = "";
  
  data.sample_parsed.forEach((row, idx) => {
    const tr = document.createElement("tr");
    
    if (row.success) {
      const p = row.parsed;
      const previewMsg = p.message || JSON.stringify(p);
      tr.innerHTML = `
        <td>${idx + 1}</td>
        <td><span class="badge status-ok">${escapeHtml(p.component || 'system')}</span></td>
        <td><span class="badge ${p.level === 'ERROR' ? 'status-suggested-miss' : 'status-ok'}">${p.level || 'INFO'}</span></td>
        <td title="${previewMsg}">${escapeHtml(previewMsg)}</td>
      `;
    } else {
      tr.innerHTML = `
        <td>${idx + 1}</td>
        <td colspan="3" style="color: var(--danger)">Failed to Parse: ${escapeHtml(row.error)}</td>
      `;
    }
    tbody.appendChild(tr);
  });
  
  wizard.style.display = "flex";
}

// Confirm full execution button on Ingestion Wizard
document.getElementById("wizard-confirm-btn").addEventListener("click", async () => {
  if (!selectedFileToIngest) return;
  
  const form = new FormData();
  form.append("file", selectedFileToIngest);
  
  try {
    showToast("Ingesting entire trace log batch...", "warning");
    document.getElementById("wizard-container").style.display = "none";
    
    const res = await fetch("/api/logs/upload", {
      method: "POST",
      body: form
    });
    
    const data = await res.json();
    if (data.success) {
      showToast(data.message, "success");
      // Clean selected file
      selectedFileToIngest = null;
      logFileInput.value = "";
      
      // Auto redirect tab to console view to check parsed outputs!
      document.querySelector('[data-tab="console-view"]').click();
    }
  } catch (err) {
    showToast(`Batch Ingestion failed: ${err.message}`, "danger");
  }
});

// ==========================================================================
// HELPERS
// ==========================================================================

function escapeHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ==========================================================================
// STARTUP INITIALIZATION
// ==========================================================================
window.addEventListener("DOMContentLoaded", () => {
  loadTraces();
});
