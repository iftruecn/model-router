"""
Chat completions route for Model Router.

Handles both streaming and non-streaming requests,
integrating with the core router for model selection and fallback.
"""

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from model_router.api.streaming import stream_model_response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    """
    OpenAI-compatible chat completions endpoint.

    Supports both streaming (stream=true) and non-streaming modes.
    Integrates with core router for model classification and fallback.
    """
    try:
        request_data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    is_streaming = request_data.get("stream", False)
    request_id = getattr(request.state, "request_id", "unknown")

    logger.info(
        "Request %s: stream=%s, messages=%d",
        request_id,
        is_streaming,
        len(request_data.get("messages", [])),
    )

    # TODO: Integrate with core router for model selection
    # For now, this is a placeholder that demonstrates streaming support
    # The full integration will be added when core router is connected

    if is_streaming:
        return await _handle_streaming(request_data, request_id)
    else:
        return await _handle_non_streaming(request_data, request_id)


async def _handle_streaming(request_data: dict, request_id: str) -> StreamingResponse:
    """Handle streaming chat completion request."""
    # TODO: Get model from router
    # For now, use a placeholder
    logger.info("Streaming request %s - router integration pending", request_id)

    # Placeholder: will be replaced with actual router logic
    async def generate():
        yield 'data: {"error": {"message": "Router integration pending", "type": "not_implemented"}}\n\n'
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-Id": request_id,
        },
    )


async def _handle_non_streaming(request_data: dict, request_id: str) -> JSONResponse:
    """Handle non-streaming chat completion request."""
    # TODO: Integrate with core router
    logger.info("Non-streaming request %s - router integration pending", request_id)

    return JSONResponse(
        {"error": {"message": "Router integration pending", "type": "not_implemented"}},
        status_code=501,
    )