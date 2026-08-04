# 🧠 Model Router — Multi-Model Intelligent Routing Proxy

> by **iftrue-hermes** · [MIT License](LICENSE) · v1.6.0
>
> **Self-learning routing for AI agents & coding tools** — picks the right model for every task, falls back automatically when output is poor, and gets smarter over time.
>
> **面向 AI Agent 与编程工具的自学习路由代理** — 按任务复杂度自动选模型、输出不满意自动换模型、越用越准。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

---

## Why

AI agents (Hermes, OpenClaw, Claude Code, Codex...) all use LLMs — but they don't know which model is best for each request. Simple "hello" burns expensive tokens on pro models; complex reasoning gets unsatisfying results from flash models.

**Model Router** sits between your agent and your LLM providers as a local OpenAI-compatible proxy. It auto-routes each request to the best model, checks output quality, and learns from every interaction. Zero configuration needed if you already have an agent installed.

---

## Core Features

| Feature | Description |
|---------|-------------|
| ⚡ **Zero-Config Startup** | Auto-detects your agent (Hermes/OpenClaw) and inherits API keys, models, and parameters. No config file needed. |
| 🔌 **One-Click Install** | `model-router install --all` — auto-injects router into all your agents. No manual config editing. |
| 🎯 **7-Domain Classifier** | coding, reasoning, math, creative, translation, vision, chat — multilingual (EN/ZH/JA/KO/ES/FR/DE) |
| 🔄 **Quality Fallback** | Output too short/empty/repetitive? Auto-retry with next model. Only open-source implementation. |
| 🧠 **Self-Learning** | Gaussian Thompson Sampling — learns which model is best for each task type over time |
| 💾 **Semantic Cache** | Similar questions return cached answers (bigram Jaccard, zero new deps) |
| 🛡️ **Param Auto-Adaptation** | Auto-fixes incompatible parameters (e.g., `reasoning_effort=ultra` → `high` for DeepSeek) |
| 🔐 **API Key Security** | SHA-256 hashing, constant-time comparison, full-chain masking in logs/dashboard |
| 📊 **Dashboard** | Real-time multi-agent view, per-agent stats, human feedback, cost tracking |
| 🐳 **Docker Ready** | `docker compose up -d` |

---

## Quick Start

```bash
# Clone
git clone https://github.com/iftruecn/model-router.git
cd model-router

# Install
pip install -e .

# Start (zero config — auto-detects your agent!)
python -m model_router
# → http://127.0.0.1:6060

# One-click install into your agents:
model-router install --all
```

**Already have Hermes or OpenClaw?** That's it. Router auto-detects your agent config and inherits all API keys and models. No `config.yaml` needed.

Point any OpenAI-compatible client to `http://127.0.0.1:6060/v1` and it just works.

---

## Supported Agents

| Agent | Auto-Detection | Install Command |
|-------|:--:|------|
| **Hermes** | ✅ | `model-router install --agent hermes` |
| **OpenClaw** (LobsterAI, AutoClaw, etc.) | ✅ | `model-router install --agent openclaw` |
| **Any OpenAI-compatible agent** | — | Point `base_url` to `http://127.0.0.1:6060/v1` |

---

## Dashboard

`http://127.0.0.1:6060/dashboard` — multi-agent view with per-agent stats, cost tracking, model management, human feedback (👍/👎), Why-this-model decision explainability.

---

## Project Structure

```
model_router/
├── core/          Routing engine, classifier, learner, quality, cache, security
├── api/           REST endpoints (chat, admin, dashboard, keys)
├── providers/     Connection pool, model registry
├── cli/           Setup wizard, model discovery, one-click install
├── config/        Defaults, validator, pricing, agent auto-inheritance
├── app.py         FastAPI application factory
└── runtime.py     AppContext container
```

---

## Roadmap

| Version | Milestone |
|:--:|------|
| v1.4.0 | Zero-config startup, Agent auto-inheritance (Hermes/OpenClaw), param adaptation |
| v1.5.0 | Multi-agent unified access, one-click install, Dashboard multi-agent view |
| v1.6.0 | Full P0/P1/P2 sweep (35 fixes from Hermes + WorkBuddy + Trae + LobsterAI review) |
| v1.7.0 | Distributed deployment, cluster routing, cross-node cache sharing (planned) |

---

## License

MIT © 2026 **iftrue-hermes**

---

*Reviewed by Hermes, WorkBuddy, Trae, and LobsterAI — 35 issues resolved across 4 review rounds.*
