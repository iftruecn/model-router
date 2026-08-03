# 🧠 Model Router — Multi-Model Intelligent Routing Proxy

> by **iftrue-hermes** · [MIT License](LICENSE)
>
> A lightweight OpenAI-compatible proxy that routes requests to the right model for each task.
> 轻量级 OpenAI 兼容代理，按任务复杂度自动选择最合适的模型。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![Author: iftrue-hermes](https://img.shields.io/badge/author-iftrue--hermes-orange)](https://github.com/iftruecn)

---

## 🌍 Languages / 语言

- [English](#english) | [中文](#中文)

---

## English

### ✨ Features

| Feature | Description |
|---------|-------------|
| 🎯 **Smart Classification** | Greetings → cheap model, coding → powerful model, images → multimodal |
| 🔄 **Quality Fallback** | Short/empty/refusal output → auto-retry with next model |
| 🧩 **Multi-Model** | Manage all your models in one YAML config |
| 🔌 **Drop-in** | Standard `/v1/chat/completions` + `/v1/models`, any OpenAI client works |
| 🪶 **Lightweight** | ~400 lines of Python, FastAPI + httpx, runs locally with zero overhead |

### 🚀 Quick Start

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
# Edit config.yaml → add your models and API keys
python model_router_server.py
# → http://127.0.0.1:6060
```

### 🎯 Routing Logic

```
User query → Classifier → flash (simple) / pro (complex) / multimodal (images)
                │
                ▼
          Quality Check → Fail? → Auto fallback to next model
```

---

## 中文

### ✨ 核心能力

| 能力 | 说明 |
|------|------|
| 🎯 **智能分类** | 问候→便宜模型，编程→强模型，图片→多模态模型 |
| 🔄 **质量回退** | 输出太短/拒绝/质量差 → 自动换模型重试 |
| 🧩 **多模型管理** | 一个 YAML 配置管理所有模型 |
| 🔌 **即插即用** | 标准 OpenAI 接口，任何客户端都能用 |
| 🪶 **轻量高效** | ~400 行 Python，本地运行零额外延迟 |

### 🚀 快速开始

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
# 编辑 config.yaml → 填入你的模型和 API Key
python model_router_server.py
# → http://127.0.0.1:6060
```

### 🎯 路由逻辑

```
用户输入 → 分类器 → flash（简单）/ pro（复杂）/ multimodal（图片）
              │
              ▼
         质量检查 → 不通过？→ 自动换下一个模型
```

---

## 📂 Project Structure / 项目结构

```
model-router/
├── model_router_server.py   # Main proxy / 主程序 (400 lines)
├── config.example.yaml      # Example config / 示例配置
├── requirements.txt         # Python dependencies / 依赖
├── start_router.bat         # Windows launcher / 启动脚本
├── start_router.sh          # Linux/Mac launcher
├── SKILL.md                 # Hermes Agent skill definition
├── LICENSE                  # MIT
└── README.md
```

## 🔧 Configuration / 配置

```yaml
models:
  your-model:
    name: "Display Name / 显示名称"
    base_url: "https://api.provider.com/v1"
    api_key: "sk-xxx"
    model: "model-id"
    tier: "pro"          # "flash" (fast/cheap) or "pro" (powerful)
    multimodal: false     # true if supports images / 支持图片则为 true
```

Supports `${ENV_VAR}` substitution for API keys. / 支持 `${环境变量}` 引用。

## 🤝 Integrations / 集成

- **Hermes Agent**: `npx skills add iftruecn/model-router`
- **Claude Code / Codex**: point `--api-base` to `http://127.0.0.1:6060/v1`
- **Any OpenAI client**: use as custom endpoint / 作为自定义端点使用

## 📊 vs Alternatives / 对比

| Solution | Input Routing | Output Fallback | Local | Open Source |
|----------|:---:|:---:|:---:|:---:|
| **Model Router** | ✅ | ✅ | ✅ | MIT |
| OpenRouter Auto | ✅ | ❌ | ❌ | ❌ |
| RouteLLM | ✅ | ❌ | ✅ | Apache |
| LiteLLM | ✅ | ❌ | ✅ | MIT |

## 📝 License

MIT © 2026 **iftrue-hermes**
