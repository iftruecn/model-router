"""
Cost & learning dashboard for Model Router v1.0.9.

Self-contained single-page dashboard (no CDN, no build step):
answers the community's #1 question — "how much money did I save?"

v1.0.3: cost stats, learning stats, preset switcher, recent requests
v1.0.9: model management (auto/manual toggle), semantic cache stats,
        agent capabilities status, connection pool stats

Endpoint:
    GET /dashboard — HTML page, auto-refreshes every 10s
"""

import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter()

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

<!-- Recent Requests -->
<section>
  <h2>Recent Requests</h2>
  <table><thead><tr><th>request</th><th>task</th><th>model</th><th>mode</th><th>preset</th><th>latency</th></tr></thead>
  <tbody id="recent"></tbody></table>
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

refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>
"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Self-contained dashboard: cost, learning, models, cache, capabilities."""
    return HTMLResponse(_DASHBOARD_HTML)
