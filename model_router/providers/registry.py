"""
Model Capability Enhancer for Model Router.

Takes the agent's registered model list and enhances each model's
capability profile with online data (LMSYS rankings, cost/speed data).

Key principle: Model Router does NOT register models. The agent owns
its model list. We only enrich capability data for models the agent
has already configured.

Dual-mode:
  Online:  Fetch rankings from LMSYS/Artificial Analysis to enhance profiles
  Offline: Use built-in rules to infer capabilities from model names
  Auto:    Try online first, fall back to offline on network failure

MOA Selection Modes:
  auto:   Router can automatically select this model (default)
  manual: Only used when user explicitly requests it (e.g., DALL-E, Sora)
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from model_router.config.defaults import (
    DEFAULT_CAPABILITY_SCORE,
    DEFAULT_REGISTRY_MODE,
    DOMAINS,
    REGISTRY_CACHE_DIR,
    REGISTRY_CACHE_FILE,
    REGISTRY_CACHE_TTL,
    REGISTRY_FETCH_TIMEOUT,
    REGISTRY_LOCAL_WEIGHT,
    REGISTRY_LMSYS_URL,
    REGISTRY_ONLINE_WEIGHT,
    REGISTRY_ARTIFICIAL_URL,
)

logger = logging.getLogger(__name__)


@dataclass
class ModelProfile:
    """Enhanced capability profile for a model the agent has registered."""
    model_id: str
    name: str
    provider: str = ""
    capabilities: dict = field(default_factory=dict)
    context_window: int = 128000
    max_output_tokens: int = 4096
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    latency_tier: str = "medium"  # fast / medium / slow
    input_modalities: list = field(default_factory=lambda: ["text"])
    output_modalities: list = field(default_factory=lambda: ["text"])
    supports_tool_call: bool = True
    supports_reasoning: bool = False
    supports_streaming: bool = True
    overall_score: float = 0.0  # from online leaderboard
    source: str = "local"  # "local", "enhanced"
    selection_mode: str = "auto"  # "auto" = router can select, "manual" = user must explicitly request

    @property
    def supports_vision(self) -> bool:
        """v1.9.0: Derived from input_modalities — True if model accepts image input."""
        return "image" in self.input_modalities

    def get_capability(self, domain: str) -> float:
        """Get capability score for a domain (0-10)."""
        return float(self.capabilities.get(domain, DEFAULT_CAPABILITY_SCORE))

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ModelProfile":
        """Deserialize from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ModelRegistry:
    """
    Model capability registry.

    Takes the agent's model list and enhances capability profiles.
    Does NOT add or remove models — the agent controls its own model list.

    MOA selection modes:
    - auto:   Router can automatically select this model during routing
    - manual: Only used when user explicitly specifies model in request

    Usage:
        registry = ModelRegistry()
        await registry.initialize(agent_models_config, mode="auto")
        profile = registry.get_profile("gpt-4o")
    """

    def __init__(self, cache_dir: Optional[str] = None):
        self._profiles: dict[str, ModelProfile] = {}
        self._mode = DEFAULT_REGISTRY_MODE
        self._cache_dir = Path(cache_dir or REGISTRY_CACHE_DIR)
        self._cache_path = self._cache_dir / REGISTRY_CACHE_FILE
        self._initialized = False

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def profiles(self) -> dict[str, ModelProfile]:
        return self._profiles

    async def initialize(
        self,
        models_config: dict,
        mode: str = DEFAULT_REGISTRY_MODE,
    ) -> None:
        """
        Initialize from the agent's model config.

        Args:
            models_config: The agent's models dict (from config.yaml)
            mode: "online", "offline", or "auto"
        """
        self._mode = mode
        logger.info(
            "Initializing registry for %d agent models (mode=%s)",
            len(models_config), mode,
        )

        # Step 1: Build profiles from agent's config (always)
        self._load_from_agent_config(models_config)

        # Step 2: Try to enhance with online data
        if mode in ("online", "auto"):
            enhanced = await self._enhance_from_online()
            if enhanced:
                logger.info("Enhanced %d profiles with online data", enhanced)
            elif mode == "auto":
                logger.info("Online unavailable, using local profiles")

        self._initialized = True

        auto_count = sum(1 for p in self._profiles.values() if p.selection_mode == "auto")
        manual_count = len(self._profiles) - auto_count
        logger.info(
            "Registry ready: %d models (%d enhanced, %d auto, %d manual)",
            len(self._profiles),
            sum(1 for p in self._profiles.values() if p.source == "enhanced"),
            auto_count,
            manual_count,
        )

    def get_profile(self, model_key: str) -> Optional[ModelProfile]:
        """Get model profile by key."""
        return self._profiles.get(model_key)

    def list_models(self) -> list[str]:
        """List all model keys from agent's config."""
        return list(self._profiles.keys())

    def get_candidates(
        self,
        requires_vision: bool = False,
        min_context_window: int = 0,
        auto_only: bool = False,
        required_input: Optional[list[str]] = None,
        required_output: Optional[list[str]] = None,
        requires_tool_call: Optional[bool] = None,
    ) -> list[ModelProfile]:
        """
        Get candidate models matching constraints.

        Only returns models the agent has registered.

        Args:
            requires_vision: Filter for vision-capable models (deprecated: use required_input=["image"])
            min_context_window: Minimum context window size
            auto_only: If True, only return models with selection_mode="auto"
            required_input: List of required input modalities (e.g. ["image"])
            required_output: List of required output modalities (e.g. ["image"])
            requires_tool_call: If True, only return models supporting tool calls
        """
        candidates = []
        for profile in self._profiles.values():
            # v1.9.0: modality-based filtering (replaces supports_vision)
            if requires_vision and "image" not in profile.input_modalities:
                continue
            if required_input:
                if not all(m in profile.input_modalities for m in required_input):
                    continue
            if required_output:
                if not all(m in profile.output_modalities for m in required_output):
                    continue
            if requires_tool_call is True and not profile.supports_tool_call:
                continue
            if profile.context_window < min_context_window:
                continue
            if auto_only and profile.selection_mode != "auto":
                continue
            candidates.append(profile)
        return candidates

    def get_auto_candidates(self, **kwargs) -> list[ModelProfile]:
        """Shortcut: get only auto-selectable models."""
        return self.get_candidates(auto_only=True, **kwargs)

    def get_manual_models(self) -> list[ModelProfile]:
        """Get all manual-only models (excluded from auto-routing)."""
        return [p for p in self._profiles.values() if p.selection_mode == "manual"]

    # ---------------------------------------------------------------
    # Step 1: Load from agent's config
    # ---------------------------------------------------------------

    def _load_from_agent_config(self, models_config: dict) -> None:
        """Build profiles from the agent's model configuration."""
        for key, cfg in models_config.items():
            # v1.9.0: populate modality fields from enriched config
            input_mod = cfg.get("input_modalities", ["text"])
            output_mod = cfg.get("output_modalities", ["text"])
            # Backward compat: if old config has multimodal=True but no input_modalities, add image
            if cfg.get("multimodal", False) and "image" not in input_mod:
                input_mod = list(input_mod) + ["image"]
            profile = ModelProfile(
                model_id=cfg.get("model", key),
                name=cfg.get("name", key),
                provider=cfg.get("provider", ""),
                capabilities=cfg.get("capabilities", {}),
                context_window=cfg.get("context_window", 128000),
                max_output_tokens=cfg.get("max_output_tokens", 4096),
                cost_per_1k_input=cfg.get("cost_per_1k_input", 0.0),
                cost_per_1k_output=cfg.get("cost_per_1k_output", 0.0),
                latency_tier=cfg.get("latency_tier", "medium"),
                input_modalities=input_mod,
                output_modalities=output_mod,
                supports_tool_call=cfg.get("supports_tool_call", True),
                supports_reasoning=cfg.get("supports_reasoning", False),
                supports_streaming=cfg.get("supports_streaming", True),
                selection_mode=cfg.get("selection_mode", "auto"),
                source="local",
            )
            # If agent didn't define capabilities, infer from model name
            if not profile.capabilities:
                profile.capabilities = self._infer_capabilities(cfg)
            self._profiles[key] = profile

            if profile.selection_mode == "manual":
                logger.info("Model %s marked as manual-only (excluded from auto-routing)", key)

    def _infer_capabilities(self, cfg: dict) -> dict:
        """
        Infer capability scores from model name heuristics.

        This is the offline fallback — when no online data is available,
        we guess capabilities based on known model names.
        """
        tier = cfg.get("tier", "pro")
        name = cfg.get("model", "").lower()

        # Base scores by tier
        if tier == "flash":
            base = {d: 4.0 for d in DOMAINS}
        else:
            base = {d: 6.0 for d in DOMAINS}

        # Known model specialties
        if any(x in name for x in ("coder", "code", "codestral", "deepseek-coder")):
            base["coding"] = 9.0
            base["math"] = max(base["math"], 7.0)
        if any(x in name for x in ("o1", "o3", "reasoner", "thinking", "deepseek-r1")):
            base["reasoning"] = 9.0
            base["math"] = max(base["math"], 8.0)
        if any(x in name for x in ("gemini", "claude-3", "gpt-4o")) and cfg.get("multimodal"):
            base["vision"] = 8.0
        if any(x in name for x in ("claude", "gpt-4")):
            base["creative"] = max(base["creative"], 7.0)
            base["reasoning"] = max(base["reasoning"], 7.0)
        if any(x in name for x in ("gemini-flash", "flash")):
            base = {d: max(d_val, 3.0) for d, d_val in base.items()}
            for d in DOMAINS:
                base[d] = min(base[d], 5.0)

        return base

    # ---------------------------------------------------------------
    # Step 2: Enhance existing profiles with online data
    # ---------------------------------------------------------------

    async def _enhance_from_online(self) -> int:
        """
        Fetch online data to ENHANCE existing model profiles.

        Does NOT add new models. Only updates capability scores,
        cost, and speed data for models the agent has already registered.

        Returns number of profiles enhanced.
        """
        # Try cache first
        if self._load_cache():
            return len(self._profiles)

        enhanced_count = 0
        try:
            import httpx
            async with httpx.AsyncClient(timeout=REGISTRY_FETCH_TIMEOUT) as client:
                count = await self._enhance_from_lmsys(client)
                enhanced_count += count

                count = await self._enhance_from_artificial_analysis(client)
                enhanced_count += count
        except Exception as e:
            logger.debug("Online enhancement failed: %s", e)
            return 0

        if enhanced_count > 0:
            self._save_cache()

        return enhanced_count

    async def _enhance_from_lmsys(self, client) -> int:
        """Enhance existing profiles with LMSYS ELO rankings."""
        try:
            resp = await client.get(REGISTRY_LMSYS_URL)
            if resp.status_code != 200:
                return 0

            data = resp.json()
            entries = data if isinstance(data, list) else data.get("data", data.get("leaderboard", []))

            online_scores = {}
            for entry in entries:
                model_name = entry.get("model", entry.get("name", ""))
                if not model_name:
                    continue
                elo = float(entry.get("elo_rating", entry.get("arena_score", 0)))
                normalized = max(0, min(10, (elo - 800) / 60))
                online_scores[self._normalize_key(model_name)] = normalized

            enhanced = 0
            for key, profile in self._profiles.items():
                online_score = online_scores.get(key)
                if online_score is None:
                    online_score = online_scores.get(self._normalize_key(profile.model_id))

                if online_score is not None:
                    for domain in DOMAINS:
                        local_score = profile.capabilities.get(domain, DEFAULT_CAPABILITY_SCORE)
                        profile.capabilities[domain] = (
                            online_score * REGISTRY_ONLINE_WEIGHT
                            + local_score * REGISTRY_LOCAL_WEIGHT
                        )
                    profile.overall_score = online_score
                    profile.source = "enhanced"
                    enhanced += 1

            logger.info("LMSYS: enhanced %d/%d models", enhanced, len(self._profiles))
            return enhanced
        except Exception as e:
            logger.debug("LMSYS enhancement failed: %s", e)
            return 0

    async def _enhance_from_artificial_analysis(self, client) -> int:
        """Enhance existing profiles with cost and speed data."""
        try:
            resp = await client.get(REGISTRY_ARTIFICIAL_URL)
            if resp.status_code != 200:
                return 0

            data = resp.json()
            models = data if isinstance(data, list) else data.get("data", [])

            online_data = {}
            for m in models:
                model_id = m.get("id", m.get("model", ""))
                online_data[self._normalize_key(model_id)] = m

            enhanced = 0
            for key, profile in self._profiles.items():
                online_model = online_data.get(key)
                if online_model is None:
                    online_model = online_data.get(self._normalize_key(profile.model_id))

                if online_model is None:
                    continue

                pricing = online_model.get("pricing", {})
                if pricing:
                    profile.cost_per_1k_input = float(pricing.get("input_per_1k", profile.cost_per_1k_input))
                    profile.cost_per_1k_output = float(pricing.get("output_per_1k", profile.cost_per_1k_output))

                speed = online_model.get("speed", {})
                if speed:
                    tps = float(speed.get("tokens_per_second", 0))
                    if tps > 50:
                        profile.latency_tier = "fast"
                    elif tps > 20:
                        profile.latency_tier = "medium"
                    else:
                        profile.latency_tier = "slow"

                if profile.source != "enhanced":
                    profile.source = "enhanced"
                enhanced += 1

            logger.info("Artificial Analysis: enhanced %d/%d models", enhanced, len(self._profiles))
            return enhanced
        except Exception as e:
            logger.debug("Artificial Analysis enhancement failed: %s", e)
            return 0

    # ---------------------------------------------------------------
    # Cache
    # ---------------------------------------------------------------

    def _load_cache(self) -> bool:
        """Load enhanced profiles from local cache."""
        try:
            if not self._cache_path.exists():
                return False

            cache_data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            cache_time = cache_data.get("timestamp", 0)

            if time.time() - cache_time > REGISTRY_CACHE_TTL:
                logger.debug("Cache expired (age: %.1fh)", (time.time() - cache_time) / 3600)
                return False

            loaded = 0
            for key, profile_data in cache_data.get("profiles", {}).items():
                if key in self._profiles:
                    cached = ModelProfile.from_dict(profile_data)
                    if cached.capabilities:
                        self._profiles[key].capabilities = cached.capabilities
                        self._profiles[key].overall_score = cached.overall_score
                        self._profiles[key].source = "enhanced"
                    if cached.cost_per_1k_input > 0:
                        self._profiles[key].cost_per_1k_input = cached.cost_per_1k_input
                        self._profiles[key].cost_per_1k_output = cached.cost_per_1k_output
                    if cached.latency_tier:
                        self._profiles[key].latency_tier = cached.latency_tier
                    loaded += 1

            return loaded > 0
        except Exception as e:
            logger.debug("Cache load failed: %s", e)
            return False

    def _save_cache(self) -> None:
        """Save enhanced profiles to local cache."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "timestamp": time.time(),
                "profiles": {k: v.to_dict() for k, v in self._profiles.items()},
            }
            self._cache_path.write_text(
                json.dumps(cache_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug("Cache saved: %d models", len(self._profiles))
        except Exception as e:
            logger.warning("Cache save failed: %s", e)

    @staticmethod
    def _normalize_key(name: str) -> str:
        """Normalize model name for matching."""
        return name.lower().strip().replace(" ", "-")


# Global singleton instance (per-process, per-agent)
model_registry = ModelRegistry()
