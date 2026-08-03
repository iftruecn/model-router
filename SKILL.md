---
name: model-router
description: Use when the user wants to set up automatic multi-model routing (smart model switching based on task complexity, auto-fallback on poor output). Deploy an OpenAI-compatible proxy that routes between flash/pro/multimodal models.
author: iftrue-hermes
triggers:
  - "model router" / "auto routing" / "model switching"
  - 自动切换模型、智能路由、多模型代理
  - "flash for simple, pro for complex"
  - 多模型自动回退、模型质量检查
---

# Model Router — Multi-Model Intelligent Routing Proxy

> by **iftrue-hermes** · MIT License

Set up a local OpenAI-compatible proxy that automatically routes requests across multiple LLMs.

部署一个本地 OpenAI 兼容代理，在多模型间自动智能路由。

## How It Works / 工作原理

```
Your Agent → Router (localhost:6060) → Classifier / 分类器
                                         ├─ Simple / 简单 → flash (fast & cheap / 快+便宜)
                                         ├─ Complex / 复杂 → pro (powerful / 强推理)
                                         ├─ Images / 图片 → multimodal / 多模态
                                         └─ Poor output → auto retry next model / 自动换模型重试
```

## Setup / 部署

### Step 1 / 第1步: Install / 安装

```bash
pip install fastapi uvicorn httpx pyyaml
```

### Step 2 / 第2步: Configure / 配置

Copy `config.example.yaml` → `config.yaml`, add your models:

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

### Step 3 / 第3步: Start / 启动

```bash
python model_router_server.py
# → http://127.0.0.1:6060
```

### Step 4 / 第4步: Hermes Integration / Hermes 集成

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

Then: `hermes model` → select `router`

### Step 5 / 第5步: Auto-start / 开机自启

```bash
# Windows
copy start_router.bat "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\"
```

## Routing Logic / 路由策略

### Classification / 分类规则

| Input / 输入 | → Tier / 层级 | Example / 示例 |
|-------|--------|---------|
| Greetings / 问候 (<3 chars) | flash | "Hi" / "你好" |
| Simple Q&A / 简单问答 | flash | "What is X?" |
| Code generation / 代码编写 | pro | "Write a function" |
| Architecture / 架构设计 | pro | "Design a system" |
| Image input / 图片 | multimodal | Screenshot / 截图 |
| Long context / 长文本 | pro | Multi-turn / 多轮对话 |
| Default / 默认 | pro | Everything else / 其他 |

### Quality Fallback / 质量回退

Auto-retries with next model if / 自动换模型重试条件:
- Empty content / 内容为空
- Too short / 过短 (flash<5, pro<80 chars)
- Refusal language / 拒绝用语 ("I cannot" / "无法")
- Repetitive / 高度重复 (>70% dup lines)

## Adding Models / 添加模型

Edit `models:` in config.yaml:

```yaml
claude-sonnet:
  name: "Claude Sonnet 4"
  base_url: "https://api.anthropic.com/v1"
  api_key: "sk-ant-xxx"
  model: "claude-sonnet-4-20250514"
  tier: "pro"
  multimodal: true
```

Restart proxy to apply. / 重启代理生效。

## Notes / 注意事项

- Supports `${ENV_VAR}` in config for API keys / 支持 `${环境变量}` 引用密钥
- Binds to 127.0.0.1 only (secure by default) / 默认仅监听本地
- Works with any OpenAI-compatible client / 兼容任何 OpenAI 客户端
- Streaming not yet supported / 暂不支持流式输出

---

MIT © 2026 **iftrue-hermes**
