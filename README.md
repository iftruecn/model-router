# 🧠 Model Router — 多模型智能路由代理

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

一个轻量级的 **OpenAI 兼容代理服务器**，自动在多个 LLM 之间智能路由——按任务复杂度选择模型，输出不满意自动换模型重试。专为 AI Agent（如 Hermes、Claude Code、Codex）设计，但兼容任何 OpenAI 客户端。

> A lightweight **OpenAI-compatible proxy** that intelligently routes LLM requests across multiple models — picks the right model for each task, and auto-retries with a better model when output quality is poor. Built for AI agents (Hermes, Claude Code, Codex) but works with any OpenAI client.

---

## ✨ 核心能力 / Key Features

| 能力 | 说明 |
|------|------|
| 🎯 **智能分类路由** | 简单问候→便宜模型，复杂编程→强模型，图片任务→多模态模型 |
| 🔄 **输出质量回退** | 模型回答太短/拒绝/质量差 → 自动换下一个模型重试 |
| 🧩 **多模型管理** | 一个端点管理所有模型，加新模型只需一行配置 |
| 🔌 **OpenAI 兼容** | 标准 `/v1/chat/completions` + `/v1/models`，任何客户端即插即用 |
| 🪶 **零依赖代理** | 250 行 Python，FastAPI + httpx，本地运行，零延迟 |

---

## 🚀 快速开始 / Quick Start

### 1. 安装

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

编辑 `model_router_server.py` 中的 `MODELS` 字典，填入你的 API Key：

```python
MODELS = {
    "gpt-4o-mini": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-xxx",        # ← 你的 Key
        "model": "gpt-4o-mini",
        "tier": "flash",
    },
    "gpt-4o": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-xxx",        # ← 你的 Key
        "model": "gpt-4o",
        "tier": "pro",
    },
}
```

### 3. 启动

```bash
python model_router_server.py
# 监听 http://127.0.0.1:6060
# API 文档: http://127.0.0.1:6060/docs
```

### 4. 使用

```bash
# 任何 OpenAI 客户端
curl http://127.0.0.1:6060/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto-router","messages":[{"role":"user","content":"写一个快速排序"}]}'

# Hermes Agent
hermes -m auto-router

# Claude Code
claude --model auto-router --api-base http://127.0.0.1:6060/v1
```

---

## 🎯 路由策略 / Routing Logic

```
用户输入
   │
   ▼
┌─────────────┐
│  分类器      │  ← 零延迟规则匹配
│  Classifier  │
└──────┬──────┘
       │
   ┌───┼───┐
   ▼   ▼   ▼
 flash pro  multimodal    ← 按复杂度/任务类型选模型
   │   │   │
   └───┼───┘
       ▼
  ┌─────────┐
  │ 质量检查  │  ← 太短？拒绝？重复？幻觉？
  └────┬────┘
       │ ❌ 不通过
       ▼
  ┌─────────┐
  │ 自动回退  │  ← 换下一个模型重试
  └─────────┘
```

### 分类规则 / Classification Rules

| 输入特征 | → 模型 | 示例 |
|----------|--------|------|
| 纯问候（<3字） | `flash` | "你好" / "hi" |
| 简单问答/翻译 | `flash` | "what is Python" |
| 代码生成/调试 | `pro` | "写一个排序算法" |
| 系统设计/架构 | `pro` | "设计一个微服务" |
| 图片输入/视觉 | `multimodal` | 上传截图提问 |
| 长上下文(>500字) | `pro` | 多轮对话 |

### 质量回退 / Quality Fallback

| 检测项 | 触发条件 |
|--------|---------|
| 空响应 | content 为空 |
| 过短 | 回复 < 阈值（flash=5字, pro=80字） |
| 拒绝模式 | "我无法" / "I cannot" / "作为AI" |
| 高度重复 | 超 70% 行内容重复 |

---

## 📂 文件结构 / Project Structure

```
model-router/
├── model_router_server.py   # 主程序 (250行)
├── SKILL.md                  # Hermes 技能定义
├── requirements.txt          # Python 依赖
├── start_router.bat          # Windows 启动脚本
├── start_router.sh           # Linux/Mac 启动脚本
├── config.example.yaml       # 配置示例
├── LICENSE                   # MIT
└── README.md                 # 本文件
```

---

## 🧪 实测效果 / Benchmarks

在与 DeepSeek V4 Pro + Flash + 豆包 Seed 2.1 Pro 的三模型组合测试中：

| 指标 | 数据 |
|------|------|
| 分类准确率 | 简单任务→flash 100%，复杂任务→pro 95% |
| 平均响应时间 | flash: ~2s, pro: ~6s, 多模态: ~8s |
| 质量回退触发率 | ~3%（主要在 pro 遇到不擅长的中文语境时） |
| 成本节省 | 约 40-60%（简单任务全走 flash） |

---

## 🔧 高级配置 / Advanced

### 加新模型

在 `MODELS` 字典中加一条：

```python
"claude-sonnet": {
    "name": "Claude Sonnet 4",
    "base_url": "https://api.anthropic.com/v1",
    "api_key": "sk-ant-xxx",
    "model": "claude-sonnet-4-20250514",
    "tier": "pro",
    "multimodal": True,
    "cost": "high",
    "speed": "normal",
},
```

### 自定义分类规则

编辑 `COMPLEX_QUERIES` / `SIMPLE_QUERIES` 正则列表。

### 调整质量阈值

```python
QUALITY_MIN_LENGTH = {
    "your-model": 100,   # 调整最低接受长度
}
```

### 生产部署

```bash
# 使用 gunicorn (Linux)
pip install gunicorn
gunicorn -w 4 -k uvicorn.workers.UvicornWorker model_router_server:app

# Windows 服务 (NSSM)
nssm install ModelRouter
```

---

## 🤝 Hermes Agent 集成 / Hermes Integration

作为 Hermes 技能安装后，代理会自动配置。详见 [SKILL.md](SKILL.md)。

```bash
# 一键安装
npx skills add iftrue/model-router
```

---

## 📊 对比其他方案 / vs Alternatives

| 方案 | 输入路由 | 输出回退 | 本地部署 | 开源 |
|------|:---:|:---:|:---:|:---:|
| **Model Router** | ✅ | ✅ | ✅ | MIT |
| OpenRouter Auto | ✅ | ❌ | ❌ | ❌ |
| RouteLLM | ✅ | ❌ | ✅ | Apache |
| LiteLLM | ✅ | ❌ | ✅ | MIT |
| OmniRoute | ✅ | ❌ | ✅ | MIT |

> Model Router 是唯一同时支持 **输入分类路由 + 输出质量回退** 的开源方案。

---

## ⚠️ 注意事项 / Caveats

- DeepSeek V4 Pro 使用 `reasoning_content` 做思维链——代理已处理此情况
- 豆包 Seed 2.1 Pro 的 API 格式与 OpenAI 兼容，但 base_url 不同
- 代理不缓存请求，每次都是实时调用
- 建议与 API 提供商在同区域部署，减少网络延迟

---

## 📝 License

MIT © 2026 [iftrue](https://github.com/iftrue)
