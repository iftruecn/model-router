"""
Offline evaluator (v1.0.4): replay the request log to quantify
how much self-learning actually improved routing.

Read-only over MemoryStore — never mutates learning state.

Metrics:
  1. Per-mode funnel: requests / fallbacks / fallback_rate by routing_mode
     (static vs learned vs shadow)
  2. Learner signals: (task, model) pairs whose learned mu strongly
     diverges from a neutral prior (learner_avoids / learner_prefers)
  3. Diversity check via DiversityGuard stats
  4. Conclusion: machine-readable verdict on whether learning helps
"""

import logging

from model_router.core.learner import diversity_guard
from model_router.core.memory import memory_store

logger = logging.getLogger(__name__)

MIN_SAMPLES = 10          # only judge pairs with enough evidence
MU_AVOID = -0.3           # learned mu below this => learner avoids this pair
MU_PREFER = 0.5           # learned mu above this => learner prefers this pair
HELP_DELTA = 0.01         # min fallback-rate difference to call it a win


class OfflineEvaluator:
    """Replay stored routing history and judge learning value."""

    def __init__(self, memory=None):
        self._memory = memory or memory_store

    # ------------------------------------------------------------------

    def evaluate(self, limit: int = 1000) -> dict:
        """Build the full evaluation report from stored history."""
        logs = self._memory.recent_requests(limit)

        by_mode: dict[str, dict] = {}
        for entry in logs:
            mode = entry.get("routing_mode", "static")
            bucket = by_mode.setdefault(
                mode, {"requests": 0, "fallbacks": 0, "models_used": set()}
            )
            bucket["requests"] += 1
            if entry.get("failed_models"):
                bucket["fallbacks"] += 1
            if entry.get("final_model"):
                bucket["models_used"].add(entry["final_model"])

        for bucket in by_mode.values():
            bucket["fallback_rate"] = (
                round(bucket["fallbacks"] / bucket["requests"], 4)
                if bucket["requests"]
                else 0.0
            )
            bucket["models_used"] = len(bucket["models_used"])

        return {
            "sample_size": len(logs),
            "by_routing_mode": by_mode,
            "learner_signals": self._learner_signals(),
            "diversity": diversity_guard.get_stats(),
            "conclusion": self._conclude(by_mode),
        }

    # ------------------------------------------------------------------

    def _learner_signals(self) -> list[dict]:
        """(task, model) pairs where learning moved mu strongly."""
        signals = []
        for key, stats in self._memory.all_model_stats().items():
            n = stats.get("n", 0)
            if n < MIN_SAMPLES:
                continue
            mu = stats.get("mu", 0.0)
            if MU_AVOID < mu < MU_PREFER:
                continue
            task, _, model = key.partition("|")
            signals.append({
                "task": task,
                "model": model,
                "mu": round(mu, 3),
                "n": n,
                "verdict": "learner_avoids" if mu <= MU_AVOID else "learner_prefers",
            })
        signals.sort(key=lambda s: abs(s["mu"]), reverse=True)
        return signals[:10]

    # ------------------------------------------------------------------

    @staticmethod
    def _conclude(by_mode: dict) -> str:
        static = by_mode.get("static")
        learned = by_mode.get("learned")
        if not static or not learned:
            return "insufficient_data: need both static and learned traffic to compare"
        delta = static["fallback_rate"] - learned["fallback_rate"]
        if delta > HELP_DELTA:
            return (
                f"learning_helps: learned fallback rate "
                f"{learned['fallback_rate']:.1%} vs static {static['fallback_rate']:.1%}"
            )
        if delta < -HELP_DELTA:
            return (
                f"learning_needs_review: learned fallback rate higher "
                f"than static by {-delta:.1%}"
            )
        return "neutral: learned and static show similar fallback rates"


# Global singleton
offline_evaluator = OfflineEvaluator()
