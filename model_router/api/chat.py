"""
Chat completions route for Model Router v1.0.2.

Handles both streaming and non-streaming requests,
integrating with the core router for model selection and fallback.

v1.0.2: real routing decision + transparency headers
(X-Routed-To / X-Routing-Reason / X-Routing-Mode / X-Routing-Preset).
v1.0.4+: in-band capability hot sensing via X-Agent-Capabilities headers.
Provider forwarding follows in the streaming integration task.
"""

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from model_router.api.streaming import stream_model_response
from model_router.core.cache import semantic_cache
from model_router.core.capabilities import capability_registry
from model_router.core.router import RoutingResult, smart_router

logger = logging.getLogger(__name__)

router = APIRouter()


def _observe_agent_capabilities(request: Request) -> None:
    """
    In-band hot sensing (FR-热感知 §2.2): compare the capability
    fingerprint riding on this request with the known one; refresh
    instantly when the full declaration comes along.

    Best-effort: any failure is swallowed — sensing never breaks routing.
    """
    fingerprint = request.headers.get("x-agent-capabilities", "")
    if not fingerprint:
        return
    agent_id = request.headers.get("x-agent-id", "default")
    full_b64 = request.headers.get("x-agent-capabilities-full", "")
    try:
        result = capability_registry.observe(agent_id, fingerprint, full_b64)
    except Exception as exc:  # noqa: BLE001 — isolation is a hard constraint
        logger.warning("Capability sensing failed (ignored): %s", exc)
        return
    if result.get("action") == "hot_updated":
        logger.info(
            "Agent '%s' capabilities hot-updated: %s", agent_id, result["diff"]
        )
    elif result.get("action") == "needs_full":
        logger.info(
            "Agent '%s' capability fingerprint changed; awaiting full "
            "declaration (X-Agent-Capabilities-Full)",
            agent_id,
        )


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    """
    OpenAI-compatible chat completions endpoint.

    Supports both streaming (stream=true) and non-streaming modes.
    Integrates with core router for model classification and fallback.

    Supports per-request routing preset via "routing_preset" field:
        {"messages": [...], "routing_preset": "cost"}
    """
    try:
        request_data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # In-band capability hot sensing (rides along, never blocks)
    _observe_agent_capabilities(request)

    is_streaming = request_data.get("stream", False)
    request_id = getattr(request.state, "request_id", "unknown")

    # Semantic cache: similar non-streaming questions short-circuit here
    if not is_streaming:
        cached = semantic_cache.lookup(request_data.get("messages", []))
        if cached is not None:
            logger.info(
                "Request %s served from semantic cache "
                "(sim=%.3f, age=%.1fs, model=%s)",
                request_id, cached["similarity"],
                cached["age_seconds"], cached["model"],
            )
            return JSONResponse(
                cached["response"],
                headers={
                    "X-Request-Id": request_id,
                    "X-Routing-Cache": "hit",
                    "X-Routing-Cache-Similarity": str(cached["similarity"]),
                },
            )

    models_config = getattr(request.app.state, "models_config", {})

    logger.info(
        "Request %s: stream=%s, messages=%d",
        request_id,
        is_streaming,
        len(request_data.get("messages", [])),
    )

    # Route the request (explicit model selection is respected inside)
    routing = await smart_router.route(
        messages=request_data.get("messages", []),
        models_config=models_config,
        request_data=request_data,
        request_id=request_id,
    )

    if is_streaming:
        return await _handle_streaming(request_data, request_id, routing)
    else:
        return await _handle_non_streaming(request_data, request_id, routing)


async def _handle_streaming(
    request_data: dict, request_id: str, routing: RoutingResult
) -> StreamingResponse:
    """Handle streaming chat completion request."""
    logger.info(
        "Streaming request %s routed to %s (mode=%s)",
        request_id, routing.model_key, routing.routing_mode,
    )

    # Placeholder: provider forwarding lands in the streaming integration task
    async def generate():
        yield 'data: {"error": {"message": "Router integration pending", "type": "not_implemented"}}\n\n'
        yield "data: [DONE]\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Request-Id": request_id,
        **routing.to_headers(),
    }
    return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)


async def _handle_non_streaming(
    request_data: dict, request_id: str, routing: RoutingResult
) -> JSONResponse:
    """Handle non-streaming chat completion request."""
    logger.info(
        "Non-streaming request %s routed to %s (mode=%s)",
        request_id, routing.model_key, routing.routing_mode,
    )

    headers = {"X-Request-Id": request_id, **routing.to_headers()}
    return JSONResponse(
        {
            "error": {
                "message": "Router integration pending",
                "type": "not_implemented",
            },
            "routing": routing.to_dict(),
        },
        status_code=501,
        headers=headers,
    )
