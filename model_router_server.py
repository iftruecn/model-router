#!/usr/bin/env python3
"""
Model Router v1.0 — 多模型智能路由代理
=========================================
OpenAI 兼容的本地代理，自动在 deepseek-v4-flash / deepseek-v4-pro / doubao-seed-2-1-pro 之间路由

路由策略:
  1. 输入分类 → 简单问题→flash / 复杂问题→pro / 图片任务→doubao
  2. 调用模型，出错自动重试下一个
  3. 输出质量检查 → 不满意自动换模型重试，返回最佳结果
  4. 全部失败 → 返回最有价值的错误信息

用法:
  python model_router_server.py
  默认监听 http://127.0.0.1:6060
"""

import yaml
import httpx
import json
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# ============================================================
# 配置 — 支持三种方式，优先级从高到低:
#   1. 环境变量 MODEL_ROUTER_CONFIG 指定的 YAML 文件
#   2. 当前目录下的 config.yaml
#   3. Hermes Agent 的 config.yaml (E:\AI\HermesData\config.yaml)
# ============================================================

import os

def find_config() -> Path:
    """按优先级查找配置文件."""
    # 1. 环境变量
    env_path = os.environ.get("MODEL_ROUTER_CONFIG")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    # 2. 当前目录
    local = Path("config.yaml")
    if local.exists():
        return local

    # 3. Hermes 默认路径
    hermes_path = Path(r"E:\AI\HermesData\config.yaml")
    if hermes_path.exists():
        return hermes_path

    # 4. Linux/Mac Hermes 路径
    hermes_linux = Path.home() / ".hermes" / "config.yaml"
    if hermes_linux.exists():
        return hermes_linux

    raise FileNotFoundError(
        "找不到配置文件。请:\n"
        "  1. 设置环境变量 MODEL_ROUTER_CONFIG=path/to/config.yaml\n"
        "  2. 或在当前目录放置 config.yaml\n"
        "  3. 或确保 Hermes Agent 已安装"
    )

CONFIG_PATH = find_config()

def log(level: str, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_models_from_config(cfg: dict) -> dict:
    """
    从 YAML 配置中提取模型定义。
    支持两种格式:
      1. 顶层 `models:` 字典（推荐，用于独立部署）
      2. Hermes `providers:` + `custom_providers:` 格式（自动提取 API Key）
    """
    # 格式 1: 独立配置
    if "models" in cfg:
        return cfg["models"]

    # 格式 2: Hermes 配置 — 自动构建
    models = {}
    providers = cfg.get("providers", {})
    custom = cfg.get("custom_providers", [])

    # 从 Hermes providers 构建
    for pname, pinfo in providers.items():
        if "api_key" not in pinfo:
            continue
        base_url = pinfo.get("base_url", "")
        if not base_url:
            base_url = "https://api.deepseek.com/v1"

        # 从 MOA 配置推断模型名
        moa = cfg.get("moa", {})
        for preset in moa.get("presets", {}).values():
            for ref in preset.get("reference_models", []):
                if ref.get("provider") == pname:
                    mname = ref.get("model")
                    if mname:
                        models[mname] = {
                            "name": mname,
                            "base_url": base_url,
                            "api_key": pinfo["api_key"],
                            "model": mname,
                            "tier": "pro",
                            "multimodal": "seed" in mname or "vision" in mname,
                            "cost": "medium",
                            "speed": "normal",
                        }

    # 从 custom_providers 补充
    for cp in custom:
        for mname, minfo in cp.get("models", {}).items():
            if mname not in models:
                models[mname] = {
                    "name": minfo.get("name", mname),
                    "base_url": cp.get("base_url", "") + "/v1" if not cp.get("base_url", "").endswith("/v1") else cp.get("base_url", ""),
                    "api_key": cp.get("api_key", ""),
                    "model": mname,
                    "tier": "flash" if "flash" in mname else "pro",
                    "multimodal": False,
                    "cost": "low" if "flash" in mname else "high",
                    "speed": "fast" if "flash" in mname else "normal",
                }

    return models

_cfg = load_config()
MODELS = load_models_from_config(_cfg)

# ============================================================
# 分类器 — 基于规则匹配，零延迟
# ============================================================

# 简单/闲聊类 → flash
SIMPLE_GREETINGS = {
    "hi", "hello", "hey", "你好", "您好", "嗨", "在吗", "在不在",
    "早上好", "下午好", "晚上好", "good morning", "good afternoon",
}

SIMPLE_QUERIES = [
    r'^(what|who|when|where)\s+\w+\s*\??$',
    r'^(什么是|怎么|如何|为什么)\s*.{0,20}[？?]$',
    r'(translate|翻译|转换|怎么说)',
    r'(thank|thanks|谢谢|感谢|thx)',
    r'^(ok|okay|好的|明白了|知道了|收到|got it)[\s!！。.,，]*$',
    r'(帮我查|查一下|搜索|搜一下).{0,30}$',
    r'^(现在几点|今天.*日期|今天.*星期)',
    r'(解释一下|简单说|简述|概括).{0,30}$',
]

# 复杂任务类 → pro
COMPLEX_QUERIES = [
    r'(write|编写|生成|创建|实现|implement|build|develop|create)',
    r'(debug|调试|fix|修复|解决|troubleshoot|resolve)',
    r'(analyze|分析|review|审查|审计|audit|examine)',
    r'(optimize|优化|refactor|重构|improve|enhance)',
    r'(design|设计|architect|架构|plan|规划|scheme)',
    r'(research|调研|调查|investigate|explore)',
    r'(多步骤|multi[- ]?step|step\s*by\s*step|逐步)',
    r'(系统.*设计|架构.*设计|技术.*方案)',
    r'```',   # 代码块
    r'(compile|编译|deploy|部署|publish|发布)',
    r'(configure|配置|setup|安装|搭建)',
]

# 视觉/多模态 → doubao
VISION_INDICATORS = [
    r'(image|图片|照片|截图|screenshot|photo|picture|图像)',
    r'(看到|看见|识别|recognize|检测|detect|describe this)',
    r'(这张|这幅|图中|图上|图片里)',
    r'\.(png|jpg|jpeg|gif|webp|bmp)\b',
]

def extract_user_text(messages: list) -> str:
    """从 messages 中提取用户文本，合并多模态内容."""
    parts = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        parts.append("[IMAGE]")
        else:
            parts.append(str(content))
    return " ".join(parts).strip()

def has_image_input(messages: list) -> bool:
    """检查消息中是否包含图片."""
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False

def classify(messages: list) -> tuple[str, str]:
    """
    分类查询 → 返回 (model_key, reason)
    优先级: 图片任务 > 复杂任务 > 简单任务 > 默认pro
    """
    user_text = extract_user_text(messages).lower()
    msg_count = len(messages)
    total_chars = len(user_text)

    # 1. 图片输入 → doubao（多模态最强）
    if has_image_input(messages):
        return "doubao-seed-2-1-pro-260628", "image_input"

    # 1b. 文本中提到图片/视觉相关 → doubao
    for pat in VISION_INDICATORS:
        if re.search(pat, user_text, re.IGNORECASE):
            return "doubao-seed-2-1-pro-260628", f"vision_keyword:{pat[:30]}"

    # 2. 极短的纯问候 → flash
    stripped = user_text.strip().rstrip("!！。.,，?？")
    if stripped.lower() in SIMPLE_GREETINGS or len(stripped) <= 3:
        return "deepseek-v4-flash", "greeting_or_ultra_short"

    # 3. 简单查询模式 → flash
    for pat in SIMPLE_QUERIES:
        if re.search(pat, user_text, re.IGNORECASE):
            return "deepseek-v4-flash", f"simple_pattern:{pat[:30]}"

    # 4. 复杂任务模式 → pro
    for pat in COMPLEX_QUERIES:
        if re.search(pat, user_text, re.IGNORECASE):
            return "deepseek-v4-pro", f"complex_pattern:{pat[:30]}"

    # 5. 消息轮次多 or 上下文长 → pro
    if msg_count > 4 or total_chars > 500:
        return "deepseek-v4-pro", "long_context"

    # 6. 默认 → pro（宁可多花点钱，不要答不好）
    return "deepseek-v4-pro", "default"

# ============================================================
# 输出质量检查
# ============================================================

QUALITY_MIN_LENGTH = {
    "deepseek-v4-pro": 80,
    "deepseek-v4-flash": 5,   # flash 回复可以很短（问候等）
    "doubao-seed-2-1-pro-260628": 50,
}

# 如果用户显式设置了很小的 max_tokens，不触发长度检查
QUALITY_SKIP_IF_MAX_TOKENS_UNDER = 100

REFUSAL_PATTERNS = [
    r'\b(I cannot|I\'m unable|I won\'t|I am not able)\b',
    r'(无法|不能|抱歉.*无法|对不起.*不能)',
    r'\b(as an AI|作为.*AI|作为一个人工智能)\b',
]

def check_quality(response_text: str, model_key: str, max_tokens: int = None) -> tuple[bool, str]:
    """
    检查输出质量。返回 (ok, reason)
    """
    if not response_text or not response_text.strip():
        return False, "empty_response"

    # 如果用户显式请求极短回复，跳过长度检查
    if max_tokens and max_tokens < QUALITY_SKIP_IF_MAX_TOKENS_UNDER:
        return True, "ok(small_max_tokens)"

    # 长度检查
    min_len = QUALITY_MIN_LENGTH.get(model_key, 50)
    if len(response_text.strip()) < min_len:
        return False, f"too_short({len(response_text)}<{min_len})"

    # 拒绝模式检查
    for pat in REFUSAL_PATTERNS:
        if re.search(pat, response_text, re.IGNORECASE):
            return False, f"refusal_pattern:{pat[:30]}"

    # 重复内容检查（幻觉标志）
    lines = response_text.strip().split("\n")
    if len(lines) > 3:
        unique_lines = len(set(line.strip() for line in lines if line.strip()))
        if unique_lines < len(lines) * 0.3:
            return False, "highly_repetitive"

    return True, "ok"

# ============================================================
# 模型调用
# ============================================================

async def call_model(model_key: str, request_data: dict, timeout: int = 120) -> dict:
    """调用指定模型，返回 API 响应字典."""
    info = MODELS[model_key]
    headers = {
        "Authorization": f"Bearer {info['api_key']}",
        "Content-Type": "application/json",
    }
    body = {
        "model": info["model"],
        "messages": request_data.get("messages", []),
        "temperature": request_data.get("temperature", 0.7),
        "max_tokens": request_data.get("max_tokens", 4096),
        "stream": False,
        # 透传其他参数
        **{k: v for k, v in request_data.items()
           if k not in ("messages", "model", "temperature", "max_tokens", "stream")},
    }

    url = f"{info['base_url']}/chat/completions"
    log("DEBUG", f"Calling {model_key} → {url}")

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body, headers=headers)

    if resp.status_code != 200:
        error_detail = resp.text[:500]
        log("WARN", f"{model_key} returned {resp.status_code}: {error_detail}")
        return {"error": True, "status": resp.status_code, "detail": error_detail, "model": model_key}

    data = resp.json()
    return data

# ============================================================
# 路由链：主模型 → 出错回退 → 质量回退 → 最终兜底
# ============================================================

# 回退顺序定义
FALLBACK_CHAIN = {
    "deepseek-v4-flash":  ["deepseek-v4-pro", "doubao-seed-2-1-pro-260628"],
    "deepseek-v4-pro":    ["doubao-seed-2-1-pro-260628"],
    "doubao-seed-2-1-pro-260628": ["deepseek-v4-pro"],
}

async def route_and_call(request_data: dict) -> dict:
    """核心路由逻辑：分类 → 调用 → 检查 → 回退."""
    messages = request_data.get("messages", [])
    primary_model, reason = classify(messages)

    log("INFO", f"Classified → {MODELS[primary_model]['name']} ({reason})")

    # 尝试队列：[primary] + fallback_chain
    attempted = []
    tried_models = [primary_model] + FALLBACK_CHAIN.get(primary_model, [])
    max_tokens = request_data.get("max_tokens")

    for model_key in tried_models:
        if model_key in attempted:
            continue
        attempted.append(model_key)

        resp = await call_model(model_key, request_data)

        # 出错 → 下一个
        if resp.get("error"):
            log("WARN", f"{model_key} API error (HTTP {resp.get('status')}): {resp.get('detail','')[:200]}")
            continue

        # 提取文本内容
        if "choices" in resp and len(resp["choices"]) > 0:
            msg = resp["choices"][0].get("message", {})
            content = msg.get("content", "")
            # DeepSeek V4 Pro 可能把输出放在 reasoning_content 里
            reasoning = msg.get("reasoning_content", "")
            if not content and reasoning:
                content = reasoning
                resp["choices"][0]["message"]["content"] = reasoning  # 补回 content 字段
        else:
            log("WARN", f"{model_key}: no choices in response — body: {json.dumps(resp, ensure_ascii=False)[:300]}")
            continue

        # 质量检查
        ok, qreason = check_quality(content, model_key, max_tokens=max_tokens)
        if ok:
            log("INFO", f"✓ {model_key} OK (quality: {qreason})")
            # 注入路由元信息（不影响正常使用）
            resp["_router"] = {
                "model": model_key,
                "reason": reason,
                "attempts": attempted,
            }
            return resp
        else:
            log("WARN", f"{model_key} quality FAIL ({qreason}), trying next...")
            continue

    # 全部失败 — 返回最后一个非错误响应
    log("ERROR", "All models exhausted!")
    return {
        "error": True,
        "detail": f"All models failed: {attempted}",
        "attempts": attempted,
    }

# ============================================================
# FastAPI 服务器
# ============================================================

app = FastAPI(
    title="Model Router",
    description="Multi-model intelligent routing proxy for Hermes Agent",
    version="1.0.0",
)

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint."""
    try:
        request_data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    result = await route_and_call(request_data)

    if result.get("error"):
        return JSONResponse(result, status_code=502)

    return JSONResponse(result)

@app.get("/v1/models")
async def list_models():
    """List available models."""
    return {
        "object": "list",
        "data": [
            {
                "id": "auto-router",
                "object": "model",
                "owned_by": "model-router",
                "created": 0,
            }
        ],
    }

@app.get("/health")
async def health():
    """Health check + routing stats."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "models": {
            k: {"name": v["name"], "tier": v["tier"], "multimodal": v["multimodal"]}
            for k, v in MODELS.items()
        },
    }

@app.get("/")
async def root():
    return {"service": "Model Router", "docs": "/docs"}

# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("  Model Router v1.0 — 多模型智能路由代理")
    print("=" * 60)
    print(f"  配置来源: {CONFIG_PATH}")
    print(f"  已加载模型:")
    for k, v in MODELS.items():
        tags = []
        if v["multimodal"]:
            tags.append("多模态")
        tags.append(v["tier"])
        print(f"    • {v['name']} ({k}) [{', '.join(tags)}]")
    print("=" * 60)
    print(f"  监听地址: http://127.0.0.1:6060")
    print(f"  API 文档: http://127.0.0.1:6060/docs")
    print("=" * 60)

    uvicorn.run(app, host="127.0.0.1", port=6060, log_level="warning")
