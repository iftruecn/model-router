"""
Offline evaluator (v1.2.0): replay the request log to quantify
how much self-learning actually improved routing.

Read-only over MemoryStore — never mutates learning state.

Metrics:
  1. Per-mode funnel: requests / fallbacks / fallback_rate by routing_mode
     (static vs learned vs shadow)
  2. Learner signals: (task, model) pairs whose learned mu strongly
     diverges from a neutral prior (learner_avoids / learner_prefers)
  3. Mu distribution: histogram-like summary of all learned scores
  4. Per-task breakdown: fallback rates grouped by task domain
  5. Diversity check via DiversityGuard stats
  6. Conclusion: machine-readable verdict on whether learning helps
"""

import logging
from collections import defaultdict

from model_router.core.learner import diversity_guard, learner
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
        by_task: dict[str, dict] = {}
        for entry in logs:
            mode = entry.get("routing_mode", "static")
            bucket = by_mode.setdefault(
                mode, {"requests": 0, "fallbacks": 0, "models_used": set(),
                       "total_latency_ms": 0.0, "latency_count": 0}
            )
            bucket["requests"] += 1
            if entry.get("failed_models"):
                bucket["fallbacks"] += 1
            if entry.get("final_model"):
                bucket["models_used"].add(entry["final_model"])
            if entry.get("latency_ms") is not None:
                bucket["total_latency_ms"] += entry["latency_ms"]
                bucket["latency_count"] += 1

            # Per-task breakdown
            task = entry.get("task", "unknown")
            tb = by_task.setdefault(
                task, {"requests": 0, "fallbacks": 0}
            )
            tb["requests"] += 1
            if entry.get("failed_models"):
                tb["fallbacks"] += 1

        for bucket in by_mode.values():
            bucket["fallback_rate"] = (
                round(bucket["fallbacks"] / bucket["requests"], 4)
                if bucket["requests"]
                else 0.0
            )
            bucket["avg_latency_ms"] = (
                round(bucket["total_latency_ms"] / bucket["latency_count"], 1)
                if bucket["latency_count"]
                else None
            )
            del bucket["total_latency_ms"]
            del bucket["latency_count"]
            bucket["models_used"] = len(bucket["models_used"])

        for tb in by_task.values():
            tb["fallback_rate"] = (
                round(tb["fallbacks"] / tb["requests"], 4)
                if tb["requests"]
                else 0.0
            )

        return {
            "sample_size": len(logs),
            "by_routing_mode": by_mode,
            "by_task": by_task,
            "learner_signals": self._learner_signals(),
            "mu_distribution": self._mu_distribution(),
            "diversity": diversity_guard.get_stats(),
            "conclusion": self._conclude(by_mode, len(logs)),
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

    def _mu_distribution(self) -> dict:
        """Histogram-like summary of all learned mu values."""
        all_stats = self._memory.all_model_stats()
        if not all_stats:
            return {"total_pairs": 0, "buckets": {}}

        buckets = {
            "strong_avoid (mu <= -0.3)": 0,
            "mild_avoid (-0.3 < mu < 0)": 0,
            "neutral (0 <= mu < 0.5)": 0,
            "mild_prefer (0.5 <= mu < 0.8)": 0,
            "strong_prefer (mu >= 0.8)": 0,
        }
        total_n = 0
        weighted_mu_sum = 0.0

        for key, stats in all_stats.items():
            n = stats.get("n", 0)
            mu = stats.get("mu", 0.0)
            total_n += n
            weighted_mu_sum += mu * n

            if mu <= -0.3:
                buckets["strong_avoid (mu <= -0.3)"] += 1
            elif mu < 0:
                buckets["mild_avoid (-0.3 < mu < 0)"] += 1
            elif mu < 0.5:
                buckets["neutral (0 <= mu < 0.5)"] += 1
            elif mu < 0.8:
                buckets["mild_prefer (0.5 <= mu < 0.8)"] += 1
            else:
                buckets["strong_prefer (mu >= 0.8)"] += 1

        avg_mu = round(weighted_mu_sum / total_n, 4) if total_n > 0 else 0.0

        return {
            "total_pairs": len(all_stats),
            "total_samples": total_n,
            "weighted_avg_mu": avg_mu,
            "buckets": buckets,
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _conclude(by_mode: dict, sample_size: int) -> str:
        if sample_size < 20:
            return (
                f"insufficient_data: only {sample_size} requests logged "
                f"(need 20+ for meaningful evaluation)"
            )

        static = by_mode.get("static")
        learned = by_mode.get("learned")

        if not static and not learned:
            return "insufficient_data: no static or learned traffic observed"

        if not static:
            return (
                f"insufficient_data: all {sample_size} requests routed in "
                f"'learned' or 'shadow' mode — no static baseline to compare"
            )

        if not learned:
            return (
                f"insufficient_data: all {sample_size} requests routed in "
                f"'static' mode — learner hasn't taken over yet "
                f"(need 200+ samples for handoff)"
            )

        delta = static["fallback_rate"] - learned["fallback_rate"]
        if delta > HELP_DELTA:
            return (
                f"learning_helps: learned fallback rate "
                f"{learned['fallback_rate']:.1%} vs static {static['fallback_rate']:.1%} "
                f"(delta={delta:.1%}, {learned['requests']} learned requests)"
            )
        if delta < -HELP_DELTA:
            return (
                f"learning_needs_review: learned fallback rate higher "
                f"than static by {-delta:.1%} "
                f"({learned['requests']} learned vs {static['requests']} static)"
            )
        return (
            f"neutral: learned and static show similar fallback rates "
            f"({learned['fallback_rate']:.1%} vs {static['fallback_rate']:.1%})"
        )


# Global singleton
offline_evaluator = OfflineEvaluator()
