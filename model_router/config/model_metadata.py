"""
Built-in model metadata for Model Router v1.9.0.

Fallback table when /v1/models doesn't return full metadata.
Contains real parameters for popular models — context windows,
max output tokens, supported features, input/output modalities.

Maintained by the team. Update as providers release new models.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Known model metadata
# Source: official provider documentation (2026-08)
MODEL_METADATA: dict[str, dict] = {
    # ── DeepSeek ──
    "deepseek-chat": {
        "context_window": 64000,
        "max_output_tokens": 8192,
        "supports_vision": False,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": False,
        "reasoning_effort_values": ["low", "medium", "high"],
        "tier": "pro",
    },
    "deepseek-v4-flash": {
        "context_window": 262144,
        "max_output_tokens": 8192,
        "supports_vision": False,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": False,
        "reasoning_effort_values": ["low", "medium", "high"],
        "tier": "flash",
    },
    "deepseek-v4-pro": {
        "context_window": 262144,
        "max_output_tokens": 8192,
        "supports_vision": False,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": True,
        "reasoning_effort_values": ["low", "medium", "high"],
        "tier": "pro",
    },
    "deepseek-reasoner": {
        "context_window": 64000,
        "max_output_tokens": 8192,
        "supports_vision": False,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "supports_tool_call": False,
        "supports_reasoning": True,
        "reasoning_effort_values": ["low", "medium", "high"],
        "tier": "pro",
    },
    # ── OpenAI ──
    "gpt-4o": {
        "context_window": 128000,
        "max_output_tokens": 16384,
        "supports_vision": True,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": False,
        "tier": "pro",
    },
    "gpt-4o-mini": {
        "context_window": 128000,
        "max_output_tokens": 16384,
        "supports_vision": True,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": False,
        "tier": "flash",
    },
    "o3-mini": {
        "context_window": 200000,
        "max_output_tokens": 100000,
        "supports_vision": True,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": True,
        "reasoning_effort_values": ["low", "medium", "high"],
        "tier": "pro",
    },
    # ── Anthropic ──
    "claude-sonnet-4-20250514": {
        "context_window": 200000,
        "max_output_tokens": 8192,
        "supports_vision": True,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": False,
        "tier": "pro",
    },
    "claude-3-5-haiku-20241022": {
        "context_window": 200000,
        "max_output_tokens": 8192,
        "supports_vision": False,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": False,
        "tier": "flash",
    },
    # ── Google ──
    "gemini-2.0-flash": {
        "context_window": 1048576,
        "max_output_tokens": 8192,
        "supports_vision": True,
        "input_modalities": ["text", "image", "audio", "video"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": False,
        "tier": "flash",
    },
    "gemini-2.5-pro": {
        "context_window": 1048576,
        "max_output_tokens": 65536,
        "supports_vision": True,
        "input_modalities": ["text", "image", "audio", "video"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": True,
        "tier": "pro",
    },
    # ── Doubao (ByteDance/Volcengine) ──
    "doubao-seed-2-1-pro-260628": {
        "context_window": 128000,
        "max_output_tokens": 4096,
        "supports_vision": True,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": False,
        "tier": "pro",
    },
    "doubao-1-5-pro-256k-250115": {
        "context_window": 256000,
        "max_output_tokens": 4096,
        "supports_vision": False,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "supports_tool_call": True,
        "supports_reasoning": False,
        "tier": "pro",
    },
}


def get_model_metadata(model_id: str) -> Optional[dict]:
    """
    Get built-in metadata for a model.

    Returns None if model is not in the built-in table.
    Caller should fall back to /v1/models discovery or defaults.
    """
    return MODEL_METADATA.get(model_id)


def enrich_model_config(model_cfg: dict) -> dict:
    """
    Enrich a model config entry with built-in metadata.

    Only fills in fields that are missing — explicit user config
    in config.yaml always wins (layered inheritance).
    """
    model_id = model_cfg.get("model", "")
    meta = get_model_metadata(model_id)
    if not meta:
        return model_cfg

    enriched = dict(model_cfg)  # copy
    # Only fill missing fields
    if "context_window" not in enriched:
        enriched["context_window"] = meta.get("context_window", 128000)
    # P1-2: Ensure both field names are set (backward compatibility)
    if "max_context" not in enriched:
        enriched["max_context"] = enriched.get("context_window", 128000)
    if "max_output_tokens" not in enriched:
        enriched["max_output_tokens"] = meta.get("max_output_tokens", 8192)
    if "multimodal" not in enriched:
        enriched["multimodal"] = meta.get("supports_vision", False)
    if "tier" not in enriched:
        enriched["tier"] = meta.get("tier", "pro")
    if "supports_tool_call" not in enriched:
        enriched["supports_tool_call"] = meta.get("supports_tool_call", False)
    if "supports_reasoning" not in enriched:
        enriched["supports_reasoning"] = meta.get("supports_reasoning", False)
    # v1.9.0: modality fields
    if "input_modalities" not in enriched:
        enriched["input_modalities"] = meta.get("input_modalities", ["text"])
    if "output_modalities" not in enriched:
        enriched["output_modalities"] = meta.get("output_modalities", ["text"])

    return enriched
