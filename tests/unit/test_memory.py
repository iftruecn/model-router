"""
Unit tests for MemoryStore (persistent memory, v1.0.2).

Tests atomic persistence, ring-buffer request log, and cost accounting.
"""

import pytest

from model_router.core.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    """Fresh MemoryStore with a small ring buffer for testing."""
    return MemoryStore(
        data_dir=str(tmp_path / "data"),
        agent_id="test-agent",
        max_request_log=5,
    )


@pytest.mark.asyncio
async def test_save_load_roundtrip(store: MemoryStore):
    """Stats survive save -> new instance -> load."""
    store.update_model_stats("coding", "gpt-4o", {"n": 3, "mu": 0.7, "m2": 0.1, "ewma": 0.65})
    store.add_cost(0.002, 0.010)
    await store.save()

    fresh = MemoryStore(data_dir=store.data_dir, agent_id="test-agent")
    await fresh.load()

    stats = fresh.get_model_stats("coding", "gpt-4o")
    assert stats is not None
    assert stats["n"] == 3
    assert abs(stats["mu"] - 0.7) < 1e-6
    cost = fresh.get_cost_stats()
    assert cost["total_requests"] == 1
    assert cost["estimated_savings"] > 0


@pytest.mark.asyncio
async def test_request_log_ring_buffer(store: MemoryStore):
    """Ring buffer caps entries and drops oldest first."""
    for i in range(8):
        store.append_request_log({"request_id": f"req-{i}", "final_model": "m"})

    assert len(store._request_log) == 5
    # oldest (req-0..2) dropped, newest kept
    assert store._request_log[0]["request_id"] == "req-3"
    assert store._request_log[-1]["request_id"] == "req-7"


def test_get_request_lookup(store: MemoryStore):
    """Request lookup by id works and misses gracefully."""
    store.append_request_log({"request_id": "abc", "final_model": "gpt-4o"})
    assert store.get_request("abc") is not None
    assert store.get_request("abc")["final_model"] == "gpt-4o"
    assert store.get_request("missing") is None


def test_cost_stats_savings(store: MemoryStore):
    """Savings = baseline - actual, with percentage."""
    store.add_cost(0.001, 0.010)
    store.add_cost(0.001, 0.010)
    stats = store.get_cost_stats()
    assert stats["total_requests"] == 2
    assert abs(stats["estimated_savings"] - 0.018) < 1e-6
    assert stats["savings_percent"] == 90.0


def test_cost_stats_empty(store: MemoryStore):
    """No division by zero when nothing recorded."""
    stats = store.get_cost_stats()
    assert stats["total_requests"] == 0
    assert stats["savings_percent"] == 0.0


@pytest.mark.asyncio
async def test_request_log_persistence(store: MemoryStore):
    """Request log survives save/load with ring cap applied."""
    for i in range(8):
        store.append_request_log({"request_id": f"req-{i}"})
    await store.save()

    fresh = MemoryStore(
        data_dir=store.data_dir, agent_id="test-agent", max_request_log=5
    )
    await fresh.load()
    assert len(fresh._request_log) == 5
    assert fresh.get_request("req-7") is not None
