"""
Agent Key auto-inheritance for Model Router v1.7.0.

On startup, if config.yaml doesn't exist:
1. Scan environment variables for known API keys
2. Call /v1/models to discover available models
3. Auto-classify (tier, multimodal)
4. Generate config.yaml

Zero-config: if the agent already has API keys set, Router just works.
"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


from model_router.core.security import mask_key as _mask

# Known environment variable -> base_url mapping
KNOWN_KEYS: dict[str, str] = {
    "OPENAI_API_KEY":       "https://api.openai.com/v1",
    "DEEPSEEK_API_KEY":     "https://api.deepseek.com/v1",
    "ANTHROPIC_API_KEY":    "https://api.anthropic.com/v1",
    "GOOGLE_API_KEY":       "https://generativelanguage.googleapis.com/v1beta/openai",
    "GROK_API_KEY":         "https://api.x.ai/v1",
    "MISTRAL_API_KEY":      "https://api.mistral.ai/v1",
    "TOGETHER_API_KEY":     "https://api.together.xyz/v1",
    "DASHSCOPE_API_KEY":    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
}


def scan_env_keys() -> dict[str, str]:
    """
    Scan environment variables for known API keys.

    Returns dict of {env_var_name: api_key} for keys that are set and non-empty.
    """
    found: dict[str, str] = {}
    for env_var, base_url in KNOWN_KEYS.items():
        key = os.environ.get(env_var, "").strip()
        if key:
            found[env_var] = key
            logger.info("Found API key: %s (%s)", env_var, _mask(key))
    return found


def auto_generate_config(
    config_path: str = "config.yaml",
    timeout: float = 30.0,
) -> bool:
    """
    Auto-generate config.yaml from environment variable API keys.

    Returns True if config was generated, False if no keys found or discovery failed.
    """
    path = Path(config_path)
    if path.exists():
        logger.debug("config.yaml already exists — skipping auto-generation")
        return False

    env_keys = scan_env_keys()
    if not env_keys:
        logger.info("No known API keys found in environment — skipping auto-config")
        return False

    # Import discover logic
    from model_router.cli.discover import discover_models, _generate_yaml

    all_models: list[dict] = []
    failed_providers: list[str] = []

    for env_var, api_key in env_keys.items():
        base_url = KNOWN_KEYS[env_var]
        provider = env_var.replace("_API_KEY", "").lower()
        try:
            models = discover_models(base_url, api_key, timeout=timeout)
            all_models.extend(models)
            logger.info(
                "Discovered %d models from %s (%s)",
                len(models), provider, base_url,
            )
        except Exception as exc:
            failed_providers.append(provider)
            logger.warning(
                "Could not discover models from %s (%s): %s",
                provider, base_url, exc,
            )

    if not all_models:
        logger.warning("No models discovered from any provider — config not generated")
        return False

    # Generate YAML
    yaml_content = _generate_yaml(all_models, existing_keys=set())
    if not yaml_content:
        return False

    # Write config
    path.write_text(yaml_content, encoding="utf-8")
    logger.info(
        "Auto-generated %s with %d models from %d provider(s) (%d failed)",
        config_path, len(all_models),
        len(env_keys) - len(failed_providers),
        len(failed_providers),
    )
    return True
