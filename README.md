# 🧠 Model Router — Multi-Model Intelligent Routing Proxy

> by **iftrue-hermes** · [MIT License](LICENSE) · v1.9.0
>
> **Zero-dependency smart routing for AI agents** — picks the cheapest capable model for every task, falls back on poor output, learns from every interaction, and knows which models can handle images/video/tools.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

---

## Why

AI agents use many LLMs — but can't tell which one to use for each request. "Hello" burns expensive pro tokens; complex reasoning gets poor results from flash models; image requests go to text-only models.

**Model Router** is a local OpenAI-compatible proxy. It analyzes each request, checks what each model can actually do, and routes to the cheapest capable one — automatically. Zero new dependencies, zero configuration if you already have an agent.

---

## Core Features

| Feature | Description |
|---------|-------------|
| ⚡ **Zero-Config Startup** | Auto-detects your agent (Hermes/OpenClaw) and inherits API keys, models, and parameters |
| 🏷️ **Model Capability Awareness** | Knows what each model can do (text/image/video/audio/tools) — never routes image requests to text-only models (v1.9.0) |
| 🎯 **7-Domain Classifier** | coding, reasoning, math, creative, translation, vision, chat — multilingual (EN/ZH/JA/KO/ES/FR/DE) |
| 🔄 **Quality Fallback** | Output too short/empty/refusal/repetitive? Auto-retry with next model |
| 🧠 **Self-Learning** | Gaussian Thompson Sampling — learns which model is best for each task, progressive handoff from static rules |
| 💾 **Semantic Cache** | Similar questions return cached answers (bigram Jaccard, zero new deps) |
| 🛡️ **Param Auto-Adaptation** | Auto-fixes incompatible parameters per provider |
| 🔐 **API Key Security** | SHA-256 hashing, constant-time comparison, full-chain masking |
| 📊 **Dashboard + Admin UI** | Real-time stats, cost tracking, model management, human feedback, 7-language i18n |
| 🎚️ **Routing Presets** | intelligence / balance / cost — one-click trade-off |
| 🐳 **Docker Ready** | `docker compose up -d` |

---

## Quick Start

```bash
git clone https://github.com/iftruecn/model-router.git
cd model-router
pip install -e .
model-router serve          # → http://127.0.0.1:6060
```

Point any OpenAI-compatible client to `http://127.0.0.1:6060/v1`.

---

## How Routing Works

```
User request → Domain classifier (coding? reasoning? creative?)
             → Modality filter (need image input? generate image?)
             → 3D scoring (capability × cost × speed)
             → Self-learning adjustment (Gaussian TS, progressive handoff)
             → Diversity guard (anti-collapse)
             → Best model selected
```

Transparency headers: `X-Routed-To`, `X-Routing-Reason`, `X-Routing-Mode`, `X-Routing-Preset`.

---

## Supported Agents

| Agent | Auto-Detection | Install Command |
|-------|:--:|------|
| **Hermes** | ✅ | `model-router install --agent hermes` |
| **OpenClaw** (LobsterAI, AutoClaw, etc.) | ✅ | `model-router install --agent openclaw` |
| **Any OpenAI-compatible agent** | — | Point `base_url` to `http://127.0.0.1:6060/v1` |

---

## Endpoints

| URL | Purpose |
|-----|---------|
| `http://127.0.0.1:6060/v1/chat/completions` | Main API (OpenAI-compatible) |
| `http://127.0.0.1:6060/dashboard` | Dashboard (multi-agent, cost, feedback) |
| `http://127.0.0.1:6060/admin` | Admin UI (model management, presets, cache) |
| `http://127.0.0.1:6060/health` | Health check |

---

## Project Structure

```
model_router/
├── core/          Routing engine, classifier, learner, quality, cache, fallback, auth, security
├── api/           REST endpoints (chat, streaming, admin, dashboard, keys)
├── providers/     Connection pool, model registry (with modality filtering)
├── cli/           Setup wizard, model discovery, one-click install
├── config/        Defaults, model metadata (capabilities), pricing, validator, auto-inheritance
├── locales/       7-language i18n
├── app.py         FastAPI application factory
└── runtime.py     AppContext container
```

---

## Roadmap

| Version | Milestone |
|:--:|------|
| v1.7.0 | Dashboard 7-language i18n, full P2/P3 sweep, module docstring unification |
| v1.8.0 | 32 fixes (quad-review), Admin UI, data-attr event delegation, startup crash fix |
| v1.9.0 | **Model capability awareness** — modality filtering (text/image/video/audio/tools), input/output_modalities, empty-candidate guard |
| v1.10.0 | stdlib TF-IDF lightweight classifier (replacing regex), session routing stickiness (planned) |

---

## License

MIT © 2026 **iftrue-hermes**

---

*Reviewed by Hermes, WorkBuddy, Trae, LobsterAI, Kun, 顺手 (AutoClaw), 产品经理, 产品设计师 — 8 reviewers across 6 review rounds.*
