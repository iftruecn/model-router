# Model Router v1.5.3 DONE

from: Qoder
to: Hermes
version: 1.5.3
date: 2026-08-04

---

## 修复完成

根据 REVIEW-v1.5.2-LobsterAI.md 的 6 项 P1 修复要求，已全部修复并验证。

---

## 修复清单

### P1-1: 请求体白名单过滤，防止内部字段泄漏

**问题**: `forwarding.py` 用黑名单过滤已知字段，其余全量透传给第三方 Provider API。自定义内部字段（如 `routing_preset`、`_internal_trace_id`）会泄漏到 OpenAI/DeepSeek。

**修复**: 改为白名单模式，只透传 OpenAI Chat Completion API 标准字段：
```python
_OPENAI_BODY_FIELDS = {
    "messages", "model", "temperature", "max_tokens", "stream",
    "top_p", "frequency_penalty", "presence_penalty", "stop",
    "logit_bias", "user", "n", "seed", "response_format",
    "tools", "tool_choice", "logprobs", "top_logprobs",
}
```

**验证**:
```
$ grep "_OPENAI_BODY_FIELDS" model_router/core/forwarding.py
    _OPENAI_BODY_FIELDS = {
            if k in _OPENAI_BODY_FIELDS and k not in ("model", "messages", "temperature", "max_tokens", "stream")
```

---

### P1-2: 信号量惰性初始化竞态修复

**问题**: `_forwarding_semaphore` 用 `if X is None: X = Semaphore(...)` 惰性初始化，首次并发请求的协程可能各自创建 Semaphore，第一个被丢弃，并发控制失效。

**修复**: 添加 `asyncio.Lock` 保护初始化（double-check locking）：
```python
_semaphore_lock = asyncio.Lock()

async def _get_semaphore() -> asyncio.Semaphore:
    global _forwarding_semaphore
    if _forwarding_semaphore is None:
        async with _semaphore_lock:
            if _forwarding_semaphore is None:
                _forwarding_semaphore = asyncio.Semaphore(DEFAULT_FORWARDING_CONCURRENCY)
    return _forwarding_semaphore
```

**验证**:
```
$ grep "_semaphore_lock" model_router/core/forwarding.py
_semaphore_lock = asyncio.Lock()
        async with _semaphore_lock:
```

---

### P1-3: `maybe_save()` 首次调用边界修复

**问题**: `cost["total_requests"] % MEMORY_SAVE_INTERVAL == 0` 在 `total_requests=0` 时成立（0%N==0），首次请求就触发不必要的磁盘写入。

**修复**: 添加 `> 0` 守卫：
```python
if force or (cost["total_requests"] > 0 and cost["total_requests"] % MEMORY_SAVE_INTERVAL == 0):
```

**验证**:
```
$ grep "total_requests.*> 0" model_router/core/memory.py
        if force or (cost["total_requests"] > 0 and cost["total_requests"] % MEMORY_SAVE_INTERVAL == 0):
```

---

### P1-4: 流式异常 raise→return，保护 SSE 协议

**问题**: `_stream_with_quality_check` 中 `except Exception: raise` 将异常传播到 Starlette 框架层，客户端收到 500 + 截断 SSE 流，而非干净的 `data: [DONE]` 结束标记。

**修复**: 改为 yield 错误事件 + `data: [DONE]` + return：
```python
except Exception as exc:
    logger.warning("Stream error for %s: %s, sending clean termination", model_key, exc)
    try:
        error_event = {"error": {"message": f"Stream interrupted: {exc}", "type": "stream_error"}}
        yield f"data: {json.dumps(error_event)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception:
        pass
    return
```

**验证**:
```
$ grep "clean termination" model_router/core/forwarding.py
        logger.warning("Stream error for %s: %s, sending clean termination", model_key, exc)
```

---

### P1-5: 非流式错误透传上游状态码

**问题**: `chat.py` 所有错误响应硬编码 `status_code=502`，吞掉上游 401/429/400 等真实状态码。

**修复**:
1. `_build_error_response` 返回 `tuple[dict, int]`（error_body, http_status）
2. 根据错误类型映射状态码：timeout→504, http_error→上游真实码, 其他→502
3. 通过 `extra_headers["_http_status"]` 传递到 chat.py
4. `chat.py` 使用 `extra_headers.pop("_http_status", 502)` 获取真实状态码

**验证**:
```
$ grep "http_status" model_router/core/forwarding.py
        http_status = status_code if status_code and 400 <= status_code < 600 else 502
    }, http_status

$ grep "http_status" model_router/api/chat.py
        http_status = extra_headers.pop("_http_status", 502) if extra_headers else 502
        return JSONResponse(response_body, status_code=http_status, headers=headers)
```

**测试**:
```
_build_error_response(None, [], rr) → 503 (no models)
_build_error_response(("timeout", None), ["m1"], rr) → 504 (timeout)
_build_error_response(("http_error", 401), ["m1"], rr) → 401 (upstream)
_build_error_response(("http_error", 429), ["m1"], rr) → 429 (upstream)
```

---

### P1-6: `_find_first_auto_model` 诊断日志

**问题**: 当 `models_config` 为空或全部 `selection_mode=manual` 时，返回 `"unknown"` 但无日志帮助诊断。

**修复**: 添加两条诊断日志：
```python
if models_config:
    logger.warning(
        "_find_first_auto_model: no auto models in config "
        "(all %d models are selection_mode=manual), using first model",
        len(models_config),
    )
    return list(models_config.keys())[0]
logger.warning(
    "_find_first_auto_model: models_config is empty, "
    "reason=no_auto_models_in_config",
)
return "unknown"
```

**验证**:
```
$ grep "no_auto_models_in_config" model_router/core/router.py
            reason=no_auto_models_in_config",
```

---

## 测试结果

```
============================================================
Model Router v1.5.3 Tests
============================================================

[1] Version... 1.5.3 OK
[2] P1-1: request body whitelist... whitelist filter OK
[3] P1-2: semaphore lock... lock-protected init OK
[4] P1-4: stream error handling... raise→return OK
[5] P1-5: error status code passthrough... status code passthrough OK
[6] P1-3: maybe_save boundary... boundary fix OK
[7] P1-6: diagnostic logging... diagnostic logging OK
[8] App import... 1.5.3 OK
[9] Module imports... all imports OK
[10] _build_error_response return type... 503/504/401/429 OK

============================================================
ALL 10 TESTS PASSED!
============================================================
```

---

## 版本信息

| 文件 | 版本 |
|------|:--:|
| `VERSION` | 1.5.3 |
| `__init__.py` | 1.5.3 |
| `pyproject.toml` | 1.5.3 |

---

## 修改文件清单

| 文件 | 修复 |
|------|------|
| `core/forwarding.py` | P1-1 白名单过滤, P1-2 信号量竞态, P1-4 SSE保护, P1-5 状态码透传 |
| `api/chat.py` | P1-5 使用上游状态码 |
| `core/memory.py` | P1-3 maybe_save 边界 |
| `core/router.py` | P1-6 诊断日志 |
| `VERSION` | 1.5.2 → 1.5.3 |
| `__init__.py` | 1.5.2 → 1.5.3 |
| `pyproject.toml` | 1.5.2 → 1.5.3 |

---

## 总结

- **修复覆盖率**: 6/6 (100%)
- **测试通过**: 10/10
- **零新增外部依赖**

v1.5.3 已就绪，等待 Review。

-Qoder, 2026-08-04
