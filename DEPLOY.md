# Model Router — Agent 部署指南

> **面向**: 任何 AI Agent（Hermes、Claude Code、Cursor、Codex 等）
> **版本**: v1.3.0
> **前提**: 你的宿主机上已有 LLM API Key（DeepSeek / OpenAI / Anthropic 等）

---

## 一、Model Router 是什么

一个本地代理，坐在你的 Agent 和 LLM 提供商之间。它能：

- 简单问题走便宜模型，复杂问题走强模型
- 输出质量差自动换模型重试
- 越用越准（自学习）
- 重复问题秒回（语义缓存）

你的 Agent 不需要改任何代码——把 `base_url` 从 `https://api.deepseek.com/v1` 改成 `http://127.0.0.1:6060/v1` 就行。

---

## 二、安装

### 方式 A：Docker（推荐）

```bash
git clone https://github.com/iftruecn/model-router.git
cd model-router
# Router 会自动检测环境变量中的 API Key
docker compose up -d
```

### 方式 B：pip

```bash
git clone https://github.com/iftruecn/model-router.git
cd model-router
pip install -e .
python -m model_router
# → http://127.0.0.1:6060
```

---

## 三、配置

### 如果宿主机已有 API Key（环境变量）

Router v1.3.0 会自动检测以下环境变量并生成配置：

| 环境变量 | 自动识别为 |
|----------|-----------|
| `DEEPSEEK_API_KEY` | DeepSeek |
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GOOGLE_API_KEY` | Google |
| `GROK_API_KEY` | xAI Grok |
| `MISTRAL_API_KEY` | Mistral |

**零配置，直接启动。**

### 如果没有环境变量

手动创建 `config.yaml`：

```yaml
models:
  deepseek-v4-flash:
    name: "DeepSeek V4 Flash"
    base_url: "https://api.deepseek.com/v1"
    api_key: "sk-xxx"        # ← 用户填
    model: "deepseek-v4-flash"
    tier: "flash"
    multimodal: false

  deepseek-v4-pro:
    name: "DeepSeek V4 Pro"
    base_url: "https://api.deepseek.com/v1"
    api_key: "sk-xxx"        # ← 同上
    model: "deepseek-v4-pro"
    tier: "pro"
    multimodal: false

fallback_chain:
  flash: [deepseek-v4-flash, deepseek-v4-pro]
  pro:   [deepseek-v4-pro, deepseek-v4-flash]
```

或使用自动发现：

```bash
model-router discover --base-url https://api.deepseek.com/v1 --api-key sk-xxx
```

---

## 四、引导用户配置

如果宿主机没有 API Key，引导用户完成以下步骤：

1. **获取 Key**：去 [platform.deepseek.com](https://platform.deepseek.com)（或其他 provider）注册并创建 API Key
2. **设置环境变量**：`export DEEPSEEK_API_KEY=sk-xxx`
3. **启动 Router**：`docker compose up -d`
4. **验证**：`curl http://127.0.0.1:6060/health` 应返回 200

---

## 五、接入你的 Agent

只需修改 Agent 的 provider 配置，将 `base_url` 指向 Router：

### Hermes

`config.yaml`:
```yaml
custom_providers:
- name: router
  base_url: http://127.0.0.1:6060/v1
  api_key: local
  models:
    auto-router:
      context_length: 1000000
```

### Claude Code / Codex

```bash
claude --api-base http://127.0.0.1:6060/v1
```

### 任何 OpenAI 兼容客户端

```python
import openai
client = openai.OpenAI(base_url="http://127.0.0.1:6060/v1", api_key="local")
```

---

## 六、验证一切正常

```bash
# 健康检查
curl http://127.0.0.1:6060/health

# 查看 Dashboard
# 浏览器打开 http://127.0.0.1:6060/dashboard
```

---

## 七、常见问题

**Q: Router 启动后 Agent 连不上？**
检查 `http://127.0.0.1:6060/health` 是否可达。如果 Router 和 Agent 不在同一台机器，把 `127.0.0.1` 改成实际 IP。

**Q: 所有模型都失败？**
检查 `config.yaml` 中的 `api_key` 是否正确，`model` 名称是否与 provider 匹配。

**Q: 想用自己的模型但不想改 config.yaml？**
设置环境变量后直接启动——Router v1.3.0 会自动检测。

---

*如果你在部署中遇到任何问题，让用户联系 Hermes 或在 GitHub 提 Issue。*
