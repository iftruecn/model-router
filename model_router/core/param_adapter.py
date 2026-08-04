"""
Request parameter adaptation for Model Router v1.7.0.

Different providers support different parameter names and values.
This module normalizes parameters before forwarding and downgrades
invalid values to the closest supported alternative.

Zero external dependencies.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Provider-specific parameter support tables
# Each entry: {param_name: {allowed_values, aliases, default}}

PROVIDER_PARAMS: dict[str, dict[str, dict]] = {
    "default": {
        "max_tokens": {"aliases": ["max_output_tokens", "max_completion_tokens"]},
        "temperature": {"range": [0.0, 2.0]},
        "top_p": {"range": [0.0, 1.0]},
    },
    "deepseek": {
        "max_tokens": {"aliases": ["max_output_tokens"], "range": [1, 8192]},
        "temperature": {"range": [0.0, 2.0]},
        "top_p": {"range": [0.0, 1.0]},
        "reasoning_effort": {
            "allowed": ["low", "medium", "high"],
            "downgrade_map": {
                "ultra": "high",
                "critical": "high",
                "minimal": "low",
                "none": "low",
            },
        },
    },
    "openai": {
        "max_tokens": {"aliases": ["max_output_tokens", "max_completion_tokens"]},
        "temperature": {"range": [0.0, 2.0]},
        "top_p": {"range": [0.0, 1.0]},
        "reasoning_effort": {
            "allowed": ["low", "medium", "high"],
            "downgrade_map": {
                "ultra": "high",
                "critical": "high",
                "minimal": "low",
                "none": "low",
            },
        },
    },
    "anthropic": {
        "max_tokens": {"aliases": ["max_output_tokens"], "required": True},
        "temperature": {"range": [0.0, 1.0]},
        "top_p": {"range": [0.0, 1.0]},
    },
    "google": {
        "max_tokens": {"aliases": ["max_output_tokens", "maxOutputTokens"]},
        "temperature": {"range": [0.0, 2.0]},
        "top_p": {"range": [0.0, 1.0]},
    },
    "doubao": {
        "max_tokens": {"aliases": ["max_output_tokens"], "range": [1, 4096]},
        "temperature": {"range": [0.0, 2.0]},
        "top_p": {"range": [0.0, 1.0]},
    },
    # P2-9: additional provider support
    "mistral": {
        "max_tokens": {"aliases": ["max_output_tokens"], "range": [1, 8192]},
        "temperature": {"range": [0.0, 1.0]},
        "top_p": {"range": [0.0, 1.0]},
    },
    "together": {
        "max_tokens": {"aliases": ["max_output_tokens", "max_completion_tokens"]},
        "temperature": {"range": [0.0, 2.0]},
        "top_p": {"range": [0.0, 1.0]},
    },
    "groq": {
        "max_tokens": {"aliases": ["max_output_tokens"], "range": [1, 8192]},
        "temperature": {"range": [0.0, 2.0]},
        "top_p": {"range": [0.0, 1.0]},
    },
}


def _detect_provider(base_url: str) -> str:
    """Detect provider name from base_url."""
    url_lower = base_url.lower()
    if "deepseek" in url_lower:
        return "deepseek"
    if "openai" in url_lower:
        return "openai"
    if "anthropic" in url_lower:
        return "anthropic"
    if "google" in url_lower or "generativelanguage" in url_lower:
        return "google"
    # P3-5 fix: "ark" is too short — require "/ark/" or "volcengine" to avoid false positives
    if "volces" in url_lower or "doubao" in url_lower or "/ark/" in url_lower or "volcengine" in url_lower:
        return "doubao"
    if "mistral" in url_lower:
        return "mistral"
    if "together" in url_lower:
        return "together"
    if "groq" in url_lower:
        return "groq"
    return "default"


def adapt_request_params(
    request_data: dict,
    base_url: str,
) -> dict:
    """
    Adapt request parameters for the target provider.

    - Normalize parameter name aliases (max_output_tokens → max_tokens)
    - Downgrade unsupported values (reasoning_effort=ultra → high)
    - Clamp out-of-range values

    Returns a copy of request_data with adapted parameters.
    Original is not modified.
    """
    provider = _detect_provider(base_url)
    provider_cfg = PROVIDER_PARAMS.get(provider, PROVIDER_PARAMS["default"])
    adapted = dict(request_data)

    for param_name, param_cfg in provider_cfg.items():
        if param_name not in adapted and "aliases" in param_cfg:
            # Check aliases — normalize to canonical name
            for alias in param_cfg["aliases"]:
                if alias in adapted:
                    adapted[param_name] = adapted.pop(alias)
                    logger.debug(
                        "Param alias: %s → %s (provider=%s)",
                        alias, param_name, provider,
                    )
                    break

        if param_name not in adapted:
            continue

        value = adapted[param_name]

        # Value downgrade (e.g., reasoning_effort)
        if "allowed" in param_cfg and value not in param_cfg["allowed"]:
            downgrade_map = param_cfg.get("downgrade_map", {})
            if value in downgrade_map:
                new_value = downgrade_map[value]
                logger.info(
                    "Param downgrade: %s=%s → %s (provider=%s)",
                    param_name, value, new_value, provider,
                )
                adapted[param_name] = new_value
            else:
                # Unknown value — remove to avoid 400
                logger.warning(
                    "Param %s=%s not supported by %s, removing",
                    param_name, value, provider,
                )
                del adapted[param_name]

        # Range clamp
        if "range" in param_cfg and isinstance(value, (int, float)):
            lo, hi = param_cfg["range"]
            if value < lo or value > hi:
                clamped = max(lo, min(hi, value))
                logger.info(
                    "Param clamp: %s=%s → %s (range=[%s,%s], provider=%s)",
                    param_name, value, clamped, lo, hi, provider,
                )
                adapted[param_name] = clamped

    # Remove known unsupported params (provider-specific exclusions)
    # e.g., some providers don't support reasoning_effort at all
    if provider not in ("deepseek", "openai"):
        if "reasoning_effort" in adapted:
            logger.debug(
                "Removing reasoning_effort for provider %s", provider,
            )
            del adapted["reasoning_effort"]

    return adapted
