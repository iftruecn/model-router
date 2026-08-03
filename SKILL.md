---
name: model-router
description: Use when the user wants to set up automatic multi-model routing (smart model switching based on task complexity, auto-fallback on poor output). Deploy an OpenAI-compatible proxy that routes between flash/pro/multimodal models.
triggers:
  - "model router" / "auto routing" / "model switching"
  - 自动切换模型、智能路由、多模型代理
  - "flash for simple, pro for complex"
  - 多模型自动回退、模型质量检查
---

# Model Router — Multi-Model Intelligent Routing Proxy

Set up a local OpenAI-compatible proxy that automatically routes requests across multiple LLMs.

## How It Works

```
Your Agent → Router (localhost:6060) → Classifier
                                         ├─ Simple → flash (fast & cheap)
                                         ├─ Complex → pro (powerful)
                                         ├─ Images → multimodal
                                         └─ Poor output → auto retry next model
```

## Setup

### Step 1: Install

```bash
pip install fastapi uvicorn httpx pyyaml
```

### Step 2: Configure

Copy and edit `config.example.yaml` → `config.yaml`:

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

### Step 3: Start

```bash
python model_router_server.py
# → http://127.0.0.1:6060
```

### Step 4: Configure Hermes

Add to Hermes `config.yaml`:

```yaml
custom_providers:
  - name: 'router'
    base_url: 'http://127.0.0.1:6060/v1'
    api_key: 'local'
    api_mode: 'chat_completions'
    models:
      auto-router:
        context_length: 1000000
    model: 'auto-router'
```

Then switch: `hermes model` → select `router`

### Step 5: Auto-start (optional)

```bash
# Windows
copy start_router.bat "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\"

# Linux/Mac (systemd or launchd)
```

## Routing Logic

### Classification

| Input | → Tier | Example |
|-------|--------|---------|
| Greetings (<3 chars) | flash | "Hi" |
| Simple Q&A | flash | "What is X?" |
| Code generation | pro | "Write a function" |
| Architecture/design | pro | "Design a system" |
| Image input | multimodal | Screenshot upload |
| Long context | pro | Multi-turn chat |
| Default | pro | Everything else |

### Quality Fallback

Output is re-routed to next model if:
- Empty content
- Too short (flash<5, pro<80 chars)
- Contains refusal language ("I cannot")
- Highly repetitive (>70% dup lines)

## Adding Models

Edit `models:` in config.yaml, add:

```yaml
claude-sonnet:
  name: "Claude Sonnet 4"
  base_url: "https://api.anthropic.com/v1"
  api_key: "sk-ant-xxx"
  model: "claude-sonnet-4-20250514"
  tier: "pro"
  multimodal: true
```

Restart proxy to apply.

## FAQ

**Q: Does this add latency?**
A: <1ms. All latency comes from the model APIs.

**Q: Works with non-Hermes agents?**
A: Yes — any OpenAI-compatible client. Claude Code, Codex, Copilot, etc.

**Q: Streaming?**
A: Not yet. Coming in v1.1.

**Q: API key security?**
A: Binds to 127.0.0.1 only. Keys stay in local config.yaml.
