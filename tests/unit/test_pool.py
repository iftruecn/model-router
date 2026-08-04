"""
Unit tests for ConnectionPool.

Tests connection pool initialization, client reuse, and cleanup.
"""

import pytest
from model_router.providers.pool import ConnectionPool


@pytest.fixture
def pool():
    """Create a fresh ConnectionPool for each test."""
    return ConnectionPool(
        max_connections=10,
        max_keepalive_connections=5,
        connect_timeout=5.0,
        read_timeout=30.0,
        write_timeout=5.0,
        pool_timeout=5.0,
    )


@pytest.mark.asyncio
async def test_pool_initialization(pool: ConnectionPool):
    """Test that pool initializes correctly."""
    assert not pool._initialized
    await pool.initialize()
    assert pool._initialized


@pytest.mark.asyncio
async def test_pool_close(pool: ConnectionPool):
    """Test that pool closes all connections."""
    await pool.initialize()
    client = pool.get_client("https://api.openai.com/v1")
    assert not client.is_closed
    await pool.close()
    assert client.is_closed
    assert not pool._initialized


@pytest.mark.asyncio
async def test_client_reuse_by_base_url(pool: ConnectionPool):
    """Test that same base_url returns same client instance."""
    await pool.initialize()
    client1 = pool.get_client("https://api.openai.com/v1")
    client2 = pool.get_client("https://api.openai.com/v1/chat/completions")
    assert client1 is client2


@pytest.mark.asyncio
async def test_different_base_urls_create_different_clients(pool: ConnectionPool):
    """Test that different base_urls create different client instances."""
    await pool.initialize()
    client1 = pool.get_client("https://api.openai.com/v1")
    client2 = pool.get_client("https://api.anthropic.com/v1")
    assert client1 is not client2


@pytest.mark.asyncio
async def test_get_stats(pool: ConnectionPool):
    """Test that get_stats returns correct information."""
    await pool.initialize()
    pool.get_client("https://api.openai.com/v1")
    pool.get_client("https://api.anthropic.com/v1")
    stats = pool.get_stats()
    assert stats["initialized"] is True
    assert stats["pools"] == 2
    assert stats["config"]["max_connections"] == 10


@pytest.mark.asyncio
async def test_get_client_before_initialize_raises(pool: ConnectionPool):
    """Test that get_client raises if pool not initialized."""
    with pytest.raises(RuntimeError, match="not initialized"):
        pool.get_client("https://api.openai.com/v1")