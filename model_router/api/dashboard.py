"""
Cost & learning dashboard for Model Router v1.8.0.

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
    <option value="en">English</option>
    <option value="zh">中文</option>
    <option value="ja">日本語</option>
    <option value="ko">한국어</option>
    <option value="es">Español</option>
    <option value="fr">Français</option>
    <option value="de">Deutsch</option>
  </select>
</div>
<h1>🧠 <span data-i18n="title">Model Router — Dashboard</span></h1>
<div class="sub"><span data-i18n="auto_refresh">auto-refresh every 10s</span> · <a href="/docs" style="color:var(--blue)" data-i18n="api_docs">API docs</a> · <a href="/admin" style="color:var(--blue)" data-i18n="admin_api">Admin API</a></div>

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
en:{title:"Model Router \u2014 Dashboard",auto_refresh:"auto-refresh every 10s",api_docs:"API docs",admin_api:"Admin API",estimated_savings:"Estimated Savings",savings_rate:"Savings Rate",requests_routed:"Requests Routed",learning_mode:"Learning Mode",samples_learned:"Samples Learned",cache_hit_rate:"Cache Hit Rate",agent_views:"Agent Views",routing_preset:"Routing Preset",models:"Models",semantic_cache:"Semantic Cache",agent_capabilities:"Agent Capabilities",system:"System",learned_perf:"Learned Model Performance",learned_subtitle:"task \u2192 model",human_feedback:"Human Feedback",recent_requests:"Recent Requests",why_this_model:"Why This Model?",all:"All",loading:"Loading...",no_agents:"No agents installed. Run: model-router install",th_model:"Model",th_provider:"Provider",th_mode:"Mode",th_cost_1k:"Cost/1K",no_models:"No models registered",to_manual:"\u2192 manual",to_auto:"\u2192 auto",entries:"Entries",hit_rate:"Hit Rate",total_hits:"Total Hits",total_queries:"Total Queries",ttl:"TTL",similarity:"Similarity",no_caps:"No capabilities declared",declared:"declared",registry_mode:"Registry Mode",diversity:"Diversity",evaluator:"Evaluator",available:"available",th_pair:"pair",th_mean_reward:"mean reward \u03bc",th_samples:"samples n",no_learning:"No learning data yet",total_feedback:"Total Feedback",positive:"Positive",negative:"Negative",approval_rate:"Approval Rate",th_request:"request",th_task:"task",th_feedback:"feedback",no_feedback:"No feedback yet",th_preset:"preset",th_latency:"latency",no_requests:"No requests yet",explain_placeholder:"Enter request ID to lookup, or a message to dry-run...",lookup_btn:"Lookup Request",dry_run_btn:"Dry Run",enter_rid:"Enter a request ID",enter_msg:"Enter a message to test routing",requests:"Requests",fallbacks:"Fallbacks",observe_only:" (observe only)",language:"Language",score_lbl:"score: ",task_lbl:"task: ",dry_run_lbl:"[dry run]",actual_cost:"Actual cost: $",estimated_cost:" | Estimated: $",baseline_cost:" | Baseline: $",latency_lbl:" | Latency: ",tokens_lbl:" | Tokens: ",top_candidates:"Top Candidates (",capability_lbl:"capability: ",cost_lbl:"cost: ",speed_lbl:"speed: ",learned_lbl:"learned: ",total_lbl:"total: ",fallback_chain:"Fallback chain: ",not_found:"Not found",error_lbl:"Error: "},
zh:{title:"Model Router \u2014 \u4eea\u8868\u76d8",auto_refresh:"\u6bcf 10 \u79d2\u81ea\u52a8\u5237\u65b0",api_docs:"API \u6587\u6863",admin_api:"\u7ba1\u7406 API",estimated_savings:"\u9884\u8ba1\u8282\u7701",savings_rate:"\u8282\u7701\u7387",requests_routed:"\u5df2\u8def\u7531\u8bf7\u6c42",learning_mode:"\u5b66\u4e60\u6a21\u5f0f",samples_learned:"\u5df2\u5b66\u4e60\u6837\u672c",cache_hit_rate:"\u7f13\u5b58\u547d\u4e2d\u7387",agent_views:"Agent \u89c6\u56fe",routing_preset:"\u8def\u7531\u9884\u8bbe",models:"\u6a21\u578b",semantic_cache:"\u8bed\u4e49\u7f13\u5b58",agent_capabilities:"Agent \u80fd\u529b",system:"\u7cfb\u7edf",learned_perf:"\u5df2\u5b66\u4e60\u6a21\u578b\u8868\u73b0",learned_subtitle:"\u4efb\u52a1 \u2192 \u6a21\u578b",human_feedback:"\u4eba\u7c7b\u53cd\u9988",recent_requests:"\u6700\u8fd1\u8bf7\u6c42",why_this_model:"\u6a21\u578b\u9009\u62e9\u539f\u56e0",all:"\u5168\u90e8",loading:"\u52a0\u8f7d\u4e2d...",no_agents:"\u672a\u5b89\u88c5 Agent\u3002\u8bf7\u8fd0\u884c: model-router install",th_model:"\u6a21\u578b",th_provider:"\u63d0\u4f9b\u5546",th_mode:"\u6a21\u5f0f",th_cost_1k:"\u8d39\u7528/1K",no_models:"\u6682\u65e0\u6ce8\u518c\u6a21\u578b",to_manual:"\u2192 \u624b\u52a8",to_auto:"\u2192 \u81ea\u52a8",entries:"\u6761\u76ee\u6570",hit_rate:"\u547d\u4e2d\u7387",total_hits:"\u603b\u547d\u4e2d",total_queries:"\u603b\u67e5\u8be2",ttl:"\u8fc7\u671f\u65f6\u95f4",similarity:"\u76f8\u4f3c\u5ea6",no_caps:"\u672a\u58f0\u660e\u80fd\u529b",declared:"\u5df2\u58f0\u660e",registry_mode:"\u6ce8\u518c\u6a21\u5f0f",diversity:"\u591a\u6837\u6027",evaluator:"\u8bc4\u4f30\u5668",available:"\u53ef\u7528",th_pair:"\u914d\u5bf9",th_mean_reward:"\u5e73\u5747\u5956\u52b1 \u03bc",th_samples:"\u6837\u672c\u6570 n",no_learning:"\u6682\u65e0\u5b66\u4e60\u6570\u636e",total_feedback:"\u603b\u53cd\u9988\u6570",positive:"\u6b63\u9762",negative:"\u8d1f\u9762",approval_rate:"\u901a\u8fc7\u7387",th_request:"\u8bf7\u6c42",th_task:"\u4efb\u52a1",th_feedback:"\u53cd\u9988",no_feedback:"\u6682\u65e0\u53cd\u9988",th_preset:"\u9884\u8bbe",th_latency:"\u5ef6\u8fdf",no_requests:"\u6682\u65e0\u8bf7\u6c42",explain_placeholder:"\u8f93\u5165\u8bf7\u6c42 ID \u67e5\u8be2\uff0c\u6216\u8f93\u5165\u6d88\u606f\u8fdb\u884c\u6a21\u62df\u8def\u7531...",lookup_btn:"\u67e5\u8be2\u8bf7\u6c42",dry_run_btn:"\u6a21\u62df\u8def\u7531",enter_rid:"\u8bf7\u8f93\u5165\u8bf7\u6c42 ID",enter_msg:"\u8bf7\u8f93\u5165\u6d88\u606f\u4ee5\u6d4b\u8bd5\u8def\u7531",requests:"\u8bf7\u6c42\u6570",fallbacks:"\u56de\u9000\u6b21\u6570",observe_only:"\uff08\u4ec5\u89c2\u5bdf\uff09",language:"\u8bed\u8a00",score_lbl:"\u5f97\u5206: ",task_lbl:"\u4efb\u52a1: ",dry_run_lbl:"[\u6a21\u62df]",actual_cost:"\u5b9e\u9645\u8d39\u7528: $",estimated_cost:" | \u9884\u4f30: $",baseline_cost:" | \u57fa\u7ebf: $",latency_lbl:" | \u5ef6\u8fdf: ",tokens_lbl:" | Token: ",top_candidates:"\u5019\u9009\u6a21\u578b (",capability_lbl:"\u80fd\u529b: ",cost_lbl:"\u8d39\u7528: ",speed_lbl:"\u901f\u5ea6: ",learned_lbl:"\u5b66\u4e60: ",total_lbl:"\u603b\u8ba1: ",fallback_chain:"\u56de\u9000\u94fe: ",not_found:"\u672a\u627e\u5230",error_lbl:"\u9519\u8bef: "},

ja:{title:"Model Router — ダッシュボード",auto_refresh:"10秒ごとに自動更新",api_docs:"APIドキュメント",admin_api:"管理API",estimated_savings:"推定コスト削減",savings_rate:"削減率",requests_routed:"ルーティング済みリクエスト",learning_mode:"学習モード",samples_learned:"学習サンプル数",cache_hit_rate:"キャッシュヒット率",agent_views:"エージェントビュー",routing_preset:"ルーティングプリセット",models:"モデル",semantic_cache:"セマンティックキャッシュ",agent_capabilities:"エージェント機能",system:"システム",learned_perf:"学習済みモデルパフォーマンス",learned_subtitle:"タスク → モデル",human_feedback:"人間フィードバック",recent_requests:"最近のリクエスト",why_this_model:"なぜこのモデル？",all:"全て",loading:"読み込み中...",no_agents:"エージェントがインストールされていません。実行: model-router install",th_model:"モデル",th_provider:"プロバイダー",th_mode:"モード",th_cost_1k:"コスト/1K",no_models:"モデルが登録されていません",to_manual:"→ 手動",to_auto:"→ 自動",entries:"エントリー数",hit_rate:"ヒット率",total_hits:"トータルヒット",total_queries:"トータルクエリ",ttl:"有効期間",similarity:"類似度",no_caps:"機能が宣言されていません",declared:"宣言済み",registry_mode:"レジストリモード",diversity:"多樣性",evaluator:"評価ツール",available:"利用可能",th_pair:"ペア",th_mean_reward:"平均報酬 μ",th_samples:"サンプル数 n",no_learning:"学習データがありません",total_feedback:"トータルフィードバック",positive:"肯定",negative:"否定",approval_rate:"承認率",th_request:"リクエスト",th_task:"タスク",th_feedback:"フィードバック",no_feedback:"フィードバックがありません",th_preset:"プリセット",th_latency:"レイテンシ",no_requests:"リクエストがありません",explain_placeholder:"リクエストIDを入力して検索、またはメッセージを入力してドライラン...",lookup_btn:"リクエスト検索",dry_run_btn:"ドライラン",enter_rid:"リクエストIDを入力",enter_msg:"メッセージを入力してルーティングをテスト",requests:"リクエスト数",fallbacks:"フォールバック数",observe_only:"（観渡モード）",language:"言語",score_lbl:"スコア: ",task_lbl:"タスク: ",dry_run_lbl:"[ドライラン]",actual_cost:"実際コスト: $",estimated_cost:" | 推定: $",baseline_cost:" | ベースライン: $",latency_lbl:" | レイテンシ: ",tokens_lbl:" | トークン: ",top_candidates:"候訜モデル (",capability_lbl:"機能: ",cost_lbl:"コスト: ",speed_lbl:"スピード: ",learned_lbl:"学習: ",total_lbl:"合計: ",fallback_chain:"フォールバックチェーン: ",not_found:"見つかりません",error_lbl:"エラー: "},
ko:{title:"Model Router — 대시보드",auto_refresh:"10초마다 자동 새로고침",api_docs:"API 문서",admin_api:"관리자 API",estimated_savings:"추정 절약량",savings_rate:"절약률",requests_routed:"라우팅 된 요청",learning_mode:"학습 모드",samples_learned:"학습된 샘플",cache_hit_rate:"캐시 히트율",agent_views:"에이전트 뷰",routing_preset:"라우팅 프리셋",models:"모델",semantic_cache:"세맨틱 캐시",agent_capabilities:"에이전트 기능",system:"시스템",learned_perf:"학습된 모델 성능",learned_subtitle:"작업 → 모델",human_feedback:"사람 피드백",recent_requests:"최근 요청",why_this_model:"왜 이 모델인가?",all:"전체",loading:"로딩 중...",no_agents:"에이전트가 설치되지 않았습니다. 실행: model-router install",th_model:"모델",th_provider:"제공자",th_mode:"모드",th_cost_1k:"비용/1K",no_models:"등록된 모델이 없습니다",to_manual:"→ 수동",to_auto:"→ 자동",entries:"항목 수",hit_rate:"히트율",total_hits:"총 히트",total_queries:"총 쿼리",ttl:"만료 시간",similarity:"유사도",no_caps:"선언된 기능이 없습니다",declared:"선언됨",registry_mode:"레지스트리 모드",diversity:"다양성",evaluator:"평가 도구",available:"사용 가능",th_pair:"페어",th_mean_reward:"평균 보상 μ",th_samples:"샘플 수 n",no_learning:"학습 데이터가 없습니다",total_feedback:"총 피드백",positive:"긍정",negative:"부정",approval_rate:"승인율",th_request:"요청",th_task:"작업",th_feedback:"피드백",no_feedback:"피드백이 없습니다",th_preset:"프리셋",th_latency:"레이텐시",no_requests:"요청이 없습니다",explain_placeholder:"요청 ID를 입력하거나 메시지를 입력하여 드라이런 실행...",lookup_btn:"요청 검색",dry_run_btn:"드라이런",enter_rid:"요청 ID를 입력하세요",enter_msg:"라우팅 테스트를 위해 메시지를 입력하세요",requests:"요청 수",fallbacks:"폴백 횟수",observe_only:"(관찰 모드)",language:"언어",score_lbl:"점수: ",task_lbl:"작업: ",dry_run_lbl:"[드라이런]",actual_cost:"실제 비용: $",estimated_cost:" | 추정: $",baseline_cost:" | 기준: $",latency_lbl:" | 레이텐시: ",tokens_lbl:" | 토큰: ",top_candidates:"후보 모델 (",capability_lbl:"기능: ",cost_lbl:"비용: ",speed_lbl:"속도: ",learned_lbl:"학습: ",total_lbl:"합계: ",fallback_chain:"폴백 체인: ",not_found:"찾을 수 없습니다",error_lbl:"오류: "},
es:{title:"Model Router — Panel",auto_refresh:"actualización automática cada 10s",api_docs:"Docs API",admin_api:"API Admin",estimated_savings:"Ahorro estimado",savings_rate:"Tasa de ahorro",requests_routed:"Solicitudes enrutadas",learning_mode:"Modo aprendizaje",samples_learned:"Muestras aprendidas",cache_hit_rate:"Tasa de acierto de caché",agent_views:"Vistas de agente",routing_preset:"Preajuste de enrutamiento",models:"Modelos",semantic_cache:"Caché semántica",agent_capabilities:"Capacidades del agente",system:"Sistema",learned_perf:"Rendimiento aprendido",learned_subtitle:"tarea → modelo",human_feedback:"Retroalimentación humana",recent_requests:"Solicitudes recientes",why_this_model:"¿Por qué este modelo?",all:"Todos",loading:"Cargando...",no_agents:"No hay agentes instalados. Ejecutar: model-router install",th_model:"Modelo",th_provider:"Proveedor",th_mode:"Modo",th_cost_1k:"Costo/1K",no_models:"No hay modelos registrados",to_manual:"→ manual",to_auto:"→ auto",entries:"Entradas",hit_rate:"Tasa de acierto",total_hits:"Aciertos totales",total_queries:"Consultas totales",ttl:"TTL",similarity:"Similitud",no_caps:"No hay capacidades declaradas",declared:"declarado",registry_mode:"Modo registro",diversity:"Diversidad",evaluator:"Evaluador",available:"disponible",th_pair:"par",th_mean_reward:"recompensa media μ",th_samples:"muestras n",no_learning:"No hay datos de aprendizaje",total_feedback:"Retroalimentación total",positive:"Positivo",negative:"Negativo",approval_rate:"Tasa de aprobación",th_request:"solicitud",th_task:"tarea",th_feedback:"retroalimentación",no_feedback:"No hay retroalimentación",th_preset:"preajuste",th_latency:"latencia",no_requests:"No hay solicitudes",explain_placeholder:"Ingrese ID de solicitud o un mensaje para prueba en seco...",lookup_btn:"Buscar solicitud",dry_run_btn:"Prueba en seco",enter_rid:"Ingrese un ID de solicitud",enter_msg:"Ingrese un mensaje para probar el enrutamiento",requests:"Solicitudes",fallbacks:"Recursos alternativos",observe_only:"(solo observación)",language:"Idioma",score_lbl:"puntuación: ",task_lbl:"tarea: ",dry_run_lbl:"[prueba]",actual_cost:"Costo real: $",estimated_cost:" | Estimado: $",baseline_cost:" | Base: $",latency_lbl:" | Latencia: ",tokens_lbl:" | Tokens: ",top_candidates:"Candidatos (",capability_lbl:"capacidad: ",cost_lbl:"costo: ",speed_lbl:"velocidad: ",learned_lbl:"aprendido: ",total_lbl:"total: ",fallback_chain:"Cadena alternativa: ",not_found:"No encontrado",error_lbl:"Error: "},
fr:{title:"Model Router — Tableau de bord",auto_refresh:"rafraîchissement auto toutes les 10s",api_docs:"Docs API",admin_api:"API Admin",estimated_savings:"Économies estimées",savings_rate:"Taux d'économie",requests_routed:"Requêtes routées",learning_mode:"Mode apprentissage",samples_learned:"Échantillons appris",cache_hit_rate:"Taux de hit cache",agent_views:"Vues agent",routing_preset:"Préréglage routage",models:"Modèles",semantic_cache:"Cache sémantique",agent_capabilities:"Capacités agent",system:"Système",learned_perf:"Performance apprise",learned_subtitle:"tâche → modèle",human_feedback:"Retour humain",recent_requests:"Requêtes récentes",why_this_model:"Pourquoi ce modèle ?",all:"Tous",loading:"Chargement...",no_agents:"Aucun agent installé. Exécuter : model-router install",th_model:"Modèle",th_provider:"Fournisseur",th_mode:"Mode",th_cost_1k:"Coût/1K",no_models:"Aucun modèle enregistré",to_manual:"→ manuel",to_auto:"→ auto",entries:"Entrées",hit_rate:"Taux de hit",total_hits:"Hits totaux",total_queries:"Requêtes totales",ttl:"Durée de vie",similarity:"Similarité",no_caps:"Aucune capacité déclarée",declared:"déclaré",registry_mode:"Mode registre",diversity:"Diversité",evaluator:"Évaluateur",available:"disponible",th_pair:"paire",th_mean_reward:"récompense moyenne μ",th_samples:"échantillons n",no_learning:"Aucune donnée d'apprentissage",total_feedback:"Retour total",positive:"Positif",negative:"Négatif",approval_rate:"Taux d'approbation",th_request:"requête",th_task:"tâche",th_feedback:"retour",no_feedback:"Aucun retour",th_preset:"préréglage",th_latency:"latence",no_requests:"Aucune requête",explain_placeholder:"Entrez un ID de requête ou un message pour un test à blanc...",lookup_btn:"Rechercher requête",dry_run_btn:"Test à blanc",enter_rid:"Entrez un ID de requête",enter_msg:"Entrez un message pour tester le routage",requests:"Requêtes",fallbacks:"Replis",observe_only:"(observation seule)",language:"Langue",score_lbl:"score : ",task_lbl:"tâche : ",dry_run_lbl:"[test]",actual_cost:"Coût réel : $",estimated_cost:" | Estimé : $",baseline_cost:" | Base : $",latency_lbl:" | Latence : ",tokens_lbl:" | Tokens : ",top_candidates:"Candidats (",capability_lbl:"capacité : ",cost_lbl:"coût : ",speed_lbl:"vitesse : ",learned_lbl:"appris : ",total_lbl:"total : ",fallback_chain:"Chaîne de repli : ",not_found:"Non trouvé",error_lbl:"Erreur : "},
de:{title:"Model Router — Dashboard",auto_refresh:"Auto-Aktualisierung alle 10s",api_docs:"API-Dokumentation",admin_api:"Admin-API",estimated_savings:"Geschätzte Einsparungen",savings_rate:"Einsparungsrate",requests_routed:"Geroutete Anfragen",learning_mode:"Lernmodus",samples_learned:"Gelernte Samples",cache_hit_rate:"Cache-Trefferquote",agent_views:"Agent-Ansichten",routing_preset:"Routing-Voreinstellung",models:"Modelle",semantic_cache:"Semantischer Cache",agent_capabilities:"Agent-Fähigkeiten",system:"System",learned_perf:"Gelernte Modellleistung",learned_subtitle:"Aufgabe → Modell",human_feedback:"Menschliches Feedback",recent_requests:"Letzte Anfragen",why_this_model:"Warum dieses Modell?",all:"Alle",loading:"Laden...",no_agents:"Keine Agenten installiert. Ausführen: model-router install",th_model:"Modell",th_provider:"Anbieter",th_mode:"Modus",th_cost_1k:"Kosten/1K",no_models:"Keine Modelle registriert",to_manual:"→ manuell",to_auto:"→ auto",entries:"Einträge",hit_rate:"Trefferquote",total_hits:"Gesamttreffer",total_queries:"Gesamtabfragen",ttl:"TTL",similarity:"Ähnlichkeit",no_caps:"Keine Fähigkeiten deklariert",declared:"deklariert",registry_mode:"Registry-Modus",diversity:"Vielfalt",evaluator:"Bewerter",available:"verfügbar",th_pair:"Paar",th_mean_reward:"mittlere Belohnung μ",th_samples:"Samples n",no_learning:"Keine Lerndaten",total_feedback:"Gesamtfeedback",positive:"Positiv",negative:"Negativ",approval_rate:"Zustimmungsrate",th_request:"Anfrage",th_task:"Aufgabe",th_feedback:"Feedback",no_feedback:"Kein Feedback",th_preset:"Voreinstellung",th_latency:"Latenz",no_requests:"Keine Anfragen",explain_placeholder:"Anfrage-ID eingeben oder Nachricht für Dry-Run eingeben...",lookup_btn:"Anfrage suchen",dry_run_btn:"Dry Run",enter_rid:"Anfrage-ID eingeben",enter_msg:"Nachricht eingeben um Routing zu testen",requests:"Anfragen",fallbacks:"Fallbacks",observe_only:"(nur beobachten)",language:"Sprache",score_lbl:"Punkte: ",task_lbl:"Aufgabe: ",dry_run_lbl:"[Dry Run]",actual_cost:"Tatsächliche Kosten: $",estimated_cost:" | Geschätzt: $",baseline_cost:" | Baseline: $",latency_lbl:" | Latenz: ",tokens_lbl:" | Tokens: ",top_candidates:"Kandidaten (",capability_lbl:"Fähigkeit: ",cost_lbl:"Kosten: ",speed_lbl:"Geschwindigkeit: ",learned_lbl:"gelernt: ",total_lbl:"gesamt: ",fallback_chain:"Fallback-Kette: ",not_found:"Nicht gefunden",error_lbl:"Fehler: "}
};
function t(k){const l=window._mrLang||'en';return(I18N[l]&&I18N[l][k])||I18N.en[k]||k}
function detectLang(){const p=new URLSearchParams(window.location.search);const u=p.get('lang');if(u&&I18N[u])return u;const s=localStorage.getItem('mr_lang');if(s&&I18N[s])return s;const n=(navigator.language||'en').split('-')[0].toLowerCase();if(I18N[n])return n;return'en'}
function setLang(l){if(!I18N[l])return;window._mrLang=l;localStorage.setItem('mr_lang',l);applyI18n();const s=document.getElementById('lang_selector');if(s)s.value=l}
function applyI18n(){document.querySelectorAll('[data-i18n]').forEach(el=>{const k=el.getAttribute('data-i18n');const v=t(k);if(el.tagName==='INPUT'||el.tagName==='TEXTAREA')el.placeholder=v;else el.textContent=v});document.title=t('title');document.documentElement.lang=window._mrLang||'en'}
window._mrLang=detectLang();
applyI18n();

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
      '" data-preset="' + esc(p) + '">' + esc(p) + '</button>').join('');
    
    // Models table
    document.getElementById('model_count').textContent = models.length;
    document.getElementById('models').innerHTML = models.slice(0, 20).map(m =>
      '<tr><td>' + esc(m.id) + '</td><td>' + esc(m.provider || '\u2014') + '</td><td>' +
      '<span class="badge badge-' + esc(m.selection_mode) + '">' + esc(m.selection_mode) + '</span></td><td>$' +
      (m.cost_per_1k_input || 0).toFixed(4) + '</td><td>' +
      '<button class="toggle-btn" data-toggle="' + esc(m.id) + '" data-mode="' +
      (m.selection_mode === 'auto' ? 'manual' : 'auto') + '">' +
      (m.selection_mode === 'auto' ? t('to_manual') : t('to_auto')) + '</button></td></tr>'
    ).join('') || '<tr><td colspan="5" style="color:var(--dim)">' + t('no_models') + '</td></tr>';

    // Cache stats
    document.getElementById('cache_stats').innerHTML = [
      sr(t('entries'), (cacheData.entries ?? 0) + ' / ' + (cacheData.capacity ?? '?')),
      sr(t('hit_rate'), ((cacheData.hit_rate ?? 0) * 100).toFixed(1) + '%'),
      sr(t('total_hits'), cacheData.hits ?? 0),
      sr(t('total_queries'), cacheData.misses ?? 0),
      sr(t('ttl'), (cacheData.ttl_seconds ?? 0) + 's'),
      sr(t('similarity'), cacheData.similarity_threshold ?? '?'),
    ].join('');

    // Capabilities
    const capData = caps || {};
    const declared = capData.declared || {};
    const capKeys = Object.keys(declared);
    if (capKeys.length === 0) {
      document.getElementById('cap_stats').innerHTML =
        '<div class="stat-row"><span class="stat-label">' + t('no_caps') + '</span></div>';
    } else {
      document.getElementById('cap_stats').innerHTML = capKeys.map(k =>
        '<div class="stat-row"><span>' + esc(k) + '</span><span class="badge badge-on">' + t('declared') + '</span></div>'
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
      '<div style="color:var(--red)">' + esc(d.detail || t('not_found')) + '</div>'; return; }
    renderExplain(d);
  } catch(e) { document.getElementById('explain_result').innerHTML =
    '<div style="color:var(--red)">' + t('error_lbl') + esc(e.message) + '</div>'; }
}

async function explainDryRun() {
  const msg = document.getElementById('explain_input').value.trim();
  if (!msg) { document.getElementById('explain_result').innerHTML =
    '<div style="color:var(--amber)">' + t('enter_msg') + '</div>'; return; }
  try {
    const r = await fetch('/admin/explain?message=' + encodeURIComponent(msg));
    const d = await r.json();
    if (!r.ok) { document.getElementById('explain_result').innerHTML =
      '<div style="color:var(--red)">' + esc(d.detail || t('error_lbl')) + '</div>'; return; }
    renderExplain(d);
  } catch(e) { document.getElementById('explain_result').innerHTML =
    '<div style="color:var(--red)">' + t('error_lbl') + esc(e.message) + '</div>'; }
}

function renderExplain(d) {
  const isDry = d.dry_run || false;
  let html = '<div style="margin-bottom:10px">';
  html += '<span style="font-size:16px;font-weight:700;color:var(--green)">' + esc(d.model || d.model_name || '?') + '</span>';
  if (d.score) html += ' <span style="color:var(--blue)">' + t('score_lbl') + (d.score || 0).toFixed(2) + '</span>';
  html += ' <span class="badge">' + esc(d.routing_mode || '') + '</span>';
  html += ' <span class="badge">' + esc(d.preset || '') + '</span>';
  if (d.task) html += ' <span style="color:var(--dim)">' + t('task_lbl') + esc(d.task) + '</span>';
  if (isDry) html += ' <span style="color:var(--amber)">' + t('dry_run_lbl') + '</span>';
  if (d.reason) html += '<div style="color:var(--dim);font-size:12px;margin-top:4px">' + esc(d.reason) + '</div>';
  html += '</div>';

  // Cost info
  if (d.cost !== undefined || d.estimated_cost) {
    html += '<div style="font-size:12px;color:var(--dim);margin-bottom:8px">';
    if (d.cost) html += t('actual_cost') + d.cost.toFixed(6);
    if (d.estimated_cost) html += t('estimated_cost') + d.estimated_cost.toFixed(6);
    if (d.baseline_cost) html += t('baseline_cost') + d.baseline_cost.toFixed(6);
    if (d.latency_ms) html += t('latency_lbl') + d.latency_ms.toFixed(0) + 'ms';
    if (d.prompt_tokens) html += t('tokens_lbl') + d.prompt_tokens + ' in / ' + d.completion_tokens + ' out';
    html += '</div>';
  }

  // Top candidates breakdown
  const candidates = d.top_candidates || [];
  if (candidates.length > 0) {
    html += '<div style="font-size:12px;color:var(--dim);margin-bottom:6px">' + t('top_candidates') + candidates.length + ')</div>';
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
        if (b.capability !== undefined) html += '<span>' + t('capability_lbl') + b.capability.toFixed(2) + '</span>';
        if (b.cost !== undefined) html += '<span>' + t('cost_lbl') + b.cost.toFixed(2) + '</span>';
        if (b.speed !== undefined) html += '<span>' + t('speed_lbl') + b.speed.toFixed(2) + '</span>';
        if (b.learned !== undefined) html += '<span>' + t('learned_lbl') + b.learned.toFixed(2) + '</span>';
        if (b.total !== undefined) html += '<span>' + t('total_lbl') + b.total.toFixed(2) + '</span>';
        html += '</div>';
      }
      html += '</div>';
    });
  }

  // Failed models (fallback trail)
  if (d.failed_models && d.failed_models.length > 0) {
    html += '<div style="font-size:12px;color:var(--amber);margin-top:8px">';
    html += t('fallback_chain') + d.failed_models.map(esc).join(' \u2192 ') + ' \u2192 <strong>' + esc(d.model) + '</strong>';
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
      '" data-agent="all">' + t('all') + '</button>';
    agentTypes.forEach(at => {
      tabs += '<button class="agent-tab' + (currentAgent === at ? ' active' : '') +
        '" data-agent="' + esc(at) + '">' + esc(at) + '</button>';
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
// Event delegation for dynamic buttons (replaces inline onclick)
document.addEventListener('click', function(e) {
  var p = e.target.closest('[data-preset]');
  if (p) { setPreset(p.dataset.preset); return; }
  var tg = e.target.closest('[data-toggle]');
  if (tg) { toggleMode(tg.dataset.toggle, tg.dataset.mode); return; }
  var ag = e.target.closest('[data-agent]');
  if (ag) { switchAgent(ag.dataset.agent); return; }
});
</script>
</body>
</html>
"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Self-contained dashboard: cost, learning, models, cache, capabilities."""
    return HTMLResponse(_DASHBOARD_HTML)
