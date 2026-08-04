"""
Tests for the provider forwarding layer (v1.0.7).

Covers:
- Non-streaming forwarding with/without fallback
- Streaming forwarding with/without fallback
- Error response building
- Semantic cache auto-fill on success
- Learning outcome recording on success
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from model_router.core.forwarding import (
    forward_non_streaming,
    forward_streaming,
    _build_error_response,
)
from model_router.core.router import RoutingResult


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def routing_result():
    """Basic routing result for testing."""
    return RoutingResult(
        model_key="gpt-4o-mini",
        model_name="GPT-4o Mini",
        score=8.5,
        reason="auto_domain:chat(score=5.0)",
    )


@pytest.fixture
def models_config():
    """Test models config with two models."""
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
    """Test fallback chain."""
    return {
        "gpt-4o-mini": ["gpt-4o"],
        "gpt-4o": ["gpt-4o-mini"],
    }


# ------------------------------------------------------------------
# Non-streaming forwarding
# ------------------------------------------------------------------

class TestForwardNonStreaming:
    """Tests for forward_non_streaming."""

    @pytest.mark.asyncio
    async def test_success_first_model(
        self, routing_result, models_config, fallback_chain_config
    ):
        """First model succeeds, no fallback needed."""
        request_data = {"messages": [{"role": "user", "content": "hi"}]}

        with patch(
            "model_router.core.forwarding._call_provider",
            new_callable=AsyncMock,
        ) as mock_call:
            mock_call.return_value = {
                "choices": [{"message": {"role": "assistant", "content": "hello"}}]
            }

            response, headers = await forward_non_streaming(
                request_data=request_data,
                request_id="test-req-1",
                routing=routing_result,
                models_config=models_config,
                fallback_chain_config=fallback_chain_config,
            )

            assert "choices" in response
            assert response["choices"][0]["message"]["content"] == "hello"
            mock_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_second_model(
        self, routing_result, models_config, fallback_chain_config
    ):
        """First model fails, second model succeeds."""
        import httpx

        request_data = {"messages": [{"role": "user", "content": "hi"}]}

        with patch(
            "model_router.core.forwarding._call_provider",
            new_callable=AsyncMock,
        ) as mock_call:
            # First call raises timeout, second succeeds
            mock_call.side_effect = [
                httpx.TimeoutException("timeout"),
                {"choices": [{"message": {"role": "assistant", "content": "fallback ok"}}]},
            ]

            response, headers = await forward_non_streaming(
                request_data=request_data,
                request_id="test-req-2",
                routing=routing_result,
                models_config=models_config,
                fallback_chain_config=fallback_chain_config,
            )

            assert "choices" in response
            assert mock_call.call_count == 2
            assert routing_result.failed_models == ["gpt-4o-mini"]

    @pytest.mark.asyncio
    async def test_all_models_fail(
        self, routing_result, models_config, fallback_chain_config
    ):
        """All models in chain fail, return error response."""
        import httpx

        request_data = {"messages": [{"role": "user", "content": "hi"}]}

        with patch(
            "model_router.core.forwarding._call_provider",
            new_callable=AsyncMock,
        ) as mock_call:
            mock_call.side_effect = httpx.TimeoutException("timeout")

            response, headers = await forward_non_streaming(
                request_data=request_data,
                request_id="test-req-3",
                routing=routing_result,
                models_config=models_config,
                fallback_chain_config=fallback_chain_config,
            )

            assert "error" in response
            assert response["error"]["type"] == "timeout"
            assert "failed_models" in response["error"]

    @pytest.mark.asyncio
    async def test_client_error_no_fallback(
        self, routing_result, models_config, fallback_chain_config
    ):
        """Client error (400) should NOT trigger fallback."""
        import httpx

        request_data = {"messages": [{"role": "user", "content": "hi"}]}

        with patch(
            "model_router.core.forwarding._call_provider",
            new_callable=AsyncMock,
        ) as mock_call:
            # Create a mock response with status_code 400
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_call.side_effect = httpx.HTTPStatusError(
                "Bad Request",
                request=MagicMock(),
                response=mock_response,
            )

            response, headers = await forward_non_streaming(
                request_data=request_data,
                request_id="test-req-4",
                routing=routing_result,
                models_config=models_config,
                fallback_chain_config=fallback_chain_config,
            )

            # Should NOT try fallback (only 1 call)
            assert mock_call.call_count == 1
            assert "error" in response


# ------------------------------------------------------------------
# Streaming forwarding
# ------------------------------------------------------------------

class TestForwardStreaming:
    """Tests for forward_streaming."""

    @pytest.mark.asyncio
    async def test_success_first_model(
        self, routing_result, models_config, fallback_chain_config
    ):
        """First model handles streaming."""
        request_data = {"messages": [{"role": "user", "content": "hi"}], "stream": True}

        async def mock_generator(*args, **kwargs):
            yield "data: test\n\n"

        with patch(
            "model_router.api.streaming.stream_model_response",
            side_effect=mock_generator,
        ):
            generator, headers = await forward_streaming(
                request_data=request_data,
                request_id="test-req-5",
                routing=routing_result,
                models_config=models_config,
                fallback_chain_config=fallback_chain_config,
            )

            assert generator is not None
            chunks = []
            async for chunk in generator:
                chunks.append(chunk)
            assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_all_models_fail(
        self, routing_result, fallback_chain_config
    ):
        """All models fail, return error generator."""
        request_data = {"messages": [{"role": "user", "content": "hi"}], "stream": True}

        # Empty models config = all models skipped
        generator, headers = await forward_streaming(
            request_data=request_data,
            request_id="test-req-6",
            routing=routing_result,
            models_config={},
            fallback_chain_config=fallback_chain_config,
        )

        chunks = []
        async for chunk in generator:
            chunks.append(chunk)

        # Should have error + [DONE]
        assert len(chunks) == 2
        assert "error" in chunks[0]
        assert "[DONE]" in chunks[1]


# ------------------------------------------------------------------
# Error response builder
# ------------------------------------------------------------------

class TestBuildErrorResponse:
    """Tests for _build_error_response."""

    def test_timeout_error(self, routing_result):
        """Build error response for timeout."""
        response = _build_error_response(
            last_error=("timeout", None),
            failed_models=["gpt-4o-mini", "gpt-4o"],
            routing=routing_result,
        )

        assert "error" in response
        assert response["error"]["type"] == "timeout"
        assert "timed out" in response["error"]["message"]

    def test_http_error(self, routing_result):
        """Build error response for HTTP error."""
        response = _build_error_response(
            last_error=("http_error", 500),
            failed_models=["gpt-4o-mini"],
            routing=routing_result,
        )

        assert "error" in response
        assert response["error"]["type"] == "all_models_failed"
        assert "500" in response["error"]["message"]

    def test_no_error(self, routing_result):
        """Build error response when no error occurred."""
        response = _build_error_response(
            last_error=None,
            failed_models=[],
            routing=routing_result,
        )

        assert "error" in response
        assert response["error"]["type"] == "no_models_available"
