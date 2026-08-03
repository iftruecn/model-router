"""
Global HTTP connection pool for Model Router.

Manages httpx.AsyncClient instances with connection pooling,
grouped by base_url for efficient TCP connection reuse.
"""

import logging
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class ConnectionPool:
    """
    Global connection pool manager.

    Maintains a pool of httpx.AsyncClient instances, one per unique base_url.
    Uses FastAPI lifespan for initialization and cleanup.
    """

    def __init__(
        self,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        timeout: float = 120.0,
    ):
        self._max_connections = max_connections
        self._max_keepalive = max_keepalive_connections
        self._timeout = timeout
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the connection pool. Called on app startup."""
        self._initialized = True
        logger.info(
            "Connection pool initialized (max_connections=%d, max_keepalive=%d)",
            self._max_connections,
            self._max_keepalive,
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
                timeout=httpx.Timeout(self._timeout),
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
                "timeout": self._timeout,
            },
            "pools_detail": {
                key: {"is_closed": client.is_closed}
                for key, client in self._clients.items()
            },
        }


# Global singleton instance
pool = ConnectionPool()