"""
Tests for v1.0.3 hardening batch (FR-v1.0.3-consolidated):
- P0#1 routing diversity guard (anti-collapse)
- P0#2 transparency headers (patterns / fallback / learned)
- P2#6 semantic fallback trigger policy
"""

import random

import pytest

from model_router.core.fallback import should_fallback_on_error
from model_router.core.learner import DiversityGuard
from model_router.core.router import RoutingResult


# ------------------------------------------------------------------
# P2#6: semantic fallback trigger
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "status,timeout,fallback,category",
    [
        (500, False, True, "infra"),
        (502, False, True, "infra"),
        (503, False, True, "infra"),
        (None, True, True, "timeout"),
        (429, False, True, "rate_limit"),
        (400, False, False, "client"),
        (401, False, False, "client"),
        (403, False, False, "client"),
        (404, False, False, "client"),  # bad model id: switching won't help
        (None, False, True, "unknown"),
    ],
)
def test_fallback_trigger_policy(status, timeout, fallback, category):
    got_fallback, got_category = should_fallback_on_error(status, is_timeout=timeout)
    assert got_fallback is fallback
    assert got_category == category


# ------------------------------------------------------------------
# P0#1: diversity guard
# ------------------------------------------------------------------

def test_guard_no_alert_on_sparse_history():
    g = DiversityGuard(window=100)
    for _ in range(5):
        g.record("coding", "m1")
    force, share = g.should_force_exploration("coding")
    assert force is False  # window too small to judge


def test_guard_detects_collapse():
    g = DiversityGuard(window=100, dominance_threshold=0.9)
    for _ in range(95):
        g.record("coding", "m1")
    for _ in range(5):
        g.record("coding", "m2")
    force, share = g.should_force_exploration("coding")
    assert force is True
    assert share == pytest.approx(0.95)


def test_guard_healthy_mix_no_force():
    g = DiversityGuard(window=100, dominance_threshold=0.9)
    for i in range(100):
        g.record("coding", f"m{i % 3}")
    force, _ = g.should_force_exploration("coding")
    assert force is False


def test_guard_forced_exploration_rate():
    """With collapse + rng always under rate, exploration always triggers."""

    class AlwaysLow(random.Random):
        def random(self):
            return 0.01

    g = DiversityGuard(window=20, explore_rate=0.05, rng=AlwaysLow())
    for _ in range(20):
        g.record("t", "m1")
    assert g.maybe_explore("t") is True
    assert g.get_stats()["forced_explorations"] == 1

    class AlwaysHigh(random.Random):
        def random(self):
            return 0.99

    g2 = DiversityGuard(window=20, explore_rate=0.05, rng=AlwaysHigh())
    for _ in range(20):
        g2.record("t", "m1")
    assert g2.maybe_explore("t") is False


def test_guard_stats_shape():
    g = DiversityGuard(window=10)
    for _ in range(8):
        g.record("chat", "a")
    g.record("chat", "b")
    g.record("chat", "b")
    stats = g.get_stats()
    task = stats["tasks"]["chat"]
    assert task["unique_models"] == 2
    assert task["dominant"] == "a"
    assert task["dominant_share"] == 0.8


# ------------------------------------------------------------------
# P0#2: transparency headers
# ------------------------------------------------------------------

def test_headers_baseline():
    r = RoutingResult(model_key="m", model_name="M", score=1.0, reason="x")
    h = r.to_headers()
    assert h["X-Routed-To"] == "m"
    assert "X-Routing-Fallback" not in h
    assert "X-Routing-Learned" not in h


def test_headers_fallback_chain():
    r = RoutingResult(model_key="m", model_name="M", score=1.0, reason="x")
    r.record_fallback(["m1", "m2"], final_model="m3")
    h = r.to_headers()
    assert h["X-Routing-Fallback"] == "true"
    assert h["X-Routing-Failed-Models"] == "m1,m2"
    assert h["X-Routed-To"] == "m3"


def test_headers_learned_contribution():
    r = RoutingResult(
        model_key="m", model_name="M", score=1.0, reason="x",
        learned_contribution=1.23,
    )
    assert r.to_headers()["X-Routing-Learned"] == "+1.23"
