"""
Smart routing engine for Model Router v1.0.2.

Combines query feature extraction (classifier) with model capability
profiles (registry) to select the best model for each query.

MOA Selection Modes:
- auto:   Router automatically selects the best model (default)
- manual: User explicitly specifies model in request — router respects it

Scoring formula:
  model_score = capability_match * W_c - cost_penalty * W_cost + speed_bonus * W_s

v1.0.2 additions:
- Routing presets: intelligence / balance / cost (weight profiles)
- Learned score fusion: Gaussian Thompson Sampling (progressive handoff,
  shadow mode by default — see core/learner.py)
- Cost accounting: estimated savings vs strongest candidate
- Request log: bounded ring buffer for feedback attribution
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from model_router.core.classifier import QueryFeatures, domain_classifier
from model_router.config.defaults import (
    DEFAULT_MAX_FALLBACK_ATTEMPTS,
    DOMAINS,
    ROUTER_CAPABILITY_WEIGHT,
    ROUTER_COST_WEIGHT,
    ROUTER_MAX_COST_PER_1K,
    ROUTER_SPEED_FAST,
    ROUTER_SPEED_SLOW,
    ROUTER_SPEED_WEIGHT,
    ROUTING_DEFAULT_PRESET,
    ROUTING_PRESETS,
)
from model_router.core.learner import Learner, learner as global_learner
from model_router.core.memory import MemoryStore, memory_store as global_memory
from model_router.providers.registry import ModelProfile, model_registry

logger = logging.getLogger(__name__)

# Rough tokens estimate used for cost accounting (input chars -> tokens)
_CHARS_PER_TOKEN: float = 4.0
_ASSUMED_OUTPUT_TOKENS: float = 500.0


@dataclass
class RoutingResult:
    """Result of model routing decision."""
    model_key: str
    model_name: str
    score: float
    reason: str
    features: Optional[dict] = None
    candidates_scored: int = 0
    top_candidates: list = field(default_factory=list)
    is_explicit: bool = False  # True if user explicitly selected this model
    routing_mode: str = "static"  # static | shadow | learned
    preset: str = ROUTING_DEFAULT_PRESET
    estimated_cost: float = 0.0
    baseline_cost: float = 0.0

    def to_dict(self) -> dict:
        return {
            "model_key": self.model_key,
            "model_name": self.model_name,
            "score": round(self.score, 2),
            "reason": self.reason,
            "features": self.features,
            "candidates_scored": self.candidates_scored,
            "top_candidates": self.top_candidates[:5],
            "is_explicit": self.is_explicit,
            "routing_mode": self.routing_mode,
            "preset": self.preset,
        }

    def to_headers(self) -> dict:
        """Routing transparency headers (X-Routed-To / X-Routing-Reason)."""
        return {
            "X-Routed-To": self.model_key,
            "X-Routing-Reason": self.reason,
            "X-Routing-Mode": self.routing_mode,
            "X-Routing-Preset": self.preset,
        }


class SmartRouter:
    """
    Intelligent model router with multi-dimensional matching.

    Respects MOA selection modes:
    - If user specifies a model explicitly (model="dall-e-3"), use it directly
    - Otherwise, only consider models with selection_mode="auto"

    Supports 3 routing presets (intelligence / balance / cost) and blends
    learned scores from the Gaussian TS learner (progressive handoff).
    """

    def __init__(
        self,
        capability_weight: float = ROUTER_CAPABILITY_WEIGHT,
        cost_weight: float = ROUTER_COST_WEIGHT,
        speed_weight: float = ROUTER_SPEED_WEIGHT,
        preset: str = ROUTING_DEFAULT_PRESET,
        learner: Optional[Learner] = None,
        memory: Optional[MemoryStore] = None,
    ):
        self._base_weights = (capability_weight, cost_weight, speed_weight)
        self._preset = preset if preset in ROUTING_PRESETS else ROUTING_DEFAULT_PRESET
        self._classifier = domain_classifier
        self._registry = model_registry
        self._learner = learner or global_learner
        self._memory = memory or global_memory

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    @property
    def preset(self) -> str:
        return self._preset

    def set_preset(self, name: str) -> bool:
        """Set global routing preset. Returns False if name unknown."""
        if name not in ROUTING_PRESETS:
            logger.warning("Unknown routing preset: %s", name)
            return False
        self._preset = name
        logger.info("Routing preset set: %s", name)
        return True

    def _resolve_weights(self, preset_override: Optional[str]) -> tuple[float, float, float]:
        """Resolve scoring weights from preset (per-request override wins)."""
        name = preset_override if preset_override in ROUTING_PRESETS else self._preset
        p = ROUTING_PRESETS[name]
        return p["capability_weight"], p["cost_weight"], p["speed_weight"]

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def route(
        self,
        messages: list,
        models_config: dict,
        request_data: Optional[dict] = None,
        request_id: Optional[str] = None,
    ) -> RoutingResult:
        """
        Select the best model for the given request.

        If request_data contains an explicit "model" field, use that model
        directly (respects manual selection mode). Otherwise, auto-select
        from models with selection_mode="auto".

        Args:
            messages: Chat messages list
            models_config: Models configuration dict
            request_data: Full request data (may contain "model" or
                          "routing_preset" fields)
            request_id: Optional id used for request-log attribution

        Returns:
            RoutingResult with selected model and scoring details
        """
        request_data = request_data or {}

        # Check if user explicitly selected a model
        explicit_model = request_data.get("model")
        if explicit_model and explicit_model != "auto":
            return self._handle_explicit_model(explicit_model, models_config, request_data)

        # Auto-routing: only consider selection_mode="auto" models
        return await self._auto_route(messages, models_config, request_data, request_id)

    def _handle_explicit_model(
        self,
        model_key: str,
        models_config: dict,
        request_data: dict,
    ) -> RoutingResult:
        """
        Handle explicit model selection from user.

        When user specifies model="dall-e-3" (or any model), use it directly
        regardless of selection_mode. This allows manual-only models to be used
        when explicitly requested.
        """
        profile = self._registry.get_profile(model_key)

        if profile:
            logger.info("Explicit model selection: %s (mode=%s)", model_key, profile.selection_mode)
            return RoutingResult(
                model_key=model_key,
                model_name=profile.name,
                score=10.0,  # explicit selection = highest priority
                reason=f"explicit_selection(mode={profile.selection_mode})",
                is_explicit=True,
                preset=self._preset,
            )

        # Model not in registry but in config — still respect user's choice
        if model_key in models_config:
            cfg = models_config[model_key]
            logger.info("Explicit model selection (from config): %s", model_key)
            return RoutingResult(
                model_key=model_key,
                model_name=cfg.get("name", model_key),
                score=10.0,
                reason="explicit_selection(config)",
                is_explicit=True,
                preset=self._preset,
            )

        # Model not found at all
        logger.warning("Explicit model not found: %s", model_key)
        return RoutingResult(
            model_key=model_key,
            model_name=model_key,
            score=0.0,
            reason=f"model_not_found({model_key})",
            is_explicit=True,
            preset=self._preset,
        )

    async def _auto_route(
        self,
        messages: list,
        models_config: dict,
        request_data: dict,
        request_id: Optional[str] = None,
    ) -> RoutingResult:
        """
        Auto-select the best model from auto-selectable candidates.

        Only considers models with selection_mode="auto".
        Manual-only models (DALL-E, Sora, etc.) are excluded.
        """
        # 1. Extract query features
        features = self._classifier.classify(messages, models_config)

        # 2. Determine constraints
        requires_vision = features.requires_vision
        min_context = self._estimate_context_needed(features)

        # 3. Get auto-selectable candidates only
        candidates = self._registry.get_auto_candidates(
            requires_vision=requires_vision,
            min_context_window=min_context,
        )

        # Fallback: if no candidates from registry, build from config (auto only)
        if not candidates:
            candidates = self._build_auto_profiles_from_config(models_config)

        # 4. Resolve weights (preset, per-request override wins)
        preset_override = request_data.get("routing_preset")
        cap_w, cost_w, speed_w = self._resolve_weights(preset_override)
        active_preset = preset_override if preset_override in ROUTING_PRESETS else self._preset

        # 5. Score each candidate: static score + learned fusion
        task = features.primary_domain
        total_attempts = sum(
            self._learner.sample_count(task, p.model_id) for p in candidates
        )
        scored = []
        routing_mode = "static"
        for profile in candidates:
            static_score, breakdown = self._score_model(
                profile, features, cap_w, cost_w, speed_w
            )
            # Learned fusion (progressive handoff; shadow mode = no effect)
            learned = self._learner.learned_score(
                task,
                profile.model_id,
                total_attempts=total_attempts,
                explore=True,  # candidates are auto-mode; manual never enters
            )
            learned_scaled = ((learned + 1.0) * 5.0) if learned is not None else None
            n_samples = self._learner.sample_count(task, profile.model_id)
            blended, mode = self._learner.blend_score(
                static_score, learned_scaled, n_samples
            )
            if mode == "learned":
                routing_mode = "learned"
            elif mode == "shadow" and routing_mode == "static":
                routing_mode = "shadow"
            breakdown["learned_bonus"] = (
                round(blended - static_score, 2) if mode == "learned" else 0.0
            )
            scored.append((profile, blended, breakdown))

        # 6. Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # 7. Select best model
        if not scored:
            # Ultimate fallback: first auto model in config
            fallback_key = self._find_first_auto_model(models_config)
            return RoutingResult(
                model_key=fallback_key,
                model_name=models_config.get(fallback_key, {}).get("name", fallback_key),
                score=0.0,
                reason="no_auto_candidates",
                features=features.to_dict(),
                preset=active_preset,
            )

        best_profile, best_score, best_breakdown = scored[0]

        # Build top candidates list for logging
        top_candidates = [
            {
                "model": p.model_id,
                "score": round(s, 2),
                "breakdown": b,
            }
            for p, s, b in scored[:5]
        ]

        # 8. Cost accounting: estimated cost vs strongest (priciest) candidate
        estimated_tokens = features.context_length / _CHARS_PER_TOKEN + _ASSUMED_OUTPUT_TOKENS
        est_cost = self._estimate_cost(best_profile, estimated_tokens)
        baseline_cost = max(
            (self._estimate_cost(p, estimated_tokens) for p, _, _ in scored),
            default=est_cost,
        )
        self._memory.add_cost(est_cost, baseline_cost)

        # 9. Request log (ring buffer) for feedback attribution
        if request_id:
            self._memory.append_request_log({
                "request_id": request_id,
                "ts": time.time(),
                "task": task,
                "preset": active_preset,
                "routing_mode": routing_mode,
                "final_model": best_profile.model_id,
                "failed_models": [],  # filled by fallback chain when wired
                "candidates": [p.model_id for p, _, _ in scored[:5]],
            })

        result = RoutingResult(
            model_key=best_profile.model_id,
            model_name=best_profile.name,
            score=best_score,
            reason=f"auto_domain:{task}(score={features.primary_score:.1f})",
            features=features.to_dict(),
            candidates_scored=len(scored),
            top_candidates=top_candidates,
            routing_mode=routing_mode,
            preset=active_preset,
            estimated_cost=round(est_cost, 6),
            baseline_cost=round(baseline_cost, 6),
        )

        logger.info(
            "Auto-routed to %s (score=%.2f, domain=%s, preset=%s, mode=%s, candidates=%d)",
            best_profile.name, best_score, task, active_preset,
            routing_mode, len(scored),
        )
        logger.debug("Routing result: %s", result.to_dict())

        return result

    def _score_model(
        self,
        profile: ModelProfile,
        features: QueryFeatures,
        capability_weight: float,
        cost_weight: float,
        speed_weight: float,
    ) -> tuple[float, dict]:
        """
        Score a model against query features.

        Returns (total_score, breakdown_dict).
        """
        breakdown = {}

        # 1. Capability match: dot product of query domain scores and model capabilities
        capability_score = 0.0
        for domain, query_weight in features.domain_scores.items():
            if query_weight > 0:
                model_cap = profile.get_capability(domain)
                capability_score += query_weight * model_cap

        total_query_weight = sum(features.domain_scores.values()) or 1.0
        normalized_capability = capability_score / total_query_weight
        breakdown["capability"] = round(normalized_capability, 2)

        # 2. Cost penalty: cheaper models get lower penalty (better)
        avg_cost = (profile.cost_per_1k_input + profile.cost_per_1k_output) / 2
        if avg_cost > 0:
            cost_penalty = min(10.0, (avg_cost / ROUTER_MAX_COST_PER_1K) * 10)
        else:
            cost_penalty = 0.0
        breakdown["cost_penalty"] = round(cost_penalty, 2)

        # 3. Speed bonus: faster models get higher bonus
        speed_map = {"fast": 10.0, "medium": 5.0, "slow": 2.0}
        speed_bonus = speed_map.get(profile.latency_tier, 5.0)
        breakdown["speed_bonus"] = round(speed_bonus, 2)

        # 4. Ultra-short query: boost fast models
        if features.is_ultra_short:
            speed_bonus *= 1.5
            breakdown["speed_bonus"] = round(speed_bonus, 2)

        # 5. High complexity: boost capable (expensive) models
        if features.estimated_complexity >= 7:
            cost_penalty *= 0.5
            breakdown["cost_penalty"] = round(cost_penalty, 2)

        # Total score
        total = (
            normalized_capability * capability_weight
            - cost_penalty * cost_weight
            + speed_bonus * speed_weight
        )
        breakdown["total"] = round(total, 2)

        return total, breakdown

    @staticmethod
    def _estimate_cost(profile: ModelProfile, estimated_tokens: float) -> float:
        """Rough cost estimate for one request (input+output tokens)."""
        input_tokens = estimated_tokens * 0.6
        output_tokens = estimated_tokens * 0.4
        return (
            profile.cost_per_1k_input * input_tokens / 1000.0
            + profile.cost_per_1k_output * output_tokens / 1000.0
        )

    def _estimate_context_needed(self, features: QueryFeatures) -> int:
        """Estimate minimum context window needed."""
        base = features.context_length * 2
        if features.estimated_complexity >= 7:
            base *= 2
        elif features.estimated_complexity >= 4:
            base *= 1.5
        return max(4096, int(base))

    def _build_auto_profiles_from_config(self, models_config: dict) -> list[ModelProfile]:
        """Fallback: build ModelProfile list from config (auto models only)."""
        profiles = []
        for key, cfg in models_config.items():
            # Skip manual models in auto-routing
            if cfg.get("selection_mode", "auto") == "manual":
                continue
            profile = ModelProfile(
                model_id=cfg.get("model", key),
                name=cfg.get("name", key),
                provider=cfg.get("provider", ""),
                capabilities=cfg.get("capabilities", {}),
                context_window=cfg.get("context_window", 128000),
                cost_per_1k_input=cfg.get("cost_per_1k_input", 0.0),
                cost_per_1k_output=cfg.get("cost_per_1k_output", 0.0),
                latency_tier=cfg.get("latency_tier", "medium"),
                supports_vision=cfg.get("multimodal", False),
                selection_mode=cfg.get("selection_mode", "auto"),
                source="config_fallback",
            )
            profiles.append(profile)
        return profiles

    def _find_first_auto_model(self, models_config: dict) -> str:
        """Find the first auto-selectable model in config."""
        for key, cfg in models_config.items():
            if cfg.get("selection_mode", "auto") != "manual":
                return key
        # Fallback: return first model regardless
        return list(models_config.keys())[0] if models_config else "unknown"

    # ------------------------------------------------------------------
    # Learning loop entry points (called after response completes)
    # ------------------------------------------------------------------

    async def record_outcome(
        self,
        request_id: str,
        quality_passed: bool,
        latency_ms: float,
    ) -> Optional[dict]:
        """
        Record the outcome of a completed request and learn from it.

        Looks up the request log for attribution (task + final model),
        computes the continuous reward and updates the learner.
        Returns the reward breakdown, or None if request not found.
        """
        entry = self._memory.get_request(request_id)
        if entry is None:
            logger.warning("record_outcome: request %s not in log", request_id)
            return None

        task = entry.get("task", "chat")
        model = entry.get("final_model", "")
        if not model:
            return None

        components = await self._learner.record_outcome(
            task=task,
            model=model,
            quality_passed=quality_passed,
            latency_ms=latency_ms,
            cost=entry.get("cost", 0.0),
            baseline_cost=entry.get("baseline_cost", 0.0),
        )
        await self._memory.maybe_save()
        return {
            "task": task,
            "model": model,
            "reward": round(components.total, 4),
            "breakdown": {
                "quality": components.quality,
                "speed": components.speed,
                "cost": components.cost,
            },
        }

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_routing_stats(self) -> dict:
        """Get router statistics (incl. learning + cost stats)."""
        auto_count = sum(1 for p in self._registry.profiles.values() if p.selection_mode == "auto")
        manual_count = len(self._registry.profiles) - auto_count
        return {
            "capability_weight": self._base_weights[0],
            "cost_weight": self._base_weights[1],
            "speed_weight": self._base_weights[2],
            "preset": self._preset,
            "available_presets": list(ROUTING_PRESETS.keys()),
            "registry_mode": self._registry.mode,
            "total_models": len(self._registry.profiles),
            "auto_models": auto_count,
            "manual_models": manual_count,
            "learning": self._learner.get_stats(),
            "cost": self._memory.get_cost_stats(),
        }


# Global singleton instance
smart_router = SmartRouter()
