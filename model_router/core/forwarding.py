"""
Provider forwarding layer (v1.0.7).

Bridges the routing decision to actual model provider API calls.
Handles:
- Non-streaming forwarding with fallback chain
- Streaming forwarding with fallback chain
- Post-response learning loop (record_outcome)
- Semantic cache auto-fill on successful non-streaming responses

Design constraints:
- All providers are OpenAI-compatible (/v1/chat/completions)
- Fallback chain is walked only on fallback-worthy errors (5xx, timeout, 429)
- Client errors (400/401/403/404) never trigger fallback
- Learning outcome is recorded asynchronously (best-effort)
- Cache auto-fill only happens for non-streaming successful responses
"""

import asyncio
import json
import logging
import time
from typing import AsyncGenerator, Optional

import httpx

from model_router.config.defaults import DEFAULT_FORWARDING_CONCURRENCY
from model_router.core.cache import semantic_cache
from model_router.core.quality import quality_checker
from model_router.core.fallback import (
    FallbackManager,
    fallback_manager,
    should_fallback_on_error,
)
from model_router.core.memory import memory_store
from model_router.core.router import RoutingResult, smart_router
from model_router.providers.pool import pool

logger = logging.getLogger(__name__)

# Concurrency limiter: prevents connection pool exhaustion under load
_forwarding_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init semaphore (must be created inside running event loop)."""
    global _forwarding_semaphore
    if _forwarding_semaphore is None:
        _forwarding_semaphore = asyncio.Semaphore(DEFAULT_FORWARDING_CONCURRENCY)
    return _forwarding_semaphore


# ------------------------------------------------------------------
# Non-streaming forwarding
# ------------------------------------------------------------------

async def forward_non_streaming(
    request_data: dict,
    request_id: str,
    routing: RoutingResult,
    models_config: dict,
    fallback_chain_config: Optional[dict] = None,
) -> tuple[dict, dict]:
    """
    Forward a non-streaming request to the selected model, with fallback.

    Returns (response_body, extra_headers).
    response_body is the raw JSON dict from the provider.
    extra_headers includes X-Routing-Fallback etc. if fallback was walked.
    """
    fallback_chain_config = fallback_chain_config or {}
    start_time = time.time()
    sem = _get_semaphore()

    async with sem:
        return await _forward_non_streaming_inner(
            request_data, request_id, routing, models_config,
            fallback_chain_config, start_time,
        )


async def _forward_non_streaming_inner(
    request_data: dict,
    request_id: str,
    routing: RoutingResult,
    models_config: dict,
    fallback_chain_config: dict,
    start_time: float,
) -> tuple[dict, dict]:
    """Inner implementation of non-streaming forwarding (under semaphore)."""

    # Build fallback chain: primary + fallbacks
    chain = fallback_manager.build_chain(
        primary_model=routing.model_key,
        fallback_chain_config=fallback_chain_config,
        models_config=models_config,
    )

    failed_models = []
    last_error = None

    for model_key in chain:
        model_cfg = models_config.get(model_key)
        if not model_cfg:
            logger.warning("Model %s not in config, skipping", model_key)
            failed_models.append(model_key)
            continue

        try:
            response_body = await _call_provider(model_key, model_cfg, request_data)
            latency_ms = (time.time() - start_time) * 1000

            # Quality check: verify response is not empty/refusal/repetitive
            response_text = _extract_response_text(response_body)
            quality_result = quality_checker.check(
                response_text=response_text,
                model_key=model_key,
                models_config=models_config,
                max_tokens=request_data.get("max_tokens"),
            )
            if not quality_result.passed:
                logger.warning(
                    "Quality check failed for %s: %s",
                    model_key, quality_result.reason,
                )
                failed_models.append(model_key)
                continue  # try next model in fallback chain

            # Success! Record fallback trail
            if failed_models:
                routing.record_fallback(failed_models, model_key)

            # Post-response: learning loop (best-effort)
            try:
                await smart_router.record_outcome(
                    request_id=request_id,
                    quality_passed=True,
                    latency_ms=latency_ms,
                )
            except Exception as exc:
                logger.debug("Learning record failed (ignored): %s", exc)

            # Post-response: update request log with fallback trail + latency
            try:
                entry = memory_store.get_request(request_id)
                if entry is not None:
                    entry["failed_models"] = list(failed_models)
                    entry["latency_ms"] = round(latency_ms, 1)
            except Exception as exc:
                logger.debug("Request log update failed (ignored): %s", exc)

            # Post-response: auto-fill semantic cache
            try:
                await semantic_cache.async_store(
                    messages=request_data.get("messages", []),
                    response=response_body,
                    model=model_key,
                )
            except Exception as exc:
                logger.debug("Cache auto-fill failed (ignored): %s", exc)

            return response_body, {}

        except httpx.TimeoutException:
            logger.warning("Model %s timed out", model_key)
            failed_models.append(model_key)
            last_error = ("timeout", None)
            should_retry, _ = should_fallback_on_error(None, is_timeout=True)
            if not should_retry:
                break

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response else None
            logger.warning("Model %s returned %s", model_key, status)
            failed_models.append(model_key)
            last_error = ("http_error", status)
            should_retry, category = should_fallback_on_error(status)
            if not should_retry:
                logger.info(
                    "Client error %s (%s) — not retrying fallback",
                    status, category,
                )
                break

        except Exception as exc:
            logger.warning("Model %s failed: %s", model_key, exc)
            failed_models.append(model_key)
            last_error = ("unknown", None)

    # All models in chain failed
    return _build_error_response(last_error, failed_models, routing), {}


# ------------------------------------------------------------------
# Streaming forwarding
# ------------------------------------------------------------------

async def forward_streaming(
    request_data: dict,
    request_id: str,
    routing: RoutingResult,
    models_config: dict,
    fallback_chain_config: Optional[dict] = None,
) -> tuple[Optional[AsyncGenerator], Optional[dict]]:
    """
    Forward a streaming request to the selected model, with fallback.

    Returns (generator, extra_headers) on success.
    Returns (error_generator, extra_headers) on failure.

    Note: Once streaming starts, we cannot switch models mid-stream.
    Fallback only applies to pre-stream failures (connection, auth, etc.).
    """
    from model_router.api.streaming import stream_model_response

    fallback_chain_config = fallback_chain_config or {}
    sem = _get_semaphore()

    async with sem:
        return await _forward_streaming_inner(
            request_data, request_id, routing, models_config,
            fallback_chain_config, stream_model_response,
        )


async def _forward_streaming_inner(
    request_data: dict,
    request_id: str,
    routing: RoutingResult,
    models_config: dict,
    fallback_chain_config: dict,
    stream_model_response,
) -> tuple[Optional[AsyncGenerator], Optional[dict]]:
    """Inner implementation of streaming forwarding (under semaphore)."""

    # Build fallback chain
    chain = fallback_manager.build_chain(
        primary_model=routing.model_key,
        fallback_chain_config=fallback_chain_config,
        models_config=models_config,
    )

    failed_models = []

    for model_key in chain:
        model_cfg = models_config.get(model_key)
        if not model_cfg:
            logger.warning("Model %s not in config, skipping", model_key)
            failed_models.append(model_key)
            continue

        # Build model_info for streaming module
        model_info = {
            "api_key": model_cfg.get("api_key", ""),
            "base_url": model_cfg.get("base_url", ""),
            "model": model_cfg.get("model", model_key),
        }

        # Pre-flight check: if api_key or base_url is missing, skip
        if not model_info["api_key"] or not model_info["base_url"]:
            logger.warning(
                "Model %s missing api_key or base_url, skipping", model_key
            )
            failed_models.append(model_key)
            continue

        # Success: this model will handle the request
        if failed_models:
            routing.record_fallback(failed_models, model_key)

        generator = stream_model_response(
            model_key=model_key,
            model_info=model_info,
            request_data=request_data,
        )
        return generator, {}

    # All models failed
    async def error_generator():
        error_data = {
            "error": {
                "message": f"All models in fallback chain failed ({len(chain)} tried)",
                "type": "all_models_failed",
            }
        }
        yield f"data: {json.dumps(error_data)}\n\n"
        yield "data: [DONE]\n\n"

    if failed_models:
        routing.record_fallback(failed_models, chain[-1] if chain else routing.model_key)

    return error_generator(), {}



# ------------------------------------------------------------------
# Response text extraction (for quality checking)
# ------------------------------------------------------------------

def _extract_response_text(response_body: dict) -> str:
    """Extract the assistant's response text from OpenAI-format response."""
    try:
        choices = response_body.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            return message.get("content", "")
    except (AttributeError, IndexError):
        pass
    return ""


# ------------------------------------------------------------------
# Provider call (non-streaming)
# ------------------------------------------------------------------

async def _call_provider(
    model_key: str,
    model_cfg: dict,
    request_data: dict,
) -> dict:
    """
    Make a non-streaming API call to the provider.

    Raises httpx.TimeoutException or httpx.HTTPStatusError on failure.
    """
    api_key = model_cfg.get("api_key", "")
    base_url = model_cfg.get("base_url", "")
    model_name = model_cfg.get("model", model_key)

    if not api_key or not base_url:
        raise ValueError(f"Missing api_key or base_url for model {model_key}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = {
        "model": model_name,
        "messages": request_data.get("messages", []),
        "temperature": request_data.get("temperature", 0.7),
        "max_tokens": request_data.get("max_tokens", 4096),
        "stream": False,
        **{
            k: v
            for k, v in request_data.items()
            if k not in ("messages", "model", "temperature", "max_tokens", "stream")
        },
    }

    url = f"{base_url.rstrip('/')}/chat/completions"
    logger.debug("Calling %s -> %s (model=%s)", model_key, url, model_name)

    client = pool.get_client(base_url)
    response = await client.post(url, json=body, headers=headers)
    response.raise_for_status()

    return response.json()


# ------------------------------------------------------------------
# Error response builder
# ------------------------------------------------------------------

def _build_error_response(
    last_error: Optional[tuple],
    failed_models: list,
    routing: RoutingResult,
) -> dict:
    """Build an OpenAI-compatible error response."""
    if last_error is None:
        return {
            "error": {
                "message": "No models available to handle request",
                "type": "no_models_available",
            }
        }

    error_type, status_code = last_error

    if error_type == "timeout":
        message = f"All models timed out ({len(failed_models)} tried)"
        error_type_str = "timeout"
    elif error_type == "http_error":
        message = f"All models failed ({len(failed_models)} tried, last HTTP {status_code})"
        error_type_str = "all_models_failed"
    else:
        message = f"All models failed ({len(failed_models)} tried)"
        error_type_str = "all_models_failed"

    return {
        "error": {
            "message": message,
            "type": error_type_str,
            "failed_models": failed_models,
        }
    }
