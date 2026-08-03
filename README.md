# 🧠 Model Router — Multi-Model Intelligent Routing Proxy

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

A lightweight **OpenAI-compatible proxy server** that automatically routes LLM requests across multiple models. Picks the right model for each task, and auto-retries with a better model when output quality is poor.

> 轻量级 OpenAI 兼容代理，在多模型间智能路由——简单问题用便宜模型、复杂任务用强模型、输出不满意自动换模型重试。

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🎯 **Smart Classification** | Greetings→cheap model, coding→powerful model, images→multimodal |
| 🔄 **Quality Fallback** | Short/empty/refusal output → auto-retry with next model |
| 🧩 **Multi-Model** | Manage all your models in one YAML config |
| 🔌 **Drop-in** | Standard `/v1/chat/completions` + `/v1/models`, any OpenAI client works |
| 🪶 **Lightweight** | ~350 lines of Python, FastAPI + httpx, runs locally with zero overhead |

---

## 🚀 Quick Start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp config.example.yaml config.yaml
# Edit config.yaml — add your models and API keys
```

Minimal config:

```yaml
models:
  gpt-4o-mini:
    name: "GPT-4o Mini"
    base_url: "https://api.openai.com/v1"
    api_key: "sk-your-key"
    model: "gpt-4o-mini"
    tier: "flash"

  gpt-4o:
    name: "GPT-4o"
    base_url: "https://api.openai.com/v1"
    api_key: "sk-your-key"
    model: "gpt-4o"
    tier: "pro"
```

### 3. Run

```bash
python model_router_server.py
# → http://127.0.0.1:6060
```

### 4. Use

```bash
# Any OpenAI client
curl http://127.0.0.1:6060/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto-router","messages":[{"role":"user","content":"Write a quicksort in Python"}]}'

# Hermes Agent
hermes -m auto-router

# Claude Code / Codex
claude --model auto-router --api-base http://127.0.0.1:6060/v1
```

---

## 🎯 How Routing Works

```
User query
   │
   ▼
┌──────────┐
│ Classifier │  ← Rule-based (zero latency)
└─────┬────┘
      │
  ┌───┼───┐
  ▼   ▼   ▼
flash pro  multimodal
  │   │   │
  └───┼───┘
      ▼
┌──────────┐
│ Quality   │  ← Too short? Refusal? Repetitive?
│ Check     │
└─────┬────┘
      │ ❌ Fail
      ▼
┌──────────┐
│ Fallback  │  ← Try next model, return best result
└──────────┘
```

### Classification Rules

| Input | → Tier | Example |
|-------|--------|---------|
| Simple greeting (<3 chars) | flash | "Hi" / "Hello" |
| Quick Q&A / translation | flash | "What is Python?" |
| Code generation / debug | pro | "Write a sorting algorithm" |
| System design / architecture | pro | "Design a microservice" |
| Image input / vision task | multimodal | Upload a screenshot |
| Long context (>500 chars) | pro | Multi-turn conversation |
| Default | pro | Better safe than cheap |

### Quality Fallback Triggers

| Check | Condition |
|-------|-----------|
| Empty response | content is "" |
| Too short | flash<5 chars, pro<80 chars |
| Refusal pattern | "I cannot" / "I'm unable" / "as an AI" |
| Repetitive | >70% duplicate lines |

---

## 📂 Project Structure

```
model-router/
├── model_router_server.py   # Main proxy (350 lines)
├── config.example.yaml      # Example config with popular models
├── requirements.txt         # Python deps (fastapi, uvicorn, httpx, pyyaml)
├── start_router.bat         # Windows launcher
├── start_router.sh          # Linux/Mac launcher
├── SKILL.md                 # Hermes Agent skill definition
├── LICENSE                  # MIT
└── README.md
```

---

## 🔧 Add Your Own Models

```yaml
models:
  your-model:
    name: "Display Name"
    base_url: "https://api.provider.com/v1"
    api_key: "sk-xxx"
    model: "model-id"
    tier: "pro"          # "flash" or "pro"
    multimodal: false     # true if supports images
    cost: "medium"        # "low" / "medium" / "high"
    speed: "normal"       # "fast" / "normal" / "slow"
```

Then restart the proxy. No code changes needed.

---

## 🤝 Integrations

### Hermes Agent

```bash
npx skills add iftrue/model-router
```

Add to Hermes `config.yaml`:

```yaml
custom_providers:
  - name: 'router'
    base_url: 'http://127.0.0.1:6060/v1'
    api_key: 'local'
    models:
      auto-router:
        context_length: 1000000
    model: 'auto-router'
```

Then: `hermes model` → select `router`

### Any OpenAI Client

Just point `base_url` to `http://127.0.0.1:6060/v1`.

---

## 📊 vs Alternatives

| Solution | Input Routing | Output Fallback | Local | Open Source |
|----------|:---:|:---:|:---:|:---:|
| **Model Router** | ✅ | ✅ | ✅ | MIT |
| OpenRouter Auto | ✅ | ❌ | ❌ | ❌ |
| RouteLLM | ✅ | ❌ | ✅ | Apache |
| LiteLLM | ✅ | ❌ | ✅ | MIT |

> Model Router is the only open-source solution that combines **input classification routing + output quality fallback**.

---

## ⚠️ Notes

- Some models (e.g., DeepSeek V4 Pro) use `reasoning_content` for chain-of-thought — the proxy handles this transparently
- No request caching — every call hits the live API
- Streaming not yet supported (coming soon)
- For production, run behind gunicorn or NSSM

---

## 📝 License

MIT © 2026 [iftrue](https://github.com/iftrue)
