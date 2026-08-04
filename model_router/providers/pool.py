"""
Global HTTP connection pool for Model Router.

Manages httpx.AsyncClient instances with connection pooling,
grouped by base_url for efficient TCP connection reuse.

v1.2.0: Tiered timeouts (connect=10s, read=60s, write=10s, pool=10s).
"""

import logging
from typing import Optional
from urllib.parse import urlparse

import httpx

from model_router.config.defaults import (
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_WRITE_TIMEOUT,
    DEFAULT_POOL_TIMEOUT,
)

logger = logging.getLogger(__name__)


class ConnectionPool:
    """
    Global connection pool manager.

    Maintains a pool of httpx.AsyncClient instances, one per unique base_url.
    Uses FastAPI lifespan for initialization and cleanup.
    Uses tiered timeouts (v1.0.9): connect=10s, read=60s, write=10s, pool=10s.
    """

    def __init__(
        self,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        max_keepalive_connections: int = DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        write_timeout: float = DEFAULT_WRITE_TIMEOUT,
        pool_timeout: float = DEFAULT_POOL_TIMEOUT,
    ):
        self._max_connections = max_connections
        self._max_keepalive = max_keepalive_connections
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=write_timeout,
            pool=pool_timeout,
        )
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the connection pool. Called on app startup."""
        self._initialized = True
        logger.info(
            "Connection pool initialized (max_connections=%d, max_keepalive=%d, "
            "timeout: connect=%.0fs read=%.0fs write=%.0fs pool=%.0fs)",
            self._max_connections,
            self._max_keepalive,
            self._timeout.connect,
            self._timeout.read,
            self._timeout.write,
            self._timeout.pool,
        )

    async def close(self) -> None:
        """Close all connections. Called on app shutdown."""
        for base_url, client in self._clients.items():
            await client.aclose()
            logger.debug("Closed connection pool for %s", base_url)
        self._clients.clear()
        self._initialized = False
        logger.info("Connection pool closed")

    def _get_base_url_key(self, base_url: str) -> str:
        """Normalize base_url to use as dict key."""
        parsed = urlparse(base_url.rstrip("/"))
        return f"{parsed.scheme}://{parsed.netloc}"

    def get_client(self, base_url: str) -> httpx.AsyncClient:
        """
        Get or create an httpx.AsyncClient for the given base_url.

        Connections are pooled by normalized base_url (scheme + netloc),
        so different paths on the same host share the same connection pool.
        """
        if not self._initialized:
            raise RuntimeError("ConnectionPool not initialized. Call initialize() first.")

        key = self._get_base_url_key(base_url)

        if key not in self._clients:
            limits = httpx.Limits(
                max_connections=self._max_connections,
                max_keepalive_connections=self._max_keepalive,
            )
            self._clients[key] = httpx.AsyncClient(
                timeout=self._timeout,
                limits=limits,
            )
            logger.debug("Created connection pool for %s", key)

        return self._clients[key]

    def get_stats(self) -> dict:
        """Get connection pool statistics."""
        return {
            "pools": len(self._clients),
            "initialized": self._initialized,
            "config": {
                "max_connections": self._max_connections,
                "max_keepalive_connections": self._max_keepalive,
                "timeout": {
                    "connect": self._timeout.connect,
                    "read": self._timeout.read,
                    "write": self._timeout.write,
                    "pool": self._timeout.pool,
                },
            },
            "pools_detail": {
                key: {"is_closed": client.is_closed}
                for key, client in self._clients.items()
            },
        }


# Global singleton instance
pool = ConnectionPool()
