"""
Smart routing engine for Model Router.

Combines query feature extraction (classifier) with model capability
profiles (registry) to select the best model for each query.

MOA Selection Modes:
- auto:   Router automatically selects the best model (default)
- manual: User explicitly specifies model in request — router respects it

Scoring formula:
  model_score = capability_match * W_c - cost_penalty * W_cost + speed_bonus * W_s
"""

import logging
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
)
from model_router.providers.registry import ModelProfile, model_registry

logger = logging.getLogger(__name__)


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
        }


class SmartRouter:
    """
    Intelligent model router with multi-dimensional matching.

    Respects MOA selection modes:
    - If user specifies a model explicitly (model="dall-e-3"), use it directly
    - Otherwise, only consider models with selection_mode="auto"
    """

    def __init__(
        self,
        capability_weight: float = ROUTER_CAPABILITY_WEIGHT,
        cost_weight: float = ROUTER_COST_WEIGHT,
        speed_weight: float = ROUTER_SPEED_WEIGHT,
    ):
        self._capability_weight = capability_weight
        self._cost_weight = cost_weight
        self._speed_weight = speed_weight
        self._classifier = domain_classifier
        self._registry = model_registry

    async def route(
        self,
        messages: list,
        models_config: dict,
        request_data: Optional[dict] = None,
    ) -> RoutingResult:
        """
        Select the best model for the given request.

        If request_data contains an explicit "model" field, use that model
        directly (respects manual selection mode). Otherwise, auto-select
        from models with selection_mode="auto".

        Args:
            messages: Chat messages list
            models_config: Models configuration dict
            request_data: Full request data (may contain explicit "model" field)

        Returns:
            RoutingResult with selected model and scoring details
        """
        request_data = request_data or {}

        # Check if user explicitly selected a model
        explicit_model = request_data.get("model")
        if explicit_model and explicit_model != "auto":
            return self._handle_explicit_model(explicit_model, models_config, request_data)

        # Auto-routing: only consider selection_mode="auto" models
        return await self._auto_route(messages, models_config, request_data)

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
            )

        # Model not found at all
        logger.warning("Explicit model not found: %s", model_key)
        return RoutingResult(
            model_key=model_key,
            model_name=model_key,
            score=0.0,
            reason=f"model_not_found({model_key})",
            is_explicit=True,
        )

    async def _auto_route(
        self,
        messages: list,
        models_config: dict,
        request_data: dict,
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

        # 4. Score each candidate
        scored = []
        for profile in candidates:
            score, breakdown = self._score_model(profile, features)
            scored.append((profile, score, breakdown))

        # 5. Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # 6. Select best model
        if not scored:
            # Ultimate fallback: first auto model in config
            fallback_key = self._find_first_auto_model(models_config)
            return RoutingResult(
                model_key=fallback_key,
                model_name=models_config.get(fallback_key, {}).get("name", fallback_key),
                score=0.0,
                reason="no_auto_candidates",
                features=features.to_dict(),
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

        result = RoutingResult(
            model_key=best_profile.model_id,
            model_name=best_profile.name,
            score=best_score,
            reason=f"auto_domain:{features.primary_domain}(score={features.primary_score:.1f})",
            features=features.to_dict(),
            candidates_scored=len(scored),
            top_candidates=top_candidates,
        )

        logger.info(
            "Auto-routed to %s (score=%.2f, domain=%s, candidates=%d, excluded_manual=%d)",
            best_profile.name, best_score, features.primary_domain, len(scored),
            len(self._registry.get_manual_models()),
        )
        logger.debug("Routing result: %s", result.to_dict())

        return result

    def _score_model(
        self,
        profile: ModelProfile,
        features: QueryFeatures,
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
            normalized_capability * self._capability_weight
            - cost_penalty * self._cost_weight
            + speed_bonus * self._speed_weight
        )
        breakdown["total"] = round(total, 2)

        return total, breakdown

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

    def get_routing_stats(self) -> dict:
        """Get router statistics."""
        auto_count = sum(1 for p in self._registry.profiles.values() if p.selection_mode == "auto")
        manual_count = len(self._registry.profiles) - auto_count
        return {
            "capability_weight": self._capability_weight,
            "cost_weight": self._cost_weight,
            "speed_weight": self._speed_weight,
            "registry_mode": self._registry.mode,
            "total_models": len(self._registry.profiles),
            "auto_models": auto_count,
            "manual_models": manual_count,
        }


# Global singleton instance
smart_router = SmartRouter()
