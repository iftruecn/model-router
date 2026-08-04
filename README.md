# 🧠 Model Router — Multi-Model Intelligent Routing Proxy

> by **iftrue-hermes** · [MIT License](LICENSE)
>
> **Self-learning routing for AI agents & coding tools** — picks the right model for every task, falls back automatically when output is poor, and gets smarter over time.
>
> **面向 AI Agent 与编程工具的自学习路由代理** — 按任务复杂度自动选模型、输出不满意自动换模型、越用越准。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

---

## What It Does

```
Your Agent → Model Router → DeepSeek Flash (simple questions)
                          → DeepSeek Pro  (complex code)
                          → GPT-4o        (images)
                          → Claude        (fallback if output is poor)
```

A local proxy (OpenAI-compatible) that sits between your AI agent and your LLM providers. It classifies each request, routes it to the best model, checks the output quality, and learns from every interaction.

## Core Features

| Feature | Description |
|---------|-------------|
| 🎯 **7-Domain Classifier** | coding, reasoning, math, creative, translation, vision, chat — multilingual (EN/ZH/JA/KO/ES/FR/DE) |
| 🔄 **Quality Fallback** | short/empty/refusal/repetitive output → auto-retry with next model |
| 🧠 **Self-Learning** | Gaussian Thompson Sampling — learns which model is best for each task type |
| 💾 **Semantic Cache** | similar questions return cached answers (bigram Jaccard, zero new deps) |
| 📊 **Offline Evaluator** | quantifies "does learning actually improve routing?" |
| 🔍 **Model Auto-Discovery** | `model-router discover` — one command to list all models under a key |
| 🛡️ **Safety First** | binds 127.0.0.1 by default, no database, no external attack surface |
| 🐳 **Docker Ready** | `docker compose up -d` |

## Quick Start

```bash
# Clone
git clone https://github.com/iftruecn/model-router.git
cd model-router

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml → add your models and API keys

# Or auto-discover (if you already have env vars set)
model-router discover --base-url https://api.deepseek.com/v1 --api-key sk-xxx

# Run
docker compose up -d
# or: pip install -e . && python -m model_router
# → http://127.0.0.1:6060
```

Point any OpenAI-compatible client to `http://127.0.0.1:6060/v1` and it just works.

## Project Structure

```
model_router/
├── core/          Routing engine, classifier, learner, quality, cache
├── api/           REST endpoints (chat, admin, dashboard, keys)
├── providers/     Connection pool, model registry
├── cli/           Setup wizard, model discovery
├── locales/       7-language i18n
├── config/        Defaults, validator, pricing
├── app.py         FastAPI application factory
└── runtime.py     AppContext container
```

## Dashboard

`http://127.0.0.1:6060/dashboard` — cost savings, learning stats, cache hit rate, model management, human feedback.

## License

MIT © 2026 **iftrue-hermes**
