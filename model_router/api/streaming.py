"""
SSE streaming support for Model Router.

Handles streaming responses from upstream model providers,
forwarding chunks to the client via Server-Sent Events.
"""

import json
import logging
from typing import AsyncGenerator

import httpx

from model_router.providers.pool import pool

logger = logging.getLogger(__name__)


async def stream_model_response(
    model_key: str,
    model_info: dict,
    request_data: dict,
    timeout: float = 120.0,
) -> AsyncGenerator[str, None]:
    """
    Stream response from a model API via SSE.

    Yields SSE-formatted strings compatible with OpenAI streaming API.

    Args:
        model_key: Model identifier key
        model_info: Model configuration dict (base_url, api_key, model name)
        request_data: Original request data from client
        timeout: Request timeout in seconds

    Yields:
        SSE-formatted strings: "data: {json}\n\n"
    """
    headers = {
        "Authorization": f"Bearer {model_info['api_key']}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    # P0-3: whitelist known-safe OpenAI params to prevent arbitrary
    # request body fields from being forwarded to the provider
    _FORWARD_FIELDS = {
        "top_p", "frequency_penalty", "presence_penalty", "stop",
        "n", "response_format", "seed", "tools", "tool_choice",
        "logprobs", "top_logprobs", "logit_bias", "user",
        "reasoning_effort",
    }
    body = {
        "model": model_info["model"],
        "messages": request_data.get("messages", []),
        "temperature": request_data.get("temperature", 0.7),
        "max_tokens": request_data.get("max_tokens", 4096),
        "stream": True,
    }
    # Only forward whitelisted fields
    for field in _FORWARD_FIELDS:
        if field in request_data:
            body[field] = request_data[field]

    url = f"{model_info['base_url'].rstrip('/')}/chat/completions"
    logger.debug("Streaming from %s -> %s", model_key, url)

    client = pool.get_client(model_info["base_url"])

    try:
        async with client.stream(
            "POST",
            url,
            json=body,
            headers=headers,
        ) as response:
            if response.status_code != 200:
                error_body = await response.aread()
                error_msg = error_body.decode("utf-8", errors="replace")[:500]
                logger.warning(
                    "%s streaming returned %d: %s",
                    model_key,
                    response.status_code,
                    error_msg,
                )
                error_data = {
                    "error": {
                        "message": f"Upstream error: HTTP {response.status_code}",
                        "type": "upstream_error",
                        "model": model_key,
                    }
                }
                yield f"data: {json.dumps(error_data)}\n\n"
                yield "data: [DONE]\n\n"
                return

            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    yield f"{line}\n\n"
                    if line.strip() == "data: [DONE]":
                        break

    except httpx.TimeoutException:
        logger.warning("%s streaming timed out after %.0fs", model_key, timeout)
        error_data = {
            "error": {
                "message": f"Streaming timeout after {timeout}s",
                "type": "timeout",
                "model": model_key,
            }
        }
        yield f"data: {json.dumps(error_data)}\n\n"
        yield "data: [DONE]\n\n"

    except httpx.HTTPError as e:
        logger.warning("%s streaming HTTP error: %s", model_key, str(e))
        error_data = {
            "error": {
                "message": f"Streaming error: {str(e)}",
                "type": "http_error",
                "model": model_key,
            }
        }
        yield f"data: {json.dumps(error_data)}\n\n"
        yield "data: [DONE]\n\n"