"""
Unit tests for Learner (Gaussian Thompson Sampling, v1.0.2).

Tests continuous reward, Welford updates, progressive handoff,
shadow mode, and feedback attribution.
"""

import random

import pytest

from model_router.core.learner import Learner
from model_router.core.memory import MemoryStore


@pytest.fixture
def make_learner(tmp_path):
    """Factory: Learner backed by a fresh MemoryStore."""
    def _make(active: bool = True, handoff_n: int = 5) -> Learner:
        store = MemoryStore(data_dir=str(tmp_path / "data"), agent_id="t")
        return Learner(
            store=store,
            enabled=True,
            active=active,
            handoff_n=handoff_n,
            rng=random.Random(42),
        )
    return _make


def test_reward_fallback_is_negative(make_learner):
    """Quality fallback = strong negative reward."""
    l = make_learner()
    r = l.compute_reward(quality_passed=False, latency_ms=100, cost=0.001, baseline_cost=0.01)
    assert r.total < 0
    assert r.quality == -1.0


def test_reward_passed_is_positive(make_learner):
    """Passed + fast + cheap = high reward in (0, 1]."""
    l = make_learner()
    r = l.compute_reward(quality_passed=True, latency_ms=100, cost=0.001, baseline_cost=0.01)
    assert r.total > 0.5
    assert r.speed > 0.9
    assert r.cost > 0.8


def test_reward_no_length_proxy(make_learner):
    """Reward must NOT depend on response length (verbosity bias guard)."""
    l = make_learner()
    short = l.compute_reward(True, 100, 0.001, 0.01)
    long = l.compute_reward(True, 100, 0.001, 0.01)
    assert short.total == long.total


@pytest.mark.asyncio
async def test_welford_convergence(make_learner):
    """Repeated identical rewards converge mu to that reward."""
    l = make_learner()
    for _ in range(30):
        await l.update("coding", "gpt-4o", 0.8)
    stats = l._store.get_model_stats("coding", "gpt-4o")
    assert stats["n"] == 30
    assert abs(stats["mu"] - 0.8) < 1e-6


def test_learned_score_none_without_data(make_learner):
    """Cold start: no data -> no learned score."""
    l = make_learner()
    assert l.learned_score("coding", "gpt-4o") is None


@pytest.mark.asyncio
async def test_learned_score_after_data(make_learner):
    """With data, learned_score returns a value near the mean."""
    l = make_learner()
    for _ in range(20):
        await l.update("coding", "gpt-4o", 0.8)
    score = l.learned_score("coding", "gpt-4o", total_attempts=20)
    assert score is not None
    assert abs(score - 0.8) < 0.3  # Thompson sample stays near mu


def test_blend_shadow_mode(make_learner):
    """active=False (shadow): decision stays static, mode='shadow'."""
    l = make_learner(active=False)
    blended, mode = l.blend_score(static_score=5.0, learned=9.0, n_samples=1000)
    assert blended == 5.0
    assert mode == "shadow"


def test_blend_static_below_handoff(make_learner):
    """Not enough samples -> static stays in control."""
    l = make_learner(handoff_n=200)
    blended, mode = l.blend_score(static_score=5.0, learned=9.0, n_samples=50)
    assert blended == 5.0
    assert mode == "shadow"


def test_blend_no_intervention_when_agreeing(make_learner):
    """Learned close to static (< dev threshold) -> no intervention."""
    l = make_learner(handoff_n=5)
    blended, mode = l.blend_score(static_score=5.0, learned=5.1, n_samples=100)
    assert blended == 5.0
    assert mode == "shadow"


def test_blend_progressive_handoff(make_learner):
    """Enough samples + big deviation -> learned gains partial weight."""
    l = make_learner(handoff_n=5)
    blended, mode = l.blend_score(static_score=5.0, learned=9.0, n_samples=10)
    assert mode == "learned"
    assert 5.0 < blended < 9.0  # progressive, not a hard switch


@pytest.mark.asyncio
async def test_feedback_attribution(make_learner):
    """Positive feedback lifts final model; negative penalizes failed ones."""
    l = make_learner()
    await l.apply_feedback("coding", "gpt-4o", ["weak-model"], positive=True)
    assert l._store.get_model_stats("coding", "gpt-4o")["mu"] > 0

    await l.apply_feedback("coding", "gpt-4o", ["weak-model"], positive=False)
    weak = l._store.get_model_stats("coding", "weak-model")
    assert weak is not None and weak["mu"] < 0


def test_disabled_learner_is_inert(make_learner):
    """enabled=False: no scores, no updates."""
    l = make_learner()
    l.enabled = False
    assert l.learned_score("coding", "gpt-4o") is None
    blended, mode = l.blend_score(5.0, 9.0, 1000)
    assert mode == "static"
