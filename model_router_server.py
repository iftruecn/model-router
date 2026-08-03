#!/usr/bin/env python3
"""
Model Router v1.0 — Multi-Model Intelligent Routing Proxy
==========================================================
Author:  iftrue-hermes
License: MIT

OpenAI-compatible local proxy that automatically routes requests across
multiple LLMs based on task complexity, with automatic fallback on poor output.

多模型智能路由代理 — 根据任务复杂度自动选择合适的 LLM，
输出质量不满意时自动切换模型重试。

Usage / 用法:
  python model_router_server.py
  → listens on http://127.0.0.1:6060

Config / 配置:
  Copy config.example.yaml to config.yaml, fill in your API keys and models.
  复制 config.example.yaml 为 config.yaml，填入你的 API Key 和模型。
"""

import yaml
import httpx
import json
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ═══════════════════════════════════════════════════════════
# Configuration / 配置
# Priority / 优先级: env var > ./config.yaml > ./config.example.yaml
# ═══════════════════════════════════════════════════════════

def find_config() -> Path:
    """Find config file / 查找配置文件."""
    env = os.environ.get("MODEL_ROUTER_CONFIG")
    if env and Path(env).exists():
        return Path(env)
    local = Path("config.yaml")
    if local.exists():
        return local
    example = Path("config.example.yaml")
    if example.exists():
        print("[WARN] Using config.example.yaml — copy to config.yaml and add your API keys!")
        print("[WARN] 正在使用示例配置 — 请复制为 config.yaml 并填入 API Key！")
        return example
    raise FileNotFoundError(
        "No config.yaml found. Copy config.example.yaml → config.yaml\n"
        "未找到 config.yaml，请复制 config.example.yaml → config.yaml"
    )

CONFIG_PATH = find_config()

def log(level: str, msg: str):
    """Timestamped logging / 带时间戳的日志."""
    print(f"[{datetime.now():%H:%M:%S}] [{level}] {msg}", flush=True)

def load_config() -> dict:
    """Load config with ${ENV_VAR} resolution / 加载配置，自动解析环境变量."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = f.read()

    # Resolve ${VAR} → env value / 替换 ${变量} 为环境变量值
    def resolve_env(match):
        var = match.group(1)
        return os.environ.get(var, match.group(0))

    resolved = re.sub(r'\$\{(\w+)\}', resolve_env, raw)
    return yaml.safe_load(resolved)

_cfg = load_config()
MODELS = _cfg.get("models", {})
FALLBACK_CHAIN = _cfg.get("fallback_chain", {})

if not MODELS:
    raise ValueError(
        "No models defined in config. Add models to config.yaml (see config.example.yaml)\n"
        "配置中未定义任何模型，请在 config.yaml 中添加模型（参考 config.example.yaml）"
    )

# ═══════════════════════════════════════════════════════════
# Classifier — zero-latency rule-based matching
# 分类器 — 基于规则的零延迟匹配
# ═══════════════════════════════════════════════════════════

# Simple greetings → flash tier / 简单问候 → flash 层
SIMPLE_GREETINGS = {
    "hi", "hello", "hey", "你好", "您好", "嗨", "在吗",
    "早上好", "下午好", "晚上好", "good morning", "good afternoon",
}

# Simple query patterns → flash tier / 简单查询模式 → flash 层
SIMPLE_QUERIES = [
    r'^(what|who|when|where)\s+\w+\s*\??$',
    r'(translate|翻译|转换|怎么说)',
    r'(thank|thanks|谢谢|感谢|thx)',
    r'^(ok|okay|好的|明白了|知道了|收到|got it)[\s!！。.,，]*$',
    r'(帮我查|查一下|搜索|搜一下).{0,30}$',
    r'^(现在几点|今天.*日期)',
    r'(解释一下|简单说|简述|概括).{0,30}$',
]

# Complex task patterns → pro tier / 复杂任务模式 → pro 层
COMPLEX_QUERIES = [
    r'(write|编写|生成|创建|implement|build|develop|create)',
    r'(debug|调试|fix|修复|解决|troubleshoot|resolve)',
    r'(analyze|分析|review|审查|审计|audit|examine)',
    r'(optimize|优化|refactor|重构|improve|enhance)',
    r'(design|设计|architect|架构|plan|规划|scheme)',
    r'(research|调研|调查|investigate|explore)',
    r'(multi[- ]?step|step\s*by\s*step|逐步)',
    r'(系统.*设计|架构.*设计|技术.*方案)',
    r'```',
    r'(compile|编译|deploy|部署|publish|发布)',
    r'(configure|配置|setup|安装|搭建)',
]

# Vision-related → multimodal / 视觉相关 → 多模态模型
VISION_INDICATORS = [
    r'(image|图片|照片|截图|screenshot|photo|picture|图像)',
    r'(看到|看见|识别|recognize|检测|detect|describe this)',
    r'(这张|这幅|图中|图上|图片里)',
    r'\.(png|jpg|jpeg|gif|webp|bmp)\b',
]

def extract_user_text(messages: list) -> str:
    """Extract user text from messages, handle multimodal content.
    从消息中提取用户文本，处理多模态内容。"""
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
    """Check if messages contain image data / 检查消息是否包含图片."""
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False

def classify(messages: list) -> tuple:
    """
    Classify query → return (model_key, reason).
    分类查询 → 返回 (模型名, 原因).

    Priority / 优先级:
      image input → multimodal > complex patterns → pro >
      simple patterns → flash > long context → pro > default → pro
    """
    user_text = extract_user_text(messages).lower()
    msg_count = len(messages)
    total_chars = len(user_text)

    # Group models by tier / 按层级分组
    flash_models = [k for k, v in MODELS.items() if v.get("tier") == "flash"]
    pro_models   = [k for k, v in MODELS.items() if v.get("tier") == "pro"]
    multi_models = [k for k, v in MODELS.items() if v.get("multimodal")]
    default_pro  = pro_models[0] if pro_models else list(MODELS.keys())[0]
    default_flash = flash_models[0] if flash_models else default_pro
    default_multi = multi_models[0] if multi_models else default_pro

    # 1. Image input → multimodal / 图片输入 → 多模态
    if has_image_input(messages) and multi_models:
        return default_multi, "image_input"

    # 2. Text mentions vision → multimodal / 文字提到视觉 → 多模态
    for pat in VISION_INDICATORS:
        if re.search(pat, user_text, re.IGNORECASE):
            if multi_models:
                return default_multi, "vision_keyword"

    # 3. Ultra-short greetings → flash / 极短问候 → flash
    stripped = user_text.strip().rstrip("!！。.,，?？")
    if stripped.lower() in SIMPLE_GREETINGS or len(stripped) <= 3:
        return default_flash, "greeting_or_ultra_short"

    # 4. Simple queries → flash / 简单查询 → flash
    for pat in SIMPLE_QUERIES:
        if re.search(pat, user_text, re.IGNORECASE):
            return default_flash, "simple_pattern"

    # 5. Complex tasks → pro / 复杂任务 → pro
    for pat in COMPLEX_QUERIES:
        if re.search(pat, user_text, re.IGNORECASE):
            return default_pro, "complex_pattern"

    # 6. Long context → pro / 长上下文 → pro
    if msg_count > 4 or total_chars > 500:
        return default_pro, "long_context"

    # 7. Default → pro (better safe than cheap)
    # 默认 → pro（宁可贵一点，不要答不好）
    return default_pro, "default"

# ═══════════════════════════════════════════════════════════
# Output Quality Check / 输出质量检查
# ═══════════════════════════════════════════════════════════

# Minimum acceptable length by tier / 各层级最低接受长度
QUALITY_MIN_LENGTH = {
    "flash": 5,
    "pro": 80,
}
# Skip length check if user explicitly requested very short output
# 用户显式请求极短输出时跳过长度检查
QUALITY_SKIP_IF_MAX_TOKENS_UNDER = 100

# Patterns that indicate refusal or low-quality output
# 表示拒绝或低质量输出的模式
REFUSAL_PATTERNS = [
    r'\b(I cannot|I\'m unable|I won\'t|I am not able)\b',
    r'(无法|不能|抱歉.*无法|对不起.*不能)',
    r'\b(as an AI|作为.*AI|作为一个人工智能)\b',
]

def check_quality(response_text: str, model_key: str, max_tokens: int = None) -> tuple:
    """
    Check output quality. Returns (ok, reason).
    检查输出质量。返回 (是否通过, 原因).
    """
    if not response_text or not response_text.strip():
        return False, "empty_response"

    # Skip length check for explicit short-output requests
    # 用户显式要求短输出时跳过长度检查
    if max_tokens and max_tokens < QUALITY_SKIP_IF_MAX_TOKENS_UNDER:
        return True, "ok(small_max_tokens)"

    tier = MODELS.get(model_key, {}).get("tier", "pro")
    min_len = QUALITY_MIN_LENGTH.get(tier, 50)
    if len(response_text.strip()) < min_len:
        return False, f"too_short({len(response_text)}<{min_len})"

    # Check for refusal language / 检查拒绝用语
    for pat in REFUSAL_PATTERNS:
        if re.search(pat, response_text, re.IGNORECASE):
            return False, "refusal_pattern"

    # Check for repetitive content (hallucination marker)
    # 检查重复内容（幻觉标志）
    lines = response_text.strip().split("\n")
    if len(lines) > 3:
        unique = len(set(line.strip() for line in lines if line.strip()))
        if unique < len(lines) * 0.3:
            return False, "highly_repetitive"

    return True, "ok"

# ═══════════════════════════════════════════════════════════
# Model API Call / 模型 API 调用
# ═══════════════════════════════════════════════════════════

async def call_model(model_key: str, request_data: dict, timeout: int = 120) -> dict:
    """Call a model API. 调用指定模型的 API."""
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
        **{k: v for k, v in request_data.items()
           if k not in ("messages", "model", "temperature", "max_tokens", "stream")},
    }

    url = f"{info['base_url'].rstrip('/')}/chat/completions"
    log("DEBUG", f"Calling {model_key} → {url}")

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body, headers=headers)

    if resp.status_code != 200:
        error_detail = resp.text[:500]
        log("WARN", f"{model_key} returned {resp.status_code}: {error_detail}")
        return {"error": True, "status": resp.status_code, "detail": error_detail, "model": model_key}

    return resp.json()

# ═══════════════════════════════════════════════════════════
# Core Router: classify → call → check → fallback
# 核心路由：分类 → 调用 → 检查 → 回退
# ═══════════════════════════════════════════════════════════

def build_fallback_chain(primary: str) -> list:
    """
    Build fallback order. Uses explicit FALLBACK_CHAIN if defined,
    otherwise auto-builds from model tiers.
    构建回退顺序。优先用显式定义的 FALLBACK_CHAIN，
    否则按模型层级自动构建。
    """
    chain = FALLBACK_CHAIN.get(primary, [])
    if not chain:
        tier = MODELS.get(primary, {}).get("tier", "pro")
        others = [k for k in MODELS if k != primary]
        same_tier = [k for k in others if MODELS[k].get("tier") == tier]
        other_tier = [k for k in others if MODELS[k].get("tier") != tier]
        chain = same_tier + other_tier
    return chain

async def route_and_call(request_data: dict) -> dict:
    """
    Main routing logic / 主路由逻辑:
      1. Classify query / 分类查询
      2. Call primary model / 调用首选模型
      3. Check output quality / 检查输出质量
      4. Fallback if needed / 不满意则回退
    """
    messages = request_data.get("messages", [])
    primary_model, reason = classify(messages)

    model_name = MODELS.get(primary_model, {}).get("name", primary_model)
    log("INFO", f"Classified → {model_name} ({reason})")

    attempted = []
    tried_models = [primary_model] + build_fallback_chain(primary_model)
    max_tokens = request_data.get("max_tokens")

    for model_key in tried_models:
        if model_key in attempted:
            continue
        attempted.append(model_key)

        resp = await call_model(model_key, request_data)

        # API error → try next / API 报错 → 下一个
        if resp.get("error"):
            log("WARN", f"{model_key} API error (HTTP {resp.get('status')}): {resp.get('detail','')[:200]}")
            continue

        # Extract content, handle reasoning_content (DeepSeek V4 Pro chain-of-thought)
        # 提取内容，处理 reasoning_content（DeepSeek V4 Pro 思维链）
        if "choices" in resp and len(resp["choices"]) > 0:
            msg = resp["choices"][0].get("message", {})
            content = msg.get("content", "")
            reasoning = msg.get("reasoning_content", "")
            if not content and reasoning:
                content = reasoning
                resp["choices"][0]["message"]["content"] = reasoning
        else:
            log("WARN", f"{model_key}: no choices — body: {json.dumps(resp, ensure_ascii=False)[:300]}")
            continue

        # Quality check / 质量检查
        ok, qreason = check_quality(content, model_key, max_tokens=max_tokens)
        if ok:
            log("INFO", f"✓ {model_key} OK (quality: {qreason})")
            resp["_router"] = {"model": model_key, "reason": reason, "attempts": attempted}
            return resp
        else:
            log("WARN", f"{model_key} quality FAIL ({qreason}), trying next...")

    # All models exhausted / 全部模型均失败
    log("ERROR", "All models exhausted!")
    return {"error": True, "detail": f"All models failed: {attempted}", "attempts": attempted}

# ═══════════════════════════════════════════════════════════
# FastAPI Server / FastAPI 服务器
# ═══════════════════════════════════════════════════════════

app = FastAPI(
    title="Model Router",
    description="Multi-model intelligent routing proxy — routes to the right model for each task / 多模型智能路由代理",
    version="1.0.0",
)

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions / OpenAI 兼容的对话接口."""
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
    """List available models / 列出可用模型."""
    return {
        "object": "list",
        "data": [{"id": "auto-router", "object": "model", "owned_by": "model-router"}],
    }

@app.get("/health")
async def health():
    """Health check + model list / 健康检查 + 模型列表."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "models": {
            k: {"name": v.get("name", k), "tier": v.get("tier", "?"), "multimodal": v.get("multimodal", False)}
            for k, v in MODELS.items()
        },
    }

@app.get("/")
async def root():
    return {"service": "Model Router", "docs": "/docs"}

# ═══════════════════════════════════════════════════════════
# Entry Point / 入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("  Model Router v1.0 — Multi-Model Intelligent Routing Proxy")
    print("  by iftrue-hermes / MIT License")
    print("=" * 60)
    print(f"  Config / 配置: {CONFIG_PATH}")
    print(f"  Loaded models / 已加载模型:")
    for k, v in MODELS.items():
        tags = [v.get("tier", "?")]
        if v.get("multimodal"):
            tags.append("multimodal")
        print(f"    • {v.get('name', k)} ({k}) [{', '.join(tags)}]")
    print("=" * 60)
    print(f"  Listening / 监听: http://127.0.0.1:6060")
    print(f"  API Docs / 文档: http://127.0.0.1:6060/docs")
    print("=" * 60)

    uvicorn.run(app, host="127.0.0.1", port=6060, log_level="warning")
