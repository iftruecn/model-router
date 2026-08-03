---
name: model-router
description: Use when the user wants to set up automatic multi-model routing (smart model switching based on task complexity, auto-fallback on poor output). Deploy an OpenAI-compatible proxy that routes between flash/pro/multimodal models.
triggers:
  - 用户提到模型自动切换、智能路由、多模型管理、模型代理
  - 用户想根据任务复杂度自动选择不同模型
  - 用户想配置多个 LLM 之间的自动回退
  - 用户提到 "model router" / "auto routing" / "model switching"
  - 用户说 "flash 处理简单问题，pro 处理复杂问题"
  - 用户想在 Hermes 中配置多个模型自动切换
---

# Model Router — 多模型智能路由代理

为 Hermes Agent 配置一个本地 OpenAI 兼容代理，自动在多个模型间智能路由。

## 工作原理

```
Hermes → 路由代理(本地:6060) → 分类器判断复杂度
                               ├─ 简单问候 → flash（快+便宜）
                               ├─ 复杂编程 → pro（强推理）
                               ├─ 图片任务 → 多模态模型
                               └─ 输出不好 → 自动换模型重试
```

## 快速部署

### 第 1 步：安装依赖

```bash
pip install fastapi uvicorn httpx pyyaml
```

### 第 2 步：复制代理脚本

```bash
mkdir -p D:\AI\py\model_router
copy scripts\model_router_server.py D:\AI\py\model_router\
```

### 第 3 步：配置 API Key

编辑 `D:\AI\py\model_router\model_router_server.py`，找到 `load_config()` 函数，替换为你的 API 配置：

```python
MODELS = {
    "your-fast-model": {
        "name": "Fast Model",
        "base_url": "https://api.xxx.com/v1",
        "api_key": "sk-xxx",
        "model": "model-id",
        "tier": "flash",
    },
    "your-pro-model": {
        "name": "Pro Model",
        "base_url": "https://api.xxx.com/v1",
        "api_key": "sk-xxx",
        "model": "model-id",
        "tier": "pro",
    },
}
```

或者，如果使用 Hermes 已有的 API Key，代理会自动从 `config.yaml` 读取。

### 第 4 步：启动代理

```bash
python D:\AI\py\model_router\model_router_server.py
# 监听 http://127.0.0.1:6060
```

### 第 5 步：配置 Hermes

在 Hermes `config.yaml` 中添加 custom_provider：

```yaml
custom_providers:
  - name: 'router'
    base_url: http://127.0.0.1:6060/v1
    api_key: 'local'
    api_mode: chat_completions
    models:
      auto-router:
        context_length: 1000000
        name: Auto Router
    model: auto-router
```

然后切换默认模型：

```bash
hermes model          # 选 router
# 或临时使用
hermes -m auto-router
```

### 第 6 步：设置自启动（可选）

将 `start_router.bat` 复制到 Windows 启动目录：

```bash
copy start_router.bat "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\"
```

## 路由策略

### 分类规则

| 输入类型 | 检测方式 | → 模型 |
|----------|---------|--------|
| 纯问候 | "你好" / "hi" / ≤3字 | flash |
| 简单问答 | 什么是/翻译/搜索 | flash |
| 代码编写 | write/编写/实现/debug | pro |
| 系统设计 | design/架构/方案 | pro |
| 图片输入 | image_url / [IMAGE] | multimodal |
| 长上下文 | >500字或>4轮对话 | pro |
| 其他 | 默认 | pro |

### 输出质量回退

当模型输出满足以下条件时，自动换下一个模型重试：
- 内容为空
- 过短（flash<5字, pro<80字）
- 包含拒绝短语（"我无法"/"I cannot"）
- 高度重复（>70% 行内容重复）

回退顺序：
```
flash 失败 → pro → multimodal
pro 失败 → multimodal
multimodal 失败 → pro
```

## 加新模型

编辑 `MODELS` 字典，加一行：

```python
"new-model": {
    "name": "New Model",
    "base_url": "https://api.xxx.com/v1",
    "api_key": "sk-xxx",
    "model": "model-id",
    "tier": "pro",        # flash / pro
    "multimodal": False,  # 是否支持图片
    "cost": "medium",     # low / medium / high
    "speed": "normal",    # fast / normal / slow
},
```

重启代理生效。

## 常见问题

**Q: 代理会拖慢响应吗？**
A: 不会。代理本身零延迟（<1ms），所有延迟来自模型 API。

**Q: 支持流式输出吗？**
A: 当前版本不支持 streaming，后续会加。对 Agent 场景影响不大（Agent 调模型不需要 streaming）。

**Q: API Key 安全吗？**
A: 代理只监听 127.0.0.1，外部无法访问。Key 存在本地 config.yaml。

**Q: 能和其他 Agent 共用吗？**
A: 可以。任何 OpenAI 兼容客户端都能用 `http://127.0.0.1:6060/v1` 作为 API 端点。
