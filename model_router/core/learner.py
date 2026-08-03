"""
Self-learning engine for Model Router v1.0.2.

Implements the learning loop approved in FR-持久记忆与自学习 with the
math refinements from Hermes' deep review (REVIEW-math-deep-dive.md):

- Gaussian Thompson Sampling (replaces Beta TS): models CONTINUOUS reward,
  O(1) conjugate-style updates via Welford's online mean/variance algorithm.
- Continuous reward function: quality-check pass + latency + cost.
  Deliberately EXCLUDES response length as a quality proxy (verbosity bias).
- UCB exploration bonus: bounded exploration, auto-vanishing with samples.
- Shadow mode: learning.active=False records data without affecting routing.
- Progressive handoff: learned score only gains weight after enough samples
  AND significant deviation from the static classifier score.
- Adaptive EWMA: slow decay (models change rarely), faster on big shifts.

All state persists through core.memory.MemoryStore.
"""

import logging
import math
import random
from collections import deque
from dataclasses import dataclass
from typing import Optional

from model_router.config.defaults import (
    DIVERSITY_DOMINANCE_THRESHOLD,
    DIVERSITY_EXPLORE_RATE,
    DIVERSITY_WINDOW,
    LEARNER_BASE_REWARD,
    LEARNER_DEV_THRESHOLD,
    LEARNER_EWMA_ALPHA_BASE,
    LEARNER_EWMA_ALPHA_MAX,
    LEARNER_FALLBACK_PENALTY,
    LEARNER_FEEDBACK_NEGATIVE,
    LEARNER_FEEDBACK_POSITIVE,
    LEARNER_HANDOFF_N,
    LEARNER_LATENCY_FULL_MS,
    LEARNER_UCB_C,
    LEARNER_VAR_FLOOR,
)
from model_router.core.memory import MemoryStore, memory_store

logger = logging.getLogger(__name__)


@dataclass
class RewardComponents:
    """Breakdown of a continuous reward signal (all in [-1, 1])."""
    quality: float = 0.0     # quality check passed (1.0) or failed (-1.0)
    speed: float = 0.0       # 1.0 = instant, 0.0 = >= LATENCY_FULL_MS
    cost: float = 0.0        # 1.0 = free, 0.0 = >= baseline cost
    source: str = "auto"     # auto | feedback_positive | feedback_negative

    @property
    def total(self) -> float:
        return self.quality * 0.5 + self.speed * 0.2 + self.cost * 0.3


class Learner:
    """
    Gaussian Thompson Sampling learner with continuous rewards.

    Per (task, model) we maintain:
        n      sample count
        mu     running mean reward          (Welford)
        m2     running sum of squared devs  (Welford)
        ewma   exponentially weighted moving average of reward

    Routing score = mu + ucb_bonus, sampled via gauss(mu, sigma) at decision
    time to balance exploration/exploitation (Thompson Sampling).
    """

    def __init__(
        self,
        store: Optional[MemoryStore] = None,
        enabled: bool = True,
        active: bool = False,  # shadow mode by default: learn, don't intervene
        handoff_n: int = LEARNER_HANDOFF_N,
        ucb_c: float = LEARNER_UCB_C,
        rng: Optional[random.Random] = None,
    ):
        self._store = store or memory_store
        self.enabled = enabled
        self.active = active
        self._handoff_n = handoff_n
        self._ucb_c = ucb_c
        self._rng = rng or random.Random()

    # ------------------------------------------------------------------
    # Decision-time scoring
    # ------------------------------------------------------------------

    def learned_score(
        self,
        task: str,
        model: str,
        total_attempts: int = 0,
        explore: bool = True,
    ) -> Optional[float]:
        """
        Return the learned score for (task, model), or None if no data.

        Score = Thompson sample of the reward posterior + UCB exploration
        bonus. `explore=False` disables the UCB term (used for manual or
        expensive models that must never be experimented with).
        """
        if not self.enabled:
            return None
        stats = self._store.get_model_stats(task, model)
        if stats is None or stats.get("n", 0) == 0:
            return None

        n = stats["n"]
        mu = stats.get("mu", 0.0)
        variance = max(LEARNER_VAR_FLOOR, stats.get("m2", 0.0) / max(1, n - 1))

        # Thompson Sampling: sample from the reward posterior
        sample = self._rng.gauss(mu, math.sqrt(variance / n))

        bonus = 0.0
        if explore and total_attempts > 0:
            # UCB bonus: shrinks naturally as this model is tried more
            bonus = self._ucb_c * math.sqrt(
                math.log(max(2, total_attempts)) / (n + 1)
            )

        return sample + bonus

    def blend_score(
        self,
        static_score: float,
        learned: Optional[float],
        n_samples: int,
    ) -> tuple[float, str]:
        """
        Blend static classifier score with learned score (progressive handoff).

        Returns (blended_score, mode) where mode is one of:
            "static"   no learning data or learning inactive
            "shadow"   data recorded but decision stays static
            "learned"  learned score partially/fully in control

        Handoff rule (Hermes review): require n > handoff_n AND significant
        deviation from the static score; then hand over progressively.
        """
        if learned is None or not self.enabled:
            return static_score, "static"

        if not self.active:
            return static_score, "shadow"

        if n_samples <= self._handoff_n:
            return static_score, "shadow"

        deviation = abs(learned - static_score)
        if deviation < LEARNER_DEV_THRESHOLD:
            # Learning agrees with static rules — no reason to intervene
            return static_score, "shadow"

        # Progressive handoff: weight grows smoothly after threshold
        w_learned = min(1.0, (n_samples - self._handoff_n) / (self._handoff_n + 50))
        blended = w_learned * learned + (1.0 - w_learned) * static_score
        return blended, "learned"

    def sample_count(self, task: str, model: str) -> int:
        stats = self._store.get_model_stats(task, model)
        return stats.get("n", 0) if stats else 0

    # ------------------------------------------------------------------
    # Reward computation
    # ------------------------------------------------------------------

    def compute_reward(
        self,
        quality_passed: bool,
        latency_ms: float,
        cost: float,
        baseline_cost: float,
    ) -> RewardComponents:
        """
        Continuous reward in [-1, 1]. Fully automatic, no human labels.

        NOTE: response length is intentionally NOT a quality proxy —
        it would systematically favor verbose models (Hermes review fix).
        """
        if not quality_passed:
            # Fallback triggered = strong negative signal
            return RewardComponents(
                quality=LEARNER_FALLBACK_PENALTY, speed=0.0, cost=0.0
            )

        speed_score = max(0.0, 1.0 - latency_ms / LEARNER_LATENCY_FULL_MS)
        if baseline_cost > 0:
            cost_score = max(0.0, 1.0 - cost / baseline_cost)
        else:
            cost_score = LEARNER_BASE_REWARD  # unknown pricing: neutral-high
        return RewardComponents(quality=1.0, speed=speed_score, cost=cost_score)

    # ------------------------------------------------------------------
    # Learning updates (O(1), Welford)
    # ------------------------------------------------------------------

    async def update(
        self,
        task: str,
        model: str,
        reward: float,
    ) -> None:
        """Fold one reward observation into the posterior (Welford)."""
        if not self.enabled:
            return

        stats = self._store.get_model_stats(task, model) or {
            "n": 0, "mu": 0.0, "m2": 0.0, "ewma": 0.0,
        }
        n = stats["n"] + 1
        old_mu = stats.get("mu", 0.0)
        delta = reward - old_mu
        new_mu = old_mu + delta / n
        m2 = stats.get("m2", 0.0) + delta * (reward - new_mu)

        # Adaptive EWMA: small alpha normally, larger on abrupt shifts
        old_ewma = stats.get("ewma", new_mu)
        shift = abs(reward - old_ewma) / max(0.01, abs(old_ewma) + 0.5)
        alpha = min(
            LEARNER_EWMA_ALPHA_MAX,
            LEARNER_EWMA_ALPHA_BASE + 0.15 * shift,
        )
        ewma = (1.0 - alpha) * old_ewma + alpha * reward

        self._store.update_model_stats(task, model, {
            "n": n,
            "mu": round(new_mu, 6),
            "m2": round(m2, 6),
            "ewma": round(ewma, 6),
        })
        await self._store.maybe_save()

    async def record_outcome(
        self,
        task: str,
        model: str,
        quality_passed: bool,
        latency_ms: float,
        cost: float,
        baseline_cost: float,
    ) -> RewardComponents:
        """Compute reward from an observed outcome and learn from it."""
        components = self.compute_reward(quality_passed, latency_ms, cost, baseline_cost)
        await self.update(task, model, components.total)
        return components

    async def apply_feedback(
        self,
        task: str,
        final_model: str,
        failed_models: list[str],
        positive: bool,
    ) -> None:
        """
        Explicit user feedback (stronger than automatic signals).

        Attribution rule (Hermes review): credit/blame goes to the model
        that produced the final answer; models abandoned by fallback get a
        mild penalty.
        """
        if positive:
            await self.update(task, final_model, LEARNER_FEEDBACK_POSITIVE)
        else:
            await self.update(task, final_model, LEARNER_FEEDBACK_NEGATIVE)
            for failed in failed_models:
                await self.update(task, failed, LEARNER_FALLBACK_PENALTY * 0.3)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        all_stats = self._store.all_model_stats()
        return {
            "enabled": self.enabled,
            "active": self.active,
            "mode": "active" if self.active else "shadow",
            "handoff_n": self._handoff_n,
            "tracked_pairs": len(all_stats),
            "total_samples": sum(s.get("n", 0) for s in all_stats.values()),
            "top_learned": sorted(
                (
                    {"pair": k, "mu": v.get("mu", 0.0), "n": v.get("n", 0)}
                    for k, v in all_stats.items()
                ),
                key=lambda x: x["mu"],
                reverse=True,
            )[:5],
        }


class DiversityGuard:
    """
    Anti-collapse monitor for learned routing (v1.0.3).

    Per arXiv "When Routing Collapses" (2026-02): learned routers can
    degenerate into always picking one model. Thompson Sampling + UCB
    mitigate this theoretically, but data imbalance can still starve models.

    Guard behavior:
    - Track the last ``window`` selections per task
    - If one model dominates (share > threshold), force exploration:
      with probability ``explore_rate`` per request, pick a non-top model
    """

    def __init__(
        self,
        window: int = DIVERSITY_WINDOW,
        dominance_threshold: float = DIVERSITY_DOMINANCE_THRESHOLD,
        explore_rate: float = DIVERSITY_EXPLORE_RATE,
        rng: Optional[random.Random] = None,
    ):
        self._window = window
        self._threshold = dominance_threshold
        self._explore_rate = explore_rate
        self._rng = rng or random.Random()
        self._history: dict[str, deque] = {}  # task -> recent model picks
        self._forced_count = 0

    def record(self, task: str, model: str) -> None:
        """Record one routing selection."""
        hist = self._history.setdefault(task, deque(maxlen=self._window))
        hist.append(model)

    def should_force_exploration(self, task: str) -> tuple[bool, float]:
        """
        Returns (force?, dominant_share).

        force=True only when the window is reasonably filled AND a single
        model dominates beyond the threshold.
        """
        hist = self._history.get(task)
        if not hist or len(hist) < max(10, self._window // 10):
            return False, 0.0
        counts: dict[str, int] = {}
        for m in hist:
            counts[m] = counts.get(m, 0) + 1
        share = max(counts.values()) / len(hist)
        return share > self._threshold, share

    def maybe_explore(self, task: str) -> bool:
        """Roll the exploration dice when dominance is detected."""
        force, _ = self.should_force_exploration(task)
        if force and self._rng.random() < self._explore_rate:
            self._forced_count += 1
            logger.warning(
                "Routing diversity degraded for task '%s' — forcing exploration pick",
                task,
            )
            return True
        return False

    def get_stats(self, task: Optional[str] = None) -> dict:
        """Diversity snapshot for /admin/learning."""
        stats: dict[str, dict] = {}
        for t, hist in self._history.items():
            if task and t != task:
                continue
            counts: dict[str, int] = {}
            for m in hist:
                counts[m] = counts.get(m, 0) + 1
            total = len(hist)
            stats[t] = {
                "window": total,
                "unique_models": len(counts),
                "diversity": round(len(counts) / total, 3) if total else 0.0,
                "dominant": max(counts, key=counts.get) if counts else None,
                "dominant_share": round(max(counts.values()) / total, 3) if total else 0.0,
            }
        return {
            "window_size": self._window,
            "dominance_threshold": self._threshold,
            "explore_rate": self._explore_rate,
            "forced_explorations": self._forced_count,
            "tasks": stats,
        }


# Global singleton (shadow mode by default — safe first launch)
learner = Learner()

# Global diversity guard (observes all routing decisions)
diversity_guard = DiversityGuard()
