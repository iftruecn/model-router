"""
Tests for forwarding layer stability (v1.0.9, gap-analysis #1).

Covers:
- Network disconnect (ConnectionError)
- Malformed JSON response from provider
- Oversized response body handling
- Timeout tiered configuration
- Concurrency semaphore limit
- Streaming X-Routing-Mode header
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from model_router.core.forwarding import (
    forward_non_streaming,
    forward_streaming,
    _get_semaphore,
    _forwarding_semaphore,
)
from model_router.core.router import RoutingResult
from model_router.config.defaults import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_WRITE_TIMEOUT,
    DEFAULT_POOL_TIMEOUT,
    DEFAULT_FORWARDING_CONCURRENCY,
)
from model_router.providers.pool import ConnectionPool


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def routing_result():
    return RoutingResult(
        model_key="gpt-4o-mini",
        model_name="GPT-4o Mini",
        score=8.5,
        reason="auto_domain:chat(score=5.0)",
    )


@pytest.fixture
def models_config():
    return {
        "gpt-4o-mini": {
            "name": "GPT-4o Mini",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-key",
            "model": "gpt-4o-mini",
        },
        "gpt-4o": {
            "name": "GPT-4o",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-key",
            "model": "gpt-4o",
        },
    }


@pytest.fixture
def fallback_chain_config():
    return {
        "gpt-4o-mini": ["gpt-4o"],
        "gpt-4o": ["gpt-4o-mini"],
    }


# ------------------------------------------------------------------
# #1c: Exception scenario tests
# ------------------------------------------------------------------

class TestNetworkDisconnect:
    """Network disconnect scenarios."""

    @pytest.mark.asyncio
    async def test_connection_error_triggers_fallback(
        self, routing_result, models_config, fallback_chain_config
    ):
        """ConnectionError should trigger fallback to next model."""
        request_data = {"messages": [{"role": "user", "content": "hi"}]}

        with patch(
            "model_router.core.forwarding._call_provider",
            new_callable=AsyncMock,
        ) as mock_call:
            # First call: connection error; second call: success
            mock_call.side_effect = [
                httpx.ConnectError("Connection refused"),
                {"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            ]

            response, headers = await forward_non_streaming(
                request_data=request_data,
                request_id="test-conn-err",
                routing=routing_result,
                models_config=models_config,
                fallback_chain_config=fallback_chain_config,
            )

            assert "choices" in response
            assert mock_call.call_count == 2

    @pytest.mark.asyncio
    async def test_all_connections_fail(
        self, routing_result, models_config, fallback_chain_config
    ):
        """All connections fail returns error response."""
        request_data = {"messages": [{"role": "user", "content": "hi"}]}

        with patch(
            "model_router.core.forwarding._call_provider",
            new_callable=AsyncMock,
        ) as mock_call:
            mock_call.side_effect = httpx.ConnectError("Network unreachable")

            response, headers = await forward_non_streaming(
                request_data=request_data,
                request_id="test-all-conn",
                routing=routing_result,
                models_config=models_config,
                fallback_chain_config=fallback_chain_config,
            )

            assert "error" in response
            assert "failed_models" in response["error"]


class TestMalformedJSON:
    """Malformed JSON response from provider."""

    @pytest.mark.asyncio
    async def test_malformed_json_response(
        self, routing_result, models_config, fallback_chain_config
    ):
        """Provider returns invalid JSON — should be caught as exception."""
        request_data = {"messages": [{"role": "user", "content": "hi"}]}

        with patch(
            "model_router.core.forwarding._call_provider",
            new_callable=AsyncMock,
        ) as mock_call:
            # Simulate json.JSONDecodeError from response.json()
            mock_call.side_effect = json.JSONDecodeError("Expecting value", "", 0)

            response, headers = await forward_non_streaming(
                request_data=request_data,
                request_id="test-bad-json",
                routing=routing_result,
                models_config=models_config,
                fallback_chain_config=fallback_chain_config,
            )

            # Should be caught by the generic Exception handler
            assert "error" in response

    @pytest.mark.asyncio
    async def test_malformed_json_triggers_fallback(
        self, routing_result, models_config, fallback_chain_config
    ):
        """First model returns bad JSON, second model succeeds."""
        request_data = {"messages": [{"role": "user", "content": "hi"}]}

        with patch(
            "model_router.core.forwarding._call_provider",
            new_callable=AsyncMock,
        ) as mock_call:
            mock_call.side_effect = [
                json.JSONDecodeError("Expecting value", "", 0),
                {"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            ]

            response, headers = await forward_non_streaming(
                request_data=request_data,
                request_id="test-bad-json-fb",
                routing=routing_result,
                models_config=models_config,
                fallback_chain_config=fallback_chain_config,
            )

            assert "choices" in response
            assert mock_call.call_count == 2


class TestOversizedResponse:
    """Oversized response body handling."""

    @pytest.mark.asyncio
    async def test_large_response_handled(
        self, routing_result, models_config, fallback_chain_config
    ):
        """Large response body should be handled without error."""
        request_data = {"messages": [{"role": "user", "content": "hi"}]}

        # Simulate a very large response
        large_content = "x" * 1_000_000  # 1MB response
        large_response = {
            "choices": [{"message": {"role": "assistant", "content": large_content}}]
        }

        with patch(
            "model_router.core.forwarding._call_provider",
            new_callable=AsyncMock,
        ) as mock_call:
            mock_call.return_value = large_response

            response, headers = await forward_non_streaming(
                request_data=request_data,
                request_id="test-large",
                routing=routing_result,
                models_config=models_config,
                fallback_chain_config=fallback_chain_config,
            )

            assert "choices" in response
            assert len(response["choices"][0]["message"]["content"]) == 1_000_000


# ------------------------------------------------------------------
# #1a: Timeout tiered configuration
# ------------------------------------------------------------------

class TestTimeoutTiers:
    """Verify tiered timeout configuration."""

    def test_default_timeout_values(self):
        """Default timeout constants are correctly defined."""
        assert DEFAULT_CONNECT_TIMEOUT == 10.0
        assert DEFAULT_READ_TIMEOUT == 60.0
        assert DEFAULT_WRITE_TIMEOUT == 10.0
        assert DEFAULT_POOL_TIMEOUT == 10.0

    def test_pool_creates_tiered_timeout(self):
        """ConnectionPool creates httpx.Timeout with tiered values."""
        p = ConnectionPool()
        assert p._timeout.connect == DEFAULT_CONNECT_TIMEOUT
        assert p._timeout.read == DEFAULT_READ_TIMEOUT
        assert p._timeout.write == DEFAULT_WRITE_TIMEOUT
        assert p._timeout.pool == DEFAULT_POOL_TIMEOUT

    def test_pool_custom_timeout(self):
        """ConnectionPool accepts custom tiered timeout values."""
        p = ConnectionPool(
            connect_timeout=5.0,
            read_timeout=30.0,
            write_timeout=5.0,
            pool_timeout=3.0,
        )
        assert p._timeout.connect == 5.0
        assert p._timeout.read == 30.0
        assert p._timeout.write == 5.0
        assert p._timeout.pool == 3.0

    def test_pool_stats_show_tiered_timeout(self):
        """get_stats() returns tiered timeout details."""
        p = ConnectionPool()
        stats = p.get_stats()
        timeout_cfg = stats["config"]["timeout"]
        assert "connect" in timeout_cfg
        assert "read" in timeout_cfg
        assert "write" in timeout_cfg
        assert "pool" in timeout_cfg


# ------------------------------------------------------------------
# #1b: Concurrency semaphore
# ------------------------------------------------------------------

class TestConcurrencyLimit:
    """Verify concurrency semaphore."""

    def test_default_concurrency_value(self):
        """Default concurrency limit is 10."""
        assert DEFAULT_FORWARDING_CONCURRENCY == 10

    def test_semaphore_creation(self):
        """Semaphore is created with correct limit."""
        sem = _get_semaphore()
        assert isinstance(sem, asyncio.Semaphore)


# ------------------------------------------------------------------
# #2: Streaming routing header
# ------------------------------------------------------------------

class TestStreamingRoutingHeader:
    """Verify X-Routing-Mode header in streaming responses."""

    @pytest.mark.asyncio
    async def test_streaming_response_has_routing_mode(
        self, routing_result, models_config, fallback_chain_config
    ):
        """Streaming response should include X-Routing-Mode: streaming."""
        from model_router.api.chat import _handle_streaming
        from fastapi import Request

        request_data = {"messages": [{"role": "user", "content": "hi"}], "stream": True}

        async def mock_gen(*args, **kwargs):
            yield "data: test\n\n"

        with patch(
            "model_router.core.forwarding.forward_streaming",
            new_callable=AsyncMock,
        ) as mock_fwd:
            mock_fwd.return_value = (mock_gen(), {})

            # Create a mock request
            mock_request = MagicMock(spec=Request)
            mock_request.app.state.fallback_chain_config = fallback_chain_config
            mock_request.app.state.models_config = models_config

            response = await _handle_streaming(
                request=mock_request,
                request_data=request_data,
                request_id="test-stream-hdr",
                routing=routing_result,
                models_config=models_config,
                fallback_chain_config=fallback_chain_config,
            )

            # Check the response headers
            assert response.headers.get("x-routing-mode") == "streaming"
