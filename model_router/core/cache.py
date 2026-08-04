"""
Semantic cache (FR-Qoder-v2-platform §FR-P1, LiteLLM-style).

Cache similar questions and return the historical answer directly,
saving provider calls for repetitive traffic.

v1 similarity: character-bigram Jaccard over normalized text —
zero dependency, millisecond-level (keeps the zero-latency promise).
Embedding-based similarity is a drop-in upgrade for v2 (same API).

Design constraints:
- In-memory LRU by default (OrderedDict); Redis backend is a future option
- TTL per entry, configurable
- Streaming requests are never cached (content shape differs)
- Short queries are never cached (too ambiguous to match safely)
- Misses and hits are counted for the offline evaluator
"""

import asyncio
import logging
import threading
import time
from collections import OrderedDict

from model_router.config.defaults import (
    CACHE_CAPACITY,
    CACHE_MIN_KEY_LEN,
    CACHE_SIM_THRESHOLD,
    CACHE_TTL_SECONDS,
)

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace for stable keys."""
    return " ".join(text.lower().split())


def _bigrams(text: str) -> set:
    """Character bigram set (works for CJK and latin alike)."""
    return {text[i:i + 2] for i in range(len(text) - 1)} if len(text) >= 2 else {text}


def similarity(a: str, b: str) -> float:
    """Jaccard similarity over character bigrams, in [0, 1]."""
    sa, sb = _bigrams(_normalize(a)), _bigrams(_normalize(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class SemanticCache:
    """LRU + TTL semantic cache keyed by normalized user text."""

    def __init__(
        self,
        ttl_seconds: int = CACHE_TTL_SECONDS,
        capacity: int = CACHE_CAPACITY,
        sim_threshold: float = CACHE_SIM_THRESHOLD,
        min_key_len: int = CACHE_MIN_KEY_LEN,
        enabled: bool = True,
    ):
        self.ttl_seconds = ttl_seconds
        self.capacity = capacity
        self.sim_threshold = sim_threshold
        self.min_key_len = min_key_len
        self.enabled = enabled
        self._entries: OrderedDict = OrderedDict()  # norm_key -> entry
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def build_key(self, messages: list) -> str:
        """Cache key = last user text + conversation depth (context matters)."""
        last_user = ""
        for msg in reversed(messages or []):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    last_user = content
                break
        return _normalize(f"{last_user}||{len(messages or [])}")

    def lookup(self, messages: list) -> dict | None:
        """
        Return the cached entry if a sufficiently similar question
        exists and is fresh; otherwise None. Never raises.
        
        P2-13: O(n) linear scan over _entries for Jaccard similarity.
        At capacity=1000 this is fast enough (<1ms per lookup on modern
        hardware). If capacity grows beyond ~10K, consider minhash/simhash
        pre-filtering. For now the bounded capacity keeps this acceptable.
        """
        if not self.enabled:
            return None
        key = self.build_key(messages)
        if len(key.split("||")[0]) < self.min_key_len:
            with self._lock:
                self.misses += 1
            return None
        now = time.time()
        best_key, best_entry, best_score = None, None, 0.0
        with self._lock:
            for norm_key, entry in self._entries.items():
                if now - entry["ts"] > self.ttl_seconds:
                    continue
                score = 1.0 if norm_key == key else similarity(
                    key.split("||")[0], norm_key.split("||")[0]
                )
                if score > best_score:
                    best_key, best_entry, best_score = norm_key, entry, score
            if best_entry is not None and best_score >= self.sim_threshold:
                self._entries.move_to_end(best_key)  # LRU touch
                with self._lock:
                    self.hits += 1
                return {
                    "response": best_entry["response"],
                    "similarity": round(best_score, 4),
                    "age_seconds": round(now - best_entry["ts"], 1),
                    "model": best_entry.get("model", ""),
                }
        self.misses += 1
        return None

    def store(self, messages: list, response: dict, model: str = "") -> bool:
        """Store a non-streaming answer for future similar questions."""
        if not self.enabled:
            return False
        key = self.build_key(messages)
        if len(key.split("||")[0]) < self.min_key_len:
            return False
        with self._lock:
            self._entries[key] = {
                "ts": time.time(),
                "response": response,
                "model": model,
            }
            self._entries.move_to_end(key)
            while len(self._entries) > self.capacity:
                self._entries.popitem(last=False)
        return True

    # ------------------------------------------------------------------
    # Async wrappers (avoid blocking event loop with threading.Lock)
    # ------------------------------------------------------------------

    async def async_lookup(self, messages: list) -> dict | None:
        """Async version of lookup() — runs in thread pool to avoid blocking."""
        return await asyncio.to_thread(self.lookup, messages)

    async def async_store(self, messages: list, response: dict, model: str = "") -> bool:
        """Async version of store() — runs in thread pool to avoid blocking."""
        return await asyncio.to_thread(self.store, messages, response, model)

    # ------------------------------------------------------------------
    # Admin helpers
    # ------------------------------------------------------------------

    def clear(self) -> int:
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            return n

    def get_stats(self) -> dict:
        total = self.hits + self.misses
        with self._lock:
            size = len(self._entries)
        return {
            "enabled": self.enabled,
            "entries": size,
            "capacity": self.capacity,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 4) if total else 0.0,
            "ttl_seconds": self.ttl_seconds,
            "similarity_threshold": self.sim_threshold,
            "backend": "memory_lru",
        }


# Global singleton
semantic_cache = SemanticCache()
