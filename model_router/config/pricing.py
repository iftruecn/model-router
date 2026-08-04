"""
Pricing configuration for model cost tracking (v1.1.0).

Loads per-token pricing from config/pricing.yaml.
Uses PyYAML if available; otherwise falls back to a built-in simple parser
for our flat YAML format (zero new dependencies).

Pricing is per 1K tokens in USD. Unknown models default to 0 (free/unknown).
"""

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YAML loading (PyYAML optional, built-in fallback)
# ---------------------------------------------------------------------------

def _load_yaml_builtin(path: str) -> dict:
    """
    Minimal YAML parser for our pricing format.
    Handles multi-line blocks:
      models:
        model_key:
          input: 0.001
          output: 0.002
          unit: "per_1k_tokens"
    Ignores comments and blank lines.
    """
    result: dict[str, dict[str, float]] = {}
    if not os.path.exists(path):
        return result

    current_model: Optional[str] = None
    current_data: dict[str, float] = {}

    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or stripped == 'models:':
                continue

            # Check indentation level
            indent = len(line) - len(line.lstrip())

            # Model key line (2-space indent): "  model_key:"
            if indent == 2 and stripped.endswith(':') and not stripped.startswith(' '):
                # Save previous model if complete
                if current_model and current_data:
                    result[current_model] = current_data
                current_model = stripped.rstrip(':')
                current_data = {}
                continue

            # Property line (4-space indent): "    input: 0.001"
            if indent >= 4 and current_model and ':' in stripped:
                key, _, value = stripped.partition(':')
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key in ('input', 'output'):
                    try:
                        current_data[key] = float(value)
                    except ValueError:
                        pass

    # Save last model
    if current_model and current_data:
        result[current_model] = current_data

    return result


def _load_pricing_data() -> dict[str, dict[str, float]]:
    """Load pricing from YAML file. Try PyYAML first, then built-in parser."""
    # pricing.yaml lives in project root (not config/)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    yaml_path = os.path.join(project_root, 'pricing.yaml')

    if not os.path.exists(yaml_path):
        logger.warning("pricing.yaml not found at %s, cost tracking disabled", yaml_path)
        return {}

    try:
        import yaml
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        if data and 'models' in data:
            return data['models']
        return {}
    except ImportError:
        logger.debug("PyYAML not installed, using built-in parser for pricing.yaml")
        return _load_yaml_builtin(yaml_path)
    except Exception as exc:
        logger.warning("Failed to load pricing.yaml: %s", exc)
        return {}


# Load once at module import time
_PRICING_DATA: dict[str, dict[str, float]] = _load_pricing_data()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_pricing(model_key: str) -> dict[str, float]:
    """
    Return per-1K-token pricing for a model.

    Returns {"input": float, "output": float}.
    If model is unknown, returns {"input": 0.0, "output": 0.0}.
    """
    # Exact match first
    if model_key in _PRICING_DATA:
        return _PRICING_DATA[model_key]

    # Fuzzy match: check if model_key contains a known pricing key
    # e.g. "openrouter/meta-llama/llama-3.1-405b" matches "llama-3.1-405b"
    for known_key, pricing in _PRICING_DATA.items():
        if known_key in model_key:
            return pricing

    return {"input": 0.0, "output": 0.0}


def calculate_cost(
    model_key: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """
    Calculate the cost of a single API call in USD.

    Returns 0.0 if pricing is unknown for the model.
    """
    pricing = get_pricing(model_key)
    if pricing["input"] == 0.0 and pricing["output"] == 0.0:
        return 0.0

    input_cost = (prompt_tokens / 1000.0) * pricing["input"]
    output_cost = (completion_tokens / 1000.0) * pricing["output"]
    return round(input_cost + output_cost, 8)


def get_baseline_cost(task: str, models_config: dict) -> float:
    """
    Estimate baseline cost for a request (what the most expensive configured
    model would cost per ~500 output + ~200 input tokens).

    This is used as the denominator in cost_score = 1 - cost/baseline.
    A higher baseline makes cost differences more meaningful.

    Returns 0.0 if no pricing info is available.
    """
    max_cost = 0.0
    assumed_output_tokens = 500
    assumed_input_tokens = 200

    for model_key, model_cfg in models_config.items():
        if not model_cfg.get("enabled", True):
            continue
        pricing = get_pricing(model_key)
        if pricing["input"] == 0.0 and pricing["output"] == 0.0:
            continue
        cost = (
            (assumed_input_tokens / 1000.0) * pricing["input"]
            + (assumed_output_tokens / 1000.0) * pricing["output"]
        )
        if cost > max_cost:
            max_cost = cost

    return round(max_cost, 8)
