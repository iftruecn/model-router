"""
Fallback chain management for Model Router.

Handles model fallback logic with configurable limits and strategies.

v1.2.0: semantic trigger policy — HTTP status alone is not a failure
signal (LiteLLM issue #21377). ``should_fallback_on_error()`` decides
per error category whether the chain should walk on.
"""

import logging
from typing import Optional

from model_router.config.defaults import DEFAULT_MAX_FALLBACK_ATTEMPTS

logger = logging.getLogger(__name__)


def should_fallback_on_error(
    status_code: Optional[int],
    is_timeout: bool = False,
) -> tuple[bool, str]:
    """
    Decide whether an API error should trigger the fallback chain.

    Returns (fallback?, category). Categories:
        infra       5xx / timeout / connection — always fallback
        client      400/401/403/404* — never fallback (retrying another
                    model cannot fix request/auth problems)
        rate_limit  429 — fallback (another model may have headroom)
        unknown     no status / unexpected — fallback (safe default)

    * 404 usually means a bad model id / endpoint — switching models with
      the same broken config won't help, so it is treated as client error.
    """
    if is_timeout or status_code is None:
        return True, "timeout" if is_timeout else "unknown"
    if status_code == 429:
        return True, "rate_limit"
    if status_code >= 500:
        return True, "infra"
    if 400 <= status_code < 500:
        return False, "client"
    return True, "unknown"


class FallbackManager:
    """
    Manages fallback chain construction and limits.

    Prevents unlimited fallback attempts that could lead to excessive API calls
    and costs.
    """

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_FALLBACK_ATTEMPTS,
    ):
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        """Get maximum fallback attempts."""
        return self._max_attempts

    def build_chain(
        self,
        primary_model: str,
        fallback_chain_config: dict,
        models_config: dict,
    ) -> list[str]:
        """
        Build fallback chain with limit applied.

        Args:
            primary_model: The primary model key selected by classifier
            fallback_chain_config: Explicit fallback chain from config.yaml
            models_config: Full models configuration

        Returns:
            List of model keys to try, limited by max_attempts
        """
        # Get explicit chain or build automatic chain
        chain = fallback_chain_config.get(primary_model, [])
        if not chain:
            # Try tier-based lookup: find primary's tier, then use that
            primary_tier = models_config.get(
                primary_model, {},
            ).get("tier", "")
            if primary_tier and primary_tier in fallback_chain_config:
                chain = fallback_chain_config[primary_tier]
            else:
                chain = self._build_automatic_chain(
                    primary_model, models_config,
                )

        # Apply limit: primary + fallback attempts
        # e.g., max_attempts=3 means try primary + 2 fallbacks
        limited_chain = [primary_model] + chain[: self._max_attempts - 1]

        # Remove duplicates while preserving order
        seen = set()
        unique_chain = []
        for model in limited_chain:
            if model not in seen:
                seen.add(model)
                unique_chain.append(model)

        if len(chain) > len(unique_chain) - 1:
            logger.warning(
                "Fallback chain truncated: %d models available, limited to %d attempts",
                len(chain),
                self._max_attempts,
            )

        return unique_chain

    def _build_automatic_chain(
        self,
        primary_model: str,
        models_config: dict,
    ) -> list[str]:
        """
        Build automatic fallback chain based on model tiers.

        Prioritizes same-tier models, then cross-tier models.
        """
        primary_tier = models_config.get(primary_model, {}).get("tier", "pro")
        others = [k for k in models_config if k != primary_model]

        # Same tier first, then other tiers
        same_tier = [k for k in others if models_config[k].get("tier") == primary_tier]
        other_tier = [k for k in others if models_config[k].get("tier") != primary_tier]

        return same_tier + other_tier

    def get_stats(self) -> dict:
        """Get fallback manager statistics."""
        return {
            "max_attempts": self._max_attempts,
        }


# Global singleton instance
fallback_manager = FallbackManager()