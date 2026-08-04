"""
Cost & learning dashboard for Model Router v1.6.1.

Self-contained single-page dashboard (no CDN, no build step):
answers the community's #1 question — "how much money did I save?"

v1.0.3: cost stats, learning stats, preset switcher, recent requests
v1.1.0: model management (auto/manual toggle), semantic cache stats,
        agent capabilities status, connection pool stats
v1.1.0: why-this-model explain panel (dry-run + request lookup)

Endpoint:
    GET /dashboard — HTML page, auto-refreshes every 10s
"""

import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# P2-5: Dashboard HTML is inlined for zero-dependency deployment
# (no CDN, no build step, no template engine). This is intentional —
# the dashboard must work with just FastAPI, no static files needed.
# If the HTML grows further, consider extracting to a templates/ directory.
_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Model Router — Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --bg:#0f1117; --card:#1a1d27; --fg:#e6e8ee; --dim:#8b90a0;
          --green:#3ddc84; --blue:#5b9dff; --amber:#ffb020; --red:#ff5050; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--fg);
         font:14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; padding:24px; }
  h1 { font-size:20px; margin-bottom:4px; }
  .sub { color:var(--dim); margin-bottom:20px; font-size:12px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
           gap:14px; margin-bottom:20px; }
  .card { background:var(--card); border-radius:10px; padding:16px; }
  .card .label { color:var(--dim); font-size:12px; text-transform:uppercase;
                 letter-spacing:.05em; }
  .card .value { font-size:26px; font-weight:700; margin-top:6px; }
  .green { color:var(--green); } .blue { color:var(--blue); } .amber { color:var(--amber); }
  section { background:var(--card); border-radius:10px; padding:16px; margin-bottom:16px; }
  h2 { font-size:14px; margin-bottom:10px; color:var(--dim); text-transform:uppercase;
       letter-spacing:.05em; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid #2a2e3d; }
  th { color:var(--dim); font-weight:500; }
  .badge { display:inline-block; padding:1px 8px; border-radius:10px; font-size:11px;
           background:#2a2e3d; }
  .badge-auto { background:#1a3a2a; color:var(--green); }
  .badge-manual { background:#3a2a1a; color:var(--amber); }
  .badge-on { background:#1a3a2a; color:var(--green); }
  .badge-off { background:#2a2e3d; color:var(--dim); }
  .preset-btn { background:#2a2e3d; border:1px solid #3a3f52; color:var(--fg);
                border-radius:8px; padding:6px 14px; cursor:pointer; margin-right:8px; }
  .preset-btn.active { border-color:var(--blue); color:var(--blue); }
  .toggle-btn { background:#2a2e3d; border:1px solid #3a3f52; color:var(--fg);
                border-radius:6px; padding:3px 10px; cursor:pointer; font-size:12px; }
  .toggle-btn:hover { border-color:var(--blue); }
  .grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media (max-width:800px) { .grid-2 { grid-template-columns:1fr; } }
  .stat-row { display:flex; justify-content:space-between; padding:4px 0;
              border-bottom:1px solid #2a2e3d; font-size:13px; }
  .stat-row:last-child { border-bottom:none; }
  .stat-label { color:var(--dim); }
  .explain-input { background:#2a2e3d; border:1px solid #3a3f52; color:var(--fg);
                   border-radius:6px; padding:8px 12px; width:100%; font-size:13px;
                   font-family:inherit; resize:vertical; }
  .explain-input:focus { outline:none; border-color:var(--blue); }
  .explain-btn { background:var(--blue); color:#fff; border:none; border-radius:6px;
                 padding:6px 16px; cursor:pointer; font-size:13px; margin-top:4px; }
  .explain-btn:hover { opacity:0.85; }
  .explain-result { margin-top:12px; }
  .explain-bar { height:8px; border-radius:4px; background:#2a2e3d; position:relative;
                 overflow:hidden; margin:2px 0 6px; }
  .explain-bar-fill { height:100%; border-radius:4px; }
  .explain-candidate { margin-bottom:10px; padding:8px; background:#1e2130;
                       border-radius:6px; }
  .explain-model { font-weight:600; font-size:13px; }
  .explain-score { color:var(--blue); font-size:12px; }
  .agent-tabs { display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }
  .agent-tab { background:#2a2e3d; border:1px solid #3a3f52; color:var(--fg);
               border-radius:8px; padding:6px 16px; cursor:pointer; font-size:13px; }
  .agent-tab.active { border-color:var(--blue); color:var(--blue); background:#1a2a3d; }
  .agent-tab:hover { border-color:var(--blue); }
  .agent-card { background:#1e2130; border-radius:8px; padding:12px; margin-bottom:8px; }
  .agent-card .agent-name { font-weight:600; font-size:14px; color:var(--green); }
  .agent-card .agent-key { color:var(--dim); font-size:11px; font-family:monospace; }
  .agent-card .agent-stats { display:flex; gap:16px; margin-top:6px; font-size:12px; }
  .agent-card .agent-stats span { color:var(--dim); }
  .agent-card .agent-stats .val { color:var(--fg); font-weight:500; }
  .explain-breakdown { display:flex; gap:12px; font-size:11px; color:var(--dim);
                       margin-top:4px; }
</style>
</head>
<body>
<h1>🧠 Model Router — Dashboard</h1>
<div class="sub">auto-refresh every 10s · <a href="/docs" style="color:var(--blue)">API docs</a> · <a href="/admin/models" style="color:var(--blue)">Admin API</a></div>

<!-- Stats Cards -->
<div class="cards">
  <div class="card"><div class="label">Estimated Savings</div>
    <div class="value green" id="savings">—</div></div>
  <div class="card"><div class="label">Savings Rate</div>
    <div class="value green" id="savings_pct">—</div></div>
  <div class="card"><div class="label">Requests Routed</div>
    <div class="value blue" id="requests">—</div></div>
  <div class="card"><div class="label">Learning Mode</div>
    <div class="value amber" id="mode">—</div></div>
  <div class="card"><div class="label">Samples Learned</div>
    <div class="value blue" id="samples">—</div></div>
  <div class="card"><div class="label">Cache Hit Rate</div>
    <div class="value green" id="cache_rate">—</div></div>
</div>

<!-- Agent Views (v1.5.0) -->
<section>
  <h2>Agent Views</h2>
  <div class="agent-tabs" id="agent_tabs">
    <button class="agent-tab active" onclick="switchAgent('all')">All</button>
  </div>
  <div id="agent_details">
    <div class="stat-row"><span class="stat-label">Loading...</span></div>
  </div>
</section>

<!-- Routing Preset -->
<section>
  <h2>Routing Preset</h2>
  <div id="presets"></div>
</section>

<!-- Two-column: Models + Cache/Capabilities -->
<div class="grid-2">

<!-- Models Management -->
<section>
  <h2>Models (<span id="model_count">—</span>)</h2>
  <table><thead><tr><th>Model</th><th>Provider</th><th>Mode</th><th>Cost/1K</th><th></th></tr></thead>
  <tbody id="models"></tbody></table>
</section>

<!-- Right column -->
<div>
<!-- Semantic Cache -->
<section>
  <h2>Semantic Cache</h2>
  <div id="cache_stats">
    <div class="stat-row"><span class="stat-label">Loading...</span></div>
  </div>
</section>

<!-- Capabilities -->
<section>
  <h2>Agent Capabilities</h2>
  <div id="cap_stats">
    <div class="stat-row"><span class="stat-label">Loading...</span></div>
  </div>
</section>

<!-- Connection Pool -->
<section>
  <h2>System</h2>
  <div id="sys_stats">
    <div class="stat-row"><span class="stat-label">Loading...</span></div>
  </div>
</section>
</div>
</div>

<!-- Learned Model Performance -->
<section>
  <h2>Learned Model Performance (task → model)</h2>
  <table><thead><tr><th>pair</th><th>mean reward μ</th><th>samples n</th></tr></thead>
  <tbody id="learned"></tbody></table>
</section>

<!-- Human Feedback (v1.2.0) -->
<section>
  <h2>Human Feedback</h2>
  <div class="cards" style="margin-bottom:12px">
    <div class="card"><div class="label">Total Feedback</div>
      <div class="value blue" id="fb_total">—</div></div>
    <div class="card"><div class="label">Positive</div>
      <div class="value green" id="fb_pos">—</div></div>
    <div class="card"><div class="label">Negative</div>
      <div class="value amber" id="fb_neg">—</div></div>
    <div class="card"><div class="label">Approval Rate</div>
      <div class="value green" id="fb_rate">—</div></div>
  </div>
  <table><thead><tr><th>request</th><th>task</th><th>model</th><th>feedback</th></tr></thead>
  <tbody id="fb_recent"></tbody></table>
</section>

<!-- Recent Requests -->
<!-- Recent Requests -->
<section>
  <h2>Recent Requests</h2>
  <table><thead><tr><th>request</th><th>task</th><th>model</th><th>mode</th><th>preset</th><th>latency</th></tr></thead>
  <tbody id="recent"></tbody></table>
</section>

<!-- Why-this-model Explain -->
<section>
  <h2>Why This Model?</h2>
  <div style="display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap">
    <div style="flex:1;min-width:200px">
      <textarea id="explain_input" class="explain-input" rows="2"
        placeholder="Enter request ID to lookup, or a message to dry-run..."></textarea>
    </div>
    <div style="display:flex;flex-direction:column;gap:4px">
      <button class="explain-btn" onclick="explainLookup()">Lookup Request</button>
      <button class="explain-btn" onclick="explainDryRun()" style="background:#2a6a3a">Dry Run</button>
    </div>
  </div>
  <div id="explain_result" class="explain-result"></div>
</section>

<script>
async function j(url){ const r = await fetch(url); return r.json(); }

// HTML escape to prevent XSS
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;');
}

async function refresh(){
  try {
    const [learn, preset, models, cache, caps] = await Promise.all([
      j('/admin/learning'),
      j('/admin/preset'),
      j('/admin/models'),
      j('/admin/cache'),
      j('/admin/capabilities'),
    ]);

    // Cost cards
    const cost = learn.cost || {};
    document.getElementById('savings').textContent =
      '$' + (cost.estimated_savings ?? 0).toFixed(4);
    document.getElementById('savings_pct').textContent =
      (cost.savings_percent ?? 0).toFixed(1) + '%';
    document.getElementById('requests').textContent = cost.total_requests ?? 0;
    const l = learn.learning || {};
    document.getElementById('mode').textContent =
      (l.mode || 'static') + (l.active ? '' : ' (observe only)');
    document.getElementById('samples').textContent = l.total_samples ?? 0;

    // Cache card
    const cacheData = cache || {};
    const hitRate = cacheData.hit_rate ?? 0;
    document.getElementById('cache_rate').textContent =
      (hitRate * 100).toFixed(1) + '%';

    // Presets
    document.getElementById('presets').innerHTML = preset.available.map(p =>
      '<button class="preset-btn' + (p === preset.current ? ' active' : '') +
      '" onclick="setPreset(\\'' + esc(p) + '\\')">' + esc(p) + '</button>').join('');
    
    // Models table
    document.getElementById('model_count').textContent = models.length;
    document.getElementById('models').innerHTML = models.slice(0, 20).map(m =>
      '<tr><td>' + esc(m.id) + '</td><td>' + esc(m.provider || '\u2014') + '</td><td>' +
      '<span class="badge badge-' + esc(m.selection_mode) + '">' + esc(m.selection_mode) + '</span></td><td>$' +
      (m.cost_per_1k_input || 0).toFixed(4) + '</td><td>' +
      '<button class="toggle-btn" onclick="toggleMode(\\'' + esc(m.id) + '\\',\\'' +
      (m.selection_mode === 'auto' ? 'manual' : 'auto') + '\\')">' +
      (m.selection_mode === 'auto' ? '\u2192 manual' : '\u2192 auto') + '</button></td></tr>'
    ).join('') || '<tr><td colspan="5" style="color:var(--dim)">No models registered</td></tr>';

    // Cache stats
    document.getElementById('cache_stats').innerHTML = [
      sr('Entries', (cacheData.entries ?? 0) + ' / ' + (cacheData.capacity ?? '?')),
      sr('Hit Rate', ((cacheData.hit_rate ?? 0) * 100).toFixed(1) + '%'),
      sr('Total Hits', cacheData.total_hits ?? 0),
      sr('Total Queries', cacheData.total_queries ?? 0),
      sr('TTL', (cacheData.ttl_seconds ?? 0) + 's'),
      sr('Similarity', cacheData.sim_threshold ?? '?'),
    ].join('');

    // Capabilities
    const capData = caps || {};
    const declared = capData.declared || {};
    const capKeys = Object.keys(declared);
    if (capKeys.length === 0) {
      document.getElementById('cap_stats').innerHTML =
        '<div class="stat-row"><span class="stat-label">No capabilities declared</span></div>';
    } else {
      document.getElementById('cap_stats').innerHTML = capKeys.map(k =>
        '<div class="stat-row"><span>' + esc(k) + '</span><span class="badge badge-on">declared</span></div>'
      ).join('');
    }

    // System (basic info)
    document.getElementById('sys_stats').innerHTML = [
      sr('Registry Mode', capData.registry_mode || '—'),
      sr('Diversity', (learn.diversity || {}).status || '—'),
      sr('Evaluator', 'available'),
    ].join('');

    // Learned table
    document.getElementById('learned').innerHTML = (l.top_learned || []).map(r =>
      '<tr><td>' + esc(r.pair.replace('|', ' \u2192 ')) + '</td><td>' + r.mu.toFixed(3) +
      '</td><td>' + r.n + '</td></tr>').join('') ||
      '<tr><td colspan="3" style="color:var(--dim)">No learning data yet</td></tr>';
    
    // Recent requests (with latency)
    document.getElementById('recent').innerHTML = (learn.recent_requests || []).map(r =>
      '<tr><td>' + esc((r.request_id || '').slice(0, 8)) + '</td><td>' + esc(r.task || '') +
      '</td><td>' + esc(r.final_model || '') + '</td><td><span class="badge">' +
      esc(r.routing_mode || '') + '</span></td><td>' + esc(r.preset || '') + '</td><td>' +
      (r.latency_ms ? r.latency_ms.toFixed(0) + 'ms' : '\u2014') + '</td></tr>')
      .reverse().join('') ||
      '<tr><td colspan="6" style="color:var(--dim)">No requests yet</td></tr>';
    // Feedback stats (v1.2.0)
    const fb = learn.feedback || {};
    document.getElementById('fb_total').textContent = fb.total ?? 0;
    document.getElementById('fb_pos').textContent = fb.positive ?? 0;
    document.getElementById('fb_neg').textContent = fb.negative ?? 0;
    const fbRate = fb.total > 0 ? ((fb.positive / fb.total) * 100).toFixed(1) + '%' : '\u2014';
    document.getElementById('fb_rate').textContent = fbRate;
    document.getElementById('fb_recent').innerHTML = (fb.recent || []).map(r =>
      '<tr><td>' + esc(r.request_id || '') + '</td><td>' + esc(r.task || '') +
      '</td><td>' + esc(r.model || '') + '</td><td><span class="badge ' +
      (r.feedback === 'positive' ? 'badge-on' : 'badge-off') + '">' +
      esc(r.feedback || '') + '</span></td></tr>').join('') ||
      '<tr><td colspan="4" style="color:var(--dim)">No feedback yet</td></tr>';

  } catch(e) { console.error(e); }
}

function sr(label, value) {
  return '<div class="stat-row"><span class="stat-label">' + esc(label) +
    '</span><span>' + esc(value) + '</span></div>';
}

async function setPreset(name){
  await fetch('/admin/preset/' + name, {method:'PUT'});
  refresh();
}

async function toggleMode(modelId, newMode){
  await fetch('/admin/models/' + modelId, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({selection_mode: newMode}),
  });
  refresh();
}

// Explain functions
async function explainLookup() {
  const rid = document.getElementById('explain_input').value.trim();
  if (!rid) { document.getElementById('explain_result').innerHTML =
    '<div style="color:var(--amber)">Enter a request ID</div>'; return; }
  try {
    const r = await fetch('/admin/explain?request_id=' + encodeURIComponent(rid));
    const d = await r.json();
    if (!r.ok) { document.getElementById('explain_result').innerHTML =
      '<div style="color:var(--red)">' + esc(d.detail || 'Not found') + '</div>'; return; }
    renderExplain(d);
  } catch(e) { document.getElementById('explain_result').innerHTML =
    '<div style="color:var(--red)">Error: ' + esc(e.message) + '</div>'; }
}

async function explainDryRun() {
  const msg = document.getElementById('explain_input').value.trim();
  if (!msg) { document.getElementById('explain_result').innerHTML =
    '<div style="color:var(--amber)">Enter a message to test routing</div>'; return; }
  try {
    const r = await fetch('/admin/explain?message=' + encodeURIComponent(msg));
    const d = await r.json();
    if (!r.ok) { document.getElementById('explain_result').innerHTML =
      '<div style="color:var(--red)">' + esc(d.detail || 'Error') + '</div>'; return; }
    renderExplain(d);
  } catch(e) { document.getElementById('explain_result').innerHTML =
    '<div style="color:var(--red)">Error: ' + esc(e.message) + '</div>'; }
}

function renderExplain(d) {
  const isDry = d.dry_run || false;
  let html = '<div style="margin-bottom:10px">';
  html += '<span style="font-size:16px;font-weight:700;color:var(--green)">' + esc(d.model || d.model_name || '?') + '</span>';
  if (d.score) html += ' <span style="color:var(--blue)">score: ' + (d.score || 0).toFixed(2) + '</span>';
  html += ' <span class="badge">' + esc(d.routing_mode || '') + '</span>';
  html += ' <span class="badge">' + esc(d.preset || '') + '</span>';
  if (d.task) html += ' <span style="color:var(--dim)">task: ' + esc(d.task) + '</span>';
  if (isDry) html += ' <span style="color:var(--amber)">[dry run]</span>';
  if (d.reason) html += '<div style="color:var(--dim);font-size:12px;margin-top:4px">' + esc(d.reason) + '</div>';
  html += '</div>';

  // Cost info
  if (d.cost !== undefined || d.estimated_cost) {
    html += '<div style="font-size:12px;color:var(--dim);margin-bottom:8px">';
    if (d.cost) html += 'Actual cost: $' + d.cost.toFixed(6);
    if (d.estimated_cost) html += ' | Estimated: $' + d.estimated_cost.toFixed(6);
    if (d.baseline_cost) html += ' | Baseline: $' + d.baseline_cost.toFixed(6);
    if (d.latency_ms) html += ' | Latency: ' + d.latency_ms.toFixed(0) + 'ms';
    if (d.prompt_tokens) html += ' | Tokens: ' + d.prompt_tokens + ' in / ' + d.completion_tokens + ' out';
    html += '</div>';
  }

  // Top candidates breakdown
  const candidates = d.top_candidates || [];
  if (candidates.length > 0) {
    html += '<div style="font-size:12px;color:var(--dim);margin-bottom:6px">Top Candidates (' + candidates.length + ')</div>';
    const maxScore = Math.max(...candidates.map(c => Math.abs(c.score || 0)), 0.01);
    candidates.forEach((c, i) => {
      const pct = Math.min(100, Math.abs(c.score || 0) / maxScore * 100);
      const color = i === 0 ? 'var(--green)' : (c.score >= 0 ? 'var(--blue)' : 'var(--red)');
      html += '<div class="explain-candidate">';
      html += '<div style="display:flex;justify-content:space-between">';
      html += '<span class="explain-model">' + esc(c.model || '') + '</span>';
      html += '<span class="explain-score">' + (c.score || 0).toFixed(2) + '</span></div>';
      html += '<div class="explain-bar"><div class="explain-bar-fill" style="width:' + pct + '%;background:' + color + '"></div></div>';
      if (c.breakdown) {
        const b = c.breakdown;
        html += '<div class="explain-breakdown">';
        if (b.capability !== undefined) html += '<span>capability: ' + b.capability.toFixed(2) + '</span>';
        if (b.cost !== undefined) html += '<span>cost: ' + b.cost.toFixed(2) + '</span>';
        if (b.speed !== undefined) html += '<span>speed: ' + b.speed.toFixed(2) + '</span>';
        if (b.learned !== undefined) html += '<span>learned: ' + b.learned.toFixed(2) + '</span>';
        if (b.total !== undefined) html += '<span>total: ' + b.total.toFixed(2) + '</span>';
        html += '</div>';
      }
      html += '</div>';
    });
  }

  // Failed models (fallback trail)
  if (d.failed_models && d.failed_models.length > 0) {
    html += '<div style="font-size:12px;color:var(--amber);margin-top:8px">';
    html += 'Fallback chain: ' + d.failed_models.map(esc).join(' \u2192 ') + ' \u2192 <strong>' + esc(d.model) + '</strong>';
    html += '</div>';
  }

  document.getElementById('explain_result').innerHTML = html;
}


// Agent view functions (v1.5.0)
let currentAgent = 'all';
let agentData = {};

async function loadAgents() {
  try {
    const r = await fetch('/admin/agents');
    if (!r.ok) return;
    agentData = await r.json();
    const agents = agentData.agents || {};
    const agentTypes = Object.keys(agents);

    let tabs = '<button class="agent-tab' + (currentAgent === 'all' ? ' active' : '') +
      '" onclick="switchAgent(\'all\')">All</button>';
    agentTypes.forEach(at => {
      tabs += '<button class="agent-tab' + (currentAgent === at ? ' active' : '') +
        '" onclick="switchAgent(\'' + esc(at) + '\')">' + esc(at) + '</button>';
    });
    document.getElementById('agent_tabs').innerHTML = tabs;

    if (currentAgent === 'all') {
      let html = '';
      agentTypes.forEach(at => {
        const a = agents[at];
        html += agentCard(at, a);
      });
      if (!html) html = '<div class="stat-row"><span class="stat-label">No agents installed. Run: model-router install</span></div>';
      document.getElementById('agent_details').innerHTML = html;
    } else {
      const a = agents[currentAgent];
      if (a) {
        document.getElementById('agent_details').innerHTML = agentCard(currentAgent, a);
      }
    }
  } catch(e) { console.debug('Agent load error:', e); }
}

function agentCard(name, data) {
  const usage = data.usage || {};
  const models = data.models || [];
  let html = '<div class="agent-card">';
  html += '<div class="agent-name">' + esc(name) + '</div>';
  html += '<div class="agent-key">' + esc(data.masked_key || '') + '</div>';
  html += '<div class="agent-stats">';
  html += '<span>Requests: <span class="val">' + (usage.requests || 0) + '</span></span>';
  html += '<span>Fallbacks: <span class="val">' + (usage.fallbacks || 0) + '</span></span>';
  html += '<span>Models: <span class="val">' + models.length + '</span></span>';
  html += '</div>';
  if (models.length > 0) {
    html += '<div style="margin-top:6px;font-size:11px;color:var(--dim)">';
    html += models.slice(0, 5).map(esc).join(', ');
    if (models.length > 5) html += ' ... +' + (models.length - 5);
    html += '</div>';
  }
  html += '</div>';
  return html;
}

function switchAgent(name) {
  currentAgent = name;
  loadAgents();
}

refresh();
loadAgents();
setInterval(refresh, 10000);
setInterval(loadAgents, 15000);
</script>
</body>
</html>
"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Self-contained dashboard: cost, learning, models, cache, capabilities."""
    return HTMLResponse(_DASHBOARD_HTML)
