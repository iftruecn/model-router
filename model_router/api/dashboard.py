"""
Cost & learning dashboard for Model Router v1.7.0.

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

  /* Language selector (v1.7.0) */
  .lang-bar { position:fixed; top:12px; right:24px; z-index:100; }
  .lang-bar select { background:var(--card); color:var(--fg); border:1px solid #3a3f52;
                     border-radius:6px; padding:4px 8px; font-size:12px; cursor:pointer; }
  .lang-bar select:hover { border-color:var(--blue); }
</style>
</head>
<body>
<div class="lang-bar">
  <select id="lang_selector" onchange="setLang(this.value)">
    <option value="en">English</option><option value="zh">中文</option>
    <option value="ja">日本語</option><option value="ko">한국어</option>
    <option value="es">Español</option><option value="fr">Français</option>
    <option value="de">Deutsch</option>
  </select>
</div>
<h1>🧠 <span data-i18n="title">Model Router — Dashboard</span></h1>
<div class="sub"><span data-i18n="auto_refresh">auto-refresh every 10s</span> · <a href="/docs" style="color:var(--blue)" data-i18n="api_docs">API docs</a> · <a href="/admin/models" style="color:var(--blue)" data-i18n="admin_api">Admin API</a></div>

<!-- Stats Cards -->
<div class="cards">
  <div class="card"><div class="label" data-i18n="estimated_savings">Estimated Savings</div>
    <div class="value green" id="savings">—</div></div>
  <div class="card"><div class="label" data-i18n="savings_rate">Savings Rate</div>
    <div class="value green" id="savings_pct">—</div></div>
  <div class="card"><div class="label" data-i18n="requests_routed">Requests Routed</div>
    <div class="value blue" id="requests">—</div></div>
  <div class="card"><div class="label" data-i18n="learning_mode">Learning Mode</div>
    <div class="value amber" id="mode">—</div></div>
  <div class="card"><div class="label" data-i18n="samples_learned">Samples Learned</div>
    <div class="value blue" id="samples">—</div></div>
  <div class="card"><div class="label" data-i18n="cache_hit_rate">Cache Hit Rate</div>
    <div class="value green" id="cache_rate">—</div></div>
</div>

<!-- Agent Views (v1.5.0) -->
<section>
  <h2 data-i18n="agent_views">Agent Views</h2>
  <div class="agent-tabs" id="agent_tabs">
    <button class="agent-tab active" onclick="switchAgent('all')" data-i18n="all">All</button>
  </div>
  <div id="agent_details">
    <div class="stat-row"><span class="stat-label">Loading...</span></div>
  </div>
</section>

<!-- Routing Preset -->
<section>
  <h2 data-i18n="routing_preset">Routing Preset</h2>
  <div id="presets"></div>
</section>

<!-- Two-column: Models + Cache/Capabilities -->
<div class="grid-2">

<!-- Models Management -->
<section>
  <h2><span data-i18n="models">Models</span> (<span id="model_count">—</span>)</h2>
  <table><thead><tr><th data-i18n="th_model">Model</th><th data-i18n="th_provider">Provider</th><th data-i18n="th_mode">Mode</th><th data-i18n="th_cost_1k">Cost/1K</th><th></th></tr></thead>
  <tbody id="models"></tbody></table>
</section>

<!-- Right column -->
<div>
<!-- Semantic Cache -->
<section>
  <h2 data-i18n="semantic_cache">Semantic Cache</h2>
  <div id="cache_stats">
    <div class="stat-row"><span class="stat-label">Loading...</span></div>
  </div>
</section>

<!-- Capabilities -->
<section>
  <h2 data-i18n="agent_capabilities">Agent Capabilities</h2>
  <div id="cap_stats">
    <div class="stat-row"><span class="stat-label">Loading...</span></div>
  </div>
</section>

<!-- Connection Pool -->
<section>
  <h2 data-i18n="system">System</h2>
  <div id="sys_stats">
    <div class="stat-row"><span class="stat-label">Loading...</span></div>
  </div>
</section>
</div>
</div>

<!-- Learned Model Performance -->
<section>
  <h2><span data-i18n="learned_perf">Learned Model Performance</span> (<span data-i18n="learned_subtitle">task → model</span>)</h2>
  <table><thead><tr><th data-i18n="th_pair">pair</th><th data-i18n="th_mean_reward">mean reward μ</th><th data-i18n="th_samples">samples n</th></tr></thead>
  <tbody id="learned"></tbody></table>
</section>

<!-- Human Feedback (v1.2.0) -->
<section>
  <h2 data-i18n="human_feedback">Human Feedback</h2>
  <div class="cards" style="margin-bottom:12px">
    <div class="card"><div class="label" data-i18n="total_feedback">Total Feedback</div>
      <div class="value blue" id="fb_total">—</div></div>
    <div class="card"><div class="label" data-i18n="positive">Positive</div>
      <div class="value green" id="fb_pos">—</div></div>
    <div class="card"><div class="label" data-i18n="negative">Negative</div>
      <div class="value amber" id="fb_neg">—</div></div>
    <div class="card"><div class="label" data-i18n="approval_rate">Approval Rate</div>
      <div class="value green" id="fb_rate">—</div></div>
  </div>
  <table><thead><tr><th data-i18n="th_request">request</th><th data-i18n="th_task">task</th><th data-i18n="th_model">model</th><th data-i18n="th_feedback">feedback</th></tr></thead>
  <tbody id="fb_recent"></tbody></table>
</section>

<!-- Recent Requests -->
<!-- Recent Requests -->
<section>
  <h2 data-i18n="recent_requests">Recent Requests</h2>
  <table><thead><tr><th data-i18n="th_request">request</th><th data-i18n="th_task">task</th><th data-i18n="th_model">model</th><th data-i18n="th_mode">mode</th><th data-i18n="th_preset">preset</th><th data-i18n="th_latency">latency</th></tr></thead>
  <tbody id="recent"></tbody></table>
</section>

<!-- Why-this-model Explain -->
<section>
  <h2 data-i18n="why_this_model">Why This Model?</h2>
  <div style="display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap">
    <div style="flex:1;min-width:200px">
      <textarea id="explain_input" class="explain-input" rows="2"
        data-i18n="explain_placeholder" placeholder="Enter request ID to lookup, or a message to dry-run..."></textarea>
    </div>
    <div style="display:flex;flex-direction:column;gap:4px">
      <button class="explain-btn" onclick="explainLookup()" data-i18n="lookup_btn">Lookup Request</button>
      <button class="explain-btn" onclick="explainDryRun()" style="background:#2a6a3a" data-i18n="dry_run_btn">Dry Run</button>
    </div>
  </div>
  <div id="explain_result" class="explain-result"></div>
</section>

<script>

const I18N={
en:{title:"Model Router \u2014 Dashboard",auto_refresh:"auto-refresh every 10s",api_docs:"API docs",admin_api:"Admin API",estimated_savings:"Estimated Savings",savings_rate:"Savings Rate",requests_routed:"Requests Routed",learning_mode:"Learning Mode",samples_learned:"Samples Learned",cache_hit_rate:"Cache Hit Rate",agent_views:"Agent Views",routing_preset:"Routing Preset",models:"Models",semantic_cache:"Semantic Cache",agent_capabilities:"Agent Capabilities",system:"System",learned_perf:"Learned Model Performance",learned_subtitle:"task \u2192 model",human_feedback:"Human Feedback",recent_requests:"Recent Requests",why_this_model:"Why This Model?",all:"All",loading:"Loading...",no_agents:"No agents installed. Run: model-router install",th_model:"Model",th_provider:"Provider",th_mode:"Mode",th_cost_1k:"Cost/1K",no_models:"No models registered",to_manual:"\u2192 manual",to_auto:"\u2192 auto",entries:"Entries",hit_rate:"Hit Rate",total_hits:"Total Hits",total_queries:"Total Queries",ttl:"TTL",similarity:"Similarity",no_caps:"No capabilities declared",declared:"declared",registry_mode:"Registry Mode",diversity:"Diversity",evaluator:"Evaluator",available:"available",th_pair:"pair",th_mean_reward:"mean reward \u03bc",th_samples:"samples n",no_learning:"No learning data yet",total_feedback:"Total Feedback",positive:"Positive",negative:"Negative",approval_rate:"Approval Rate",th_request:"request",th_task:"task",th_feedback:"feedback",no_feedback:"No feedback yet",th_preset:"preset",th_latency:"latency",no_requests:"No requests yet",explain_placeholder:"Enter request ID to lookup, or a message to dry-run...",lookup_btn:"Lookup Request",dry_run_btn:"Dry Run",enter_rid:"Enter a request ID",enter_msg:"Enter a message to test routing",requests:"Requests",fallbacks:"Fallbacks",observe_only:" (observe only)",language:"Language"},
zh:{title:"Model Router \u2014 \u4eea\u8868\u76d8",auto_refresh:"\u6bcf 10 \u79d2\u81ea\u52a8\u5237\u65b0",api_docs:"API \u6587\u6863",admin_api:"\u7ba1\u7406 API",estimated_savings:"\u9884\u8ba1\u8282\u7701",savings_rate:"\u8282\u7701\u7387",requests_routed:"\u5df2\u8def\u7531\u8bf7\u6c42",learning_mode:"\u5b66\u4e60\u6a21\u5f0f",samples_learned:"\u5df2\u5b66\u4e60\u6837\u672c",cache_hit_rate:"\u7f13\u5b58\u547d\u4e2d\u7387",agent_views:"Agent \u89c6\u56fe",routing_preset:"\u8def\u7531\u9884\u8bbe",models:"\u6a21\u578b",semantic_cache:"\u8bed\u4e49\u7f13\u5b58",agent_capabilities:"Agent \u80fd\u529b",system:"\u7cfb\u7edf",learned_perf:"\u5df2\u5b66\u4e60\u6a21\u578b\u8868\u73b0",learned_subtitle:"\u4efb\u52a1 \u2192 \u6a21\u578b",human_feedback:"\u4eba\u7c7b\u53cd\u9988",recent_requests:"\u6700\u8fd1\u8bf7\u6c42",why_this_model:"\u6a21\u578b\u9009\u62e9\u539f\u56e0",all:"\u5168\u90e8",loading:"\u52a0\u8f7d\u4e2d...",no_agents:"\u672a\u5b89\u88c5 Agent\u3002\u8bf7\u8fd0\u884c: model-router install",th_model:"\u6a21\u578b",th_provider:"\u63d0\u4f9b\u5546",th_mode:"\u6a21\u5f0f",th_cost_1k:"\u8d39\u7528/1K",no_models:"\u6682\u65e0\u6ce8\u518c\u6a21\u578b",to_manual:"\u2192 \u624b\u52a8",to_auto:"\u2192 \u81ea\u52a8",entries:"\u6761\u76ee\u6570",hit_rate:"\u547d\u4e2d\u7387",total_hits:"\u603b\u547d\u4e2d",total_queries:"\u603b\u67e5\u8be2",ttl:"\u8fc7\u671f\u65f6\u95f4",similarity:"\u76f8\u4f3c\u5ea6",no_caps:"\u672a\u58f0\u660e\u80fd\u529b",declared:"\u5df2\u58f0\u660e",registry_mode:"\u6ce8\u518c\u6a21\u5f0f",diversity:"\u591a\u6837\u6027",evaluator:"\u8bc4\u4f30\u5668",available:"\u53ef\u7528",th_pair:"\u914d\u5bf9",th_mean_reward:"\u5e73\u5747\u5956\u52b1 \u03bc",th_samples:"\u6837\u672c\u6570 n",no_learning:"\u6682\u65e0\u5b66\u4e60\u6570\u636e",total_feedback:"\u603b\u53cd\u9988\u6570",positive:"\u6b63\u9762",negative:"\u8d1f\u9762",approval_rate:"\u901a\u8fc7\u7387",th_request:"\u8bf7\u6c42",th_task:"\u4efb\u52a1",th_feedback:"\u53cd\u9988",no_feedback:"\u6682\u65e0\u53cd\u9988",th_preset:"\u9884\u8bbe",th_latency:"\u5ef6\u8fdf",no_requests:"\u6682\u65e0\u8bf7\u6c42",explain_placeholder:"\u8f93\u5165\u8bf7\u6c42 ID \u67e5\u8be2\uff0c\u6216\u8f93\u5165\u6d88\u606f\u8fdb\u884c\u6a21\u62df\u8def\u7531...",lookup_btn:"\u67e5\u8be2\u8bf7\u6c42",dry_run_btn:"\u6a21\u62df\u8def\u7531",enter_rid:"\u8bf7\u8f93\u5165\u8bf7\u6c42 ID",enter_msg:"\u8bf7\u8f93\u5165\u6d88\u606f\u4ee5\u6d4b\u8bd5\u8def\u7531",requests:"\u8bf7\u6c42\u6570",fallbacks:"\u56de\u9000\u6b21\u6570",observe_only:"\uff08\u4ec5\u89c2\u5bdf\uff09",language:"\u8bed\u8a00"},
ja:{title:"Model Router \u2014 \u30c0\u30c3\u30b7\u30e5\u30dc\u30fc\u30c9",auto_refresh:"10\u79d2\u3054\u3068\u306b\u81ea\u52d5\u66f4\u65b0",api_docs:"API\u30c9\u30ad\u30e5\u30e1\u30f3\u30c8",admin_api:"\u7ba1\u7406API",estimated_savings:"\u63a8\u5b9a\u7bc0\u7d04\u984d",savings_rate:"\u7bc0\u7d04\u7387",requests_routed:"\u30eb\u30fc\u30c6\u30a3\u30f3\u30b0\u6e08\u307f\u30ea\u30af\u30a8\u30b9\u30c8",learning_mode:"\u5b66\u7fd2\u30e2\u30fc\u30c9",samples_learned:"\u5b66\u7fd2\u30b5\u30f3\u30d7\u30eb\u6570",cache_hit_rate:"\u30ad\u30e3\u30c3\u30b7\u30e5\u30d2\u30c3\u30c8\u7387",agent_views:"\u30a8\u30fc\u30b8\u30a7\u30f3\u30c8\u30d3\u30e5\u30fc",routing_preset:"\u30eb\u30fc\u30c6\u30a3\u30f3\u30b0\u30d7\u30ea\u30bb\u30c3\u30c8",models:"\u30e2\u30c7\u30eb",semantic_cache:"\u30bb\u30de\u30f3\u30c6\u30a3\u30c3\u30af\u30ad\u30e3\u30c3\u30b7\u30e5",agent_capabilities:"\u30a8\u30fc\u30b8\u30a7\u30f3\u30c8\u6a5f\u80fd",system:"\u30b7\u30b9\u30c6\u30e0",learned_perf:"\u5b66\u7fd2\u6e08\u307f\u30e2\u30c7\u30eb\u30d1\u30d5\u30a9\u30fc\u30de\u30f3\u30b9",learned_subtitle:"\u30bf\u30b9\u30af \u2192 \u30e2\u30c7\u30eb",human_feedback:"\u30d2\u30e5\u30fc\u30de\u30f3\u30d5\u30a3\u30fc\u30c9\u30d0\u30c3\u30af",recent_requests:"\u6700\u8fd1\u306e\u30ea\u30af\u30a8\u30b9\u30c8",why_this_model:"\u3053\u306e\u30e2\u30c7\u30eb\u304c\u9078\u3070\u308c\u305f\u7406\u7531",all:"\u3059\u3079\u3066",loading:"\u8aad\u307f\u8fbc\u307f\u4e2d...",no_agents:"\u30a8\u30fc\u30b8\u30a7\u30f3\u30c8\u304c\u672a\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u3067\u3059\u3002\u5b9f\u884c: model-router install",th_model:"\u30e2\u30c7\u30eb",th_provider:"\u30d7\u30ed\u30d0\u30a4\u30c0\u30fc",th_mode:"\u30e2\u30fc\u30c9",th_cost_1k:"\u30b3\u30b9\u30c8/1K",no_models:"\u30e2\u30c7\u30eb\u672a\u767b\u9332",to_manual:"\u2192 \u624b\u52d5",to_auto:"\u2192 \u81ea\u52d5",entries:"\u30a8\u30f3\u30c8\u30ea\u6570",hit_rate:"\u30d2\u30c3\u30c8\u7387",total_hits:"\u7dcf\u30d2\u30c3\u30c8",total_queries:"\u7dcf\u30af\u30a8\u30ea",ttl:"TTL",similarity:"\u985e\u4f3c\u5ea6",no_caps:"\u6a5f\u80fd\u5ba3\u8a00\u306a\u3057",declared:"\u5ba3\u8a00\u6e08\u307f",registry_mode:"\u30ec\u30b8\u30b9\u30c8\u30ea\u30e2\u30fc\u30c9",diversity:"\u30c0\u30a4\u30d0\u30fc\u30b7\u30c6\u30a3",evaluator:"\u8a55\u4fa1\u5668",available:"\u5229\u7528\u53ef\u80fd",th_pair:"\u30da\u30a2",th_mean_reward:"\u5e73\u5747\u5831\u916c \u03bc",th_samples:"\u30b5\u30f3\u30d7\u30eb\u6570 n",no_learning:"\u5b66\u7fd2\u30c7\u30fc\u30bf\u306a\u3057",total_feedback:"\u7dcf\u30d5\u30a3\u30fc\u30c9\u30d0\u30c3\u30af\u6570",positive:"\u30dd\u30b8\u30c6\u30a3\u30d6",negative:"\u30cd\u30ac\u30c6\u30a3\u30d6",approval_rate:"\u627f\u8a8d\u7387",th_request:"\u30ea\u30af\u30a8\u30b9\u30c8",th_task:"\u30bf\u30b9\u30af",th_feedback:"\u30d5\u30a3\u30fc\u30c9\u30d0\u30c3\u30af",no_feedback:"\u30d5\u30a3\u30fc\u30c9\u30d0\u30c3\u30af\u306a\u3057",th_preset:"\u30d7\u30ea\u30bb\u30c3\u30c8",th_latency:"\u9045\u5ef6",no_requests:"\u30ea\u30af\u30a8\u30b9\u30c8\u306a\u3057",explain_placeholder:"\u30ea\u30af\u30a8\u30b9\u30c8ID\u307e\u305f\u306f\u30e1\u30c3\u30bb\u30fc\u30b8\u3092\u5165\u529b...",lookup_btn:"\u30ea\u30af\u30a8\u30b9\u30c8\u691c\u7d22",dry_run_btn:"\u30c9\u30e9\u30a4\u30e9\u30f3",enter_rid:"\u30ea\u30af\u30a8\u30b9\u30c8ID\u3092\u5165\u529b",enter_msg:"\u30eb\u30fc\u30c6\u30a3\u30f3\u30b0\u30c6\u30b9\u30c8\u7528\u30e1\u30c3\u30bb\u30fc\u30b8\u3092\u5165\u529b",requests:"\u30ea\u30af\u30a8\u30b9\u30c8\u6570",fallbacks:"\u30d5\u30a9\u30fc\u30eb\u30d0\u30c3\u30af",observe_only:"\uff08\u76e3\u8996\u306e\u307f\uff09",language:"\u8a00\u8a9e"},
ko:{title:"Model Router \u2014 \ub300\uc2dc\ubcf4\ub4dc",auto_refresh:"10\ucd08\ub9c8\ub2e4 \uc790\ub3d9 \uc0c8\ub85c\uace0\uce68",api_docs:"API \ubb38\uc11c",admin_api:"\uad00\ub9ac API",estimated_savings:"\uc608\uc0c1 \uc808\uac10\uc561",savings_rate:"\uc808\uac10\ub960",requests_routed:"\ub77c\uc6b0\ud305\ub41c \uc694\uccad",learning_mode:"\ud559\uc2b5 \ubaa8\ub4dc",samples_learned:"\ud559\uc2b5\ub41c \uc0d8\ud50c",cache_hit_rate:"\uce90\uc2dc \uc801\uc911\ub960",agent_views:"\uc5d0\uc774\uc804\ud2b8 \ubdf0",routing_preset:"\ub77c\uc6b0\ud305 \ud504\ub9ac\uc14b",models:"\ubaa8\ub378",semantic_cache:"\uc2dc\ub9e8\ud2f1 \uce90\uc2dc",agent_capabilities:"\uc5d0\uc774\uc804\ud2b8 \uae30\ub2a5",system:"\uc2dc\uc2a4\ud15c",learned_perf:"\ud559\uc2b5\ub41c \ubaa8\ub378 \uc131\ub2a5",learned_subtitle:"\uc791\uc5c5 \u2192 \ubaa8\ub378",human_feedback:"\uc0ac\uc6a9\uc790 \ud53c\ub4dc\ubc31",recent_requests:"\ucd5c\uadfc \uc694\uccad",why_this_model:"\uc774 \ubaa8\ub378\uc774 \uc120\ud0dd\ub41c \uc774\uc720",all:"\uc804\uccb4",loading:"\ub85c\ub529 \uc911...",no_agents:"\uc124\uce58\ub41c \uc5d0\uc774\uc804\ud2b8\uac00 \uc5c6\uc2b5\ub2c8\ub2e4. \uc2e4\ud589: model-router install",th_model:"\ubaa8\ub378",th_provider:"\uc81c\uacf5\uc790",th_mode:"\ubaa8\ub4dc",th_cost_1k:"\ube44\uc6a9/1K",no_models:"\ub4f1\ub85d\ub41c \ubaa8\ub378 \uc5c6\uc74c",to_manual:"\u2192 \uc218\ub3d9",to_auto:"\u2192 \uc790\ub3d9",entries:"\ud56d\ubaa9 \uc218",hit_rate:"\uc801\uc911\ub960",total_hits:"\ucd1d \uc801\uc911",total_queries:"\ucd1d \ucffc\ub9ac",ttl:"TTL",similarity:"\uc720\uc0ac\ub3c4",no_caps:"\uc120\uc5b8\ub41c \uae30\ub2a5 \uc5c6\uc74c",declared:"\uc120\uc5b8\ub428",registry_mode:"\ub808\uc9c0\uc2a4\ud2b8\ub9ac \ubaa8\ub4dc",diversity:"\ub2e4\uc591\uc131",evaluator:"\ud3c9\uac00\uae30",available:"\uc0ac\uc6a9 \uac00\ub2a5",th_pair:"\uc30d",th_mean_reward:"\ud3c9\uade0 \ubcf4\uc0c1 \u03bc",th_samples:"\uc0d8\ud50c \uc218 n",no_learning:"\ud559\uc2b5 \ub370\uc774\ud130 \uc5c6\uc74c",total_feedback:"\ucd1d \ud53c\ub4dc\ubc31",positive:"\uae0d\uc815",negative:"\ubd80\uc815",approval_rate:"\uc2b9\uc778\uc728",th_request:"\uc694\uccad",th_task:"\uc791\uc5c5",th_feedback:"\ud53c\ub4dc\ubc31",no_feedback:"\ud53c\ub4dc\ubc31 \uc5c6\uc74c",th_preset:"\ud504\ub9ac\uc14b",th_latency:"\uc9c0\uc5f0",no_requests:"\uc694\uccad \uc5c6\uc74c",explain_placeholder:"\uc694\uccad ID \ub610\ub294 \uba54\uc2dc\uc9c0\ub97c \uc785\ub825\ud558\uc138\uc694...",lookup_btn:"\uc694\uccad \uc870\ud68c",dry_run_btn:"\ub4dc\ub77c\uc774 \\ub7f0",enter_rid:"\uc694\uccad ID\ub97c \uc785\ub825\ud558\uc138\uc694",enter_msg:"\ub77c\uc6b0\ud305 \ud14c\uc2a4\ud2b8 \uba54\uc2dc\uc9c0\ub97c \uc785\ub825\ud558\uc138\uc694",requests:"\uc694\uccad \uc218",fallbacks:"\ud3f4\ubc31",observe_only:" (\uad00\ucc30\ub9cc)",language:"\uc5b8\uc5b4"},
es:{title:"Model Router \u2014 Panel",auto_refresh:"actualizaci\u00f3n autom\u00e1tica cada 10s",api_docs:"Docs API",admin_api:"API Admin",estimated_savings:"Ahorro estimado",savings_rate:"Tasa de ahorro",requests_routed:"Solicitudes enrutadas",learning_mode:"Modo aprendizaje",samples_learned:"Muestras aprendidas",cache_hit_rate:"Tasa de acierto cach\u00e9",agent_views:"Vistas de agente",routing_preset:"Preajuste de enrutamiento",models:"Modelos",semantic_cache:"Cach\u00e9 sem\u00e1ntico",agent_capabilities:"Capacidades del agente",system:"Sistema",learned_perf:"Rendimiento aprendido",learned_subtitle:"tarea \u2192 modelo",human_feedback:"Feedback humano",recent_requests:"Solicitudes recientes",why_this_model:"\u00bfPor qu\u00e9 este modelo?",all:"Todos",loading:"Cargando...",no_agents:"Sin agentes instalados. Ejecutar: model-router install",th_model:"Modelo",th_provider:"Proveedor",th_mode:"Modo",th_cost_1k:"Costo/1K",no_models:"Sin modelos registrados",to_manual:"\u2192 manual",to_auto:"\u2192 auto",entries:"Entradas",hit_rate:"Tasa de acierto",total_hits:"Aciertos totales",total_queries:"Consultas totales",ttl:"TTL",similarity:"Similitud",no_caps:"Sin capacidades declaradas",declared:"declarado",registry_mode:"Modo registro",diversity:"Diversidad",evaluator:"Evaluador",available:"disponible",th_pair:"par",th_mean_reward:"recompensa media \u03bc",th_samples:"muestras n",no_learning:"Sin datos de aprendizaje",total_feedback:"Feedback total",positive:"Positivo",negative:"Negativo",approval_rate:"Tasa aprobaci\u00f3n",th_request:"solicitud",th_task:"tarea",th_feedback:"feedback",no_feedback:"Sin feedback a\u00fan",th_preset:"preajuste",th_latency:"latencia",no_requests:"Sin solicitudes a\u00fan",explain_placeholder:"Ingrese ID de solicitud o mensaje para probar...",lookup_btn:"Buscar solicitud",dry_run_btn:"Prueba seca",enter_rid:"Ingrese un ID de solicitud",enter_msg:"Ingrese un mensaje para probar enrutamiento",requests:"Solicitudes",fallbacks:"Fallbacks",observe_only:" (solo observar)",language:"Idioma"},
fr:{title:"Model Router \u2014 Tableau de bord",auto_refresh:"rafra\u00eechissement auto toutes les 10s",api_docs:"Docs API",admin_api:"API Admin",estimated_savings:"\u00c9conomies estim\u00e9es",savings_rate:"Taux d'\u00e9conomie",requests_routed:"Requ\u00eates rout\u00e9es",learning_mode:"Mode apprentissage",samples_learned:"\u00c9chantillons appris",cache_hit_rate:"Taux de hit cache",agent_views:"Vues agent",routing_preset:"Pr\u00e9r\u00e9glage routage",models:"Mod\u00e8les",semantic_cache:"Cache s\u00e9mantique",agent_capabilities:"Capacit\u00e9s agent",system:"Syst\u00e8me",learned_perf:"Performance apprise",learned_subtitle:"t\u00e2che \u2192 mod\u00e8le",human_feedback:"Feedback humain",recent_requests:"Requ\u00eates r\u00e9centes",why_this_model:"Pourquoi ce mod\u00e8le ?",all:"Tous",loading:"Chargement...",no_agents:"Aucun agent install\u00e9. Ex\u00e9cuter : model-router install",th_model:"Mod\u00e8le",th_provider:"Fournisseur",th_mode:"Mode",th_cost_1k:"Co\u00fbt/1K",no_models:"Aucun mod\u00e8le enregistr\u00e9",to_manual:"\u2192 manuel",to_auto:"\u2192 auto",entries:"Entr\u00e9es",hit_rate:"Taux de hit",total_hits:"Hits totaux",total_queries:"Requ\u00eates totales",ttl:"TTL",similarity:"Similarit\u00e9",no_caps:"Aucune capacit\u00e9 d\u00e9clar\u00e9e",declared:"d\u00e9clar\u00e9",registry_mode:"Mode registre",diversity:"Diversit\u00e9",evaluator:"\u00c9valuateur",available:"disponible",th_pair:"paire",th_mean_reward:"r\u00e9compense moy. \u03bc",th_samples:"\u00e9chantillons n",no_learning:"Aucune donn\u00e9e d'apprentissage",total_feedback:"Feedback total",positive:"Positif",negative:"N\u00e9gatif",approval_rate:"Taux approbation",th_request:"requ\u00eate",th_task:"t\u00e2che",th_feedback:"feedback",no_feedback:"Aucun feedback",th_preset:"pr\u00e9r\u00e9glage",th_latency:"latence",no_requests:"Aucune requ\u00eate",explain_placeholder:"Entrez un ID de requ\u00eate ou un message \u00e0 tester...",lookup_btn:"Rechercher requ\u00eate",dry_run_btn:"Test simul\u00e9",enter_rid:"Entrez un ID de requ\u00eate",enter_msg:"Entrez un message pour tester le routage",requests:"Requ\u00eates",fallbacks:"Replis",observe_only:" (observation seule)",language:"Langue"},
de:{title:"Model Router \u2014 Dashboard",auto_refresh:"Auto-Aktualisierung alle 10s",api_docs:"API-Dokumentation",admin_api:"Admin-API",estimated_savings:"Gesch\u00e4tzte Einsparung",savings_rate:"Sparrate",requests_routed:"Weitergeleitete Anfragen",learning_mode:"Lernmodus",samples_learned:"Gelernte Beispiele",cache_hit_rate:"Cache-Trefferrate",agent_views:"Agent-Ansichten",routing_preset:"Routing-Voreinstellung",models:"Modelle",semantic_cache:"Semantischer Cache",agent_capabilities:"Agent-F\u00e4higkeiten",system:"System",learned_perf:"Gelernte Modellleistung",learned_subtitle:"Aufgabe \u2192 Modell",human_feedback:"Menschliches Feedback",recent_requests:"Letzte Anfragen",why_this_model:"Warum dieses Modell?",all:"Alle",loading:"Laden...",no_agents:"Keine Agenten installiert. Ausf\u00fchren: model-router install",th_model:"Modell",th_provider:"Anbieter",th_mode:"Modus",th_cost_1k:"Kosten/1K",no_models:"Keine Modelle registriert",to_manual:"\u2192 manuell",to_auto:"\u2192 auto",entries:"Eintr\u00e4ge",hit_rate:"Trefferquote",total_hits:"Gesamthits",total_queries:"Gesamtanfragen",ttl:"TTL",similarity:"\u00c4hnlichkeit",no_caps:"Keine F\u00e4higkeiten deklariert",declared:"deklariert",registry_mode:"Registrierungsmodus",diversity:"Vielfalt",evaluator:"Bewerter",available:"verf\u00fcgbar",th_pair:"Paar",th_mean_reward:"mittlere Belohnung \u03bc",th_samples:"Beispiele n",no_learning:"Keine Lerndaten vorhanden",total_feedback:"Feedback gesamt",positive:"Positiv",negative:"Negativ",approval_rate:"Zustimmungsrate",th_request:"Anfrage",th_task:"Aufgabe",th_feedback:"Feedback",no_feedback:"Noch kein Feedback",th_preset:"Voreinstellung",th_latency:"Latenz",no_requests:"Noch keine Anfragen",explain_placeholder:"Anfrage-ID oder Nachricht eingeben...",lookup_btn:"Anfrage suchen",dry_run_btn:"Trockenlauf",enter_rid:"Anfrage-ID eingeben",enter_msg:"Nachricht zum Testen des Routings eingeben",requests:"Anfragen",fallbacks:"Fallbacks",observe_only:" (nur Beobachtung)",language:"Sprache"}
};
const I18N_LANG_NAMES={en:"English",zh:"\u4e2d\u6587",ja:"\u65e5\u672c\u8a9e",ko:"\ud55c\uad6d\uc5b4",es:"Espa\u00f1ol",fr:"Fran\u00e7ais",de:"Deutsch"};
function t(k){const l=window._mrLang||'en';return(I18N[l]&&I18N[l][k])||I18N.en[k]||k}
function detectLang(){const p=new URLSearchParams(window.location.search);const u=p.get('lang');if(u&&I18N[u])return u;const s=localStorage.getItem('mr_lang');if(s&&I18N[s])return s;const n=(navigator.language||'en').split('-')[0].toLowerCase();if(I18N[n])return n;return'en'}
function setLang(l){if(!I18N[l])return;window._mrLang=l;localStorage.setItem('mr_lang',l);applyI18n();const s=document.getElementById('lang_selector');if(s)s.value=l}
function applyI18n(){document.querySelectorAll('[data-i18n]').forEach(el=>{const k=el.getAttribute('data-i18n');const v=t(k);if(el.tagName==='INPUT'||el.tagName==='TEXTAREA')el.placeholder=v;else el.textContent=v});document.title=t('title');document.documentElement.lang=window._mrLang||'en'}
window._mrLang=detectLang();

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
      (l.mode || 'static') + (l.active ? '' : t('observe_only'));
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
      (m.selection_mode === 'auto' ? t('to_manual') : t('to_auto')) + '</button></td></tr>'
    ).join('') || '<tr><td colspan="5" style="color:var(--dim)">' + t('no_models') + '</td></tr>';

    // Cache stats
    document.getElementById('cache_stats').innerHTML = [
      sr(t('entries'), (cacheData.entries ?? 0) + ' / ' + (cacheData.capacity ?? '?')),
      sr(t('hit_rate'), ((cacheData.hit_rate ?? 0) * 100).toFixed(1) + '%'),
      sr(t('total_hits'), cacheData.total_hits ?? 0),
      sr(t('total_queries'), cacheData.total_queries ?? 0),
      sr(t('ttl'), (cacheData.ttl_seconds ?? 0) + 's'),
      sr(t('similarity'), cacheData.sim_threshold ?? '?'),
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
      sr(t('registry_mode'), capData.registry_mode || '—'),
      sr(t('diversity'), (learn.diversity || {}).status || '—'),
      sr(t('evaluator'), t('available')),
    ].join('');

    // Learned table
    document.getElementById('learned').innerHTML = (l.top_learned || []).map(r =>
      '<tr><td>' + esc(r.pair.replace('|', ' \u2192 ')) + '</td><td>' + r.mu.toFixed(3) +
      '</td><td>' + r.n + '</td></tr>').join('') ||
      '<tr><td colspan="3" style="color:var(--dim)">' + t('no_learning') + '</td></tr>';
    
    // Recent requests (with latency)
    document.getElementById('recent').innerHTML = (learn.recent_requests || []).map(r =>
      '<tr><td>' + esc((r.request_id || '').slice(0, 8)) + '</td><td>' + esc(r.task || '') +
      '</td><td>' + esc(r.final_model || '') + '</td><td><span class="badge">' +
      esc(r.routing_mode || '') + '</span></td><td>' + esc(r.preset || '') + '</td><td>' +
      (r.latency_ms ? r.latency_ms.toFixed(0) + 'ms' : '\u2014') + '</td></tr>')
      .reverse().join('') ||
      '<tr><td colspan="6" style="color:var(--dim)">' + t('no_requests') + '</td></tr>';
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
      '<tr><td colspan="4" style="color:var(--dim)">' + t('no_feedback') + '</td></tr>';

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
    '<div style="color:var(--amber)">' + t('enter_rid') + '</div>'; return; }
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
    '<div style="color:var(--amber)">' + t('enter_msg') + '</div>'; return; }
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
      '" onclick="switchAgent(\'all\')">' + t('all') + '</button>';
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
  html += '<span>' + t('requests') + ': <span class="val">' + (usage.requests || 0) + '</span></span>';
  html += '<span>' + t('fallbacks') + ': <span class="val">' + (usage.fallbacks || 0) + '</span></span>';
  html += '<span>' + t('models') + ': <span class="val">' + models.length + '</span></span>';
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

// Initialize i18n
document.getElementById('lang_selector').value = window._mrLang;
applyI18n();
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
