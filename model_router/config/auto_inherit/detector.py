"""
Agent config file detector for Model Router v1.8.0.

Scans known paths for Agent configuration files and extracts
provider/model information for Router inheritance.
"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Known Agent config paths (priority order)
# P2-16 fix: use Path.home()-based paths instead of hardcoded Windows absolutes
AGENT_CONFIG_PATHS: list[dict] = [
    # Hermes (primary) — cross-platform paths
    {"name": "Hermes", "paths": [
        "~/.hermes/config.yaml",
        "~/.config/hermes/config.yaml",
        str(Path.home() / "HermesData" / "config.yaml"),
    ]},
    # Claude Code
    {"name": "Claude Code", "paths": [
        "~/.claude/config.yaml",
        "~/.claude/settings.yaml",
    ]},
    # Codex
    {"name": "Codex", "paths": [
        "~/.codex/config.yaml",
        "~/.config/codex/config.yaml",
    ]},
    # Open Interpreter
    {"name": "Open Interpreter", "paths": [
        "~/.config/open-interpreter/config.yaml",
    ]},
    # OpenClaw (JSON format)
    {"name": "OpenClaw", "paths": [
        "~/.openclaw/openclaw.runtime.json",
        "~/.config/openclaw/openclaw.runtime.json",
    ], "format": "json"},
]

# Known provider → base_url mapping
PROVIDER_BASE_URLS: dict[str, str] = {
    "openai":       "https://api.openai.com/v1",
    "deepseek":     "https://api.deepseek.com/v1",
    "anthropic":    "https://api.anthropic.com/v1",
    "google":       "https://generativelanguage.googleapis.com/v1beta/openai",
    "grok":         "https://api.x.ai/v1",
    "mistral":      "https://api.mistral.ai/v1",
    "together":     "https://api.together.xyz/v1",
    "dashscope":    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "doubao":       "https://ark.cn-beijing.volces.com/api/v3",
    "volcengine":   "https://ark.cn-beijing.volces.com/api/v3",
    "ark":          "https://ark.cn-beijing.volces.com/api/v3",
}


def discover_agent_config(
    custom_path: Optional[str] = None,
) -> Optional[dict]:
    """
    Discover and load Agent configuration file.

    Priority:
    1. MODEL_ROUTER_AGENT_CONFIG env var (custom path)
    2. Known Agent config paths (scanned in order)

    Returns parsed config dict, or None if not found.
    """
    # 1. Custom path from env var
    custom = custom_path or os.environ.get("MODEL_ROUTER_AGENT_CONFIG", "")
    if custom:
        path = Path(custom).expanduser()
        if path.exists():
            logger.info("Agent config from env: %s", path)
            return _load_yaml_safe(path)
        logger.warning("MODEL_ROUTER_AGENT_CONFIG path not found: %s", path)

    # 2. Scan known paths
    for agent_info in AGENT_CONFIG_PATHS:
        agent_name = agent_info["name"]
        agent_fmt = agent_info.get("format", "yaml")
        for p in agent_info["paths"]:
            path = Path(p).expanduser()
            if path.exists():
                logger.info(
                    "Found %s config at: %s", agent_name, path,
                )
                config = _load_yaml_safe(path, fmt=agent_fmt)
                if config:
                    # R3: Log if other agents were also found
                    logger.info(
                        "Using %s config (first match, priority order). "
                        "Set MODEL_ROUTER_AGENT_CONFIG to override.",
                        agent_name,
                    )
                    return config

    logger.info("No Agent config found in known paths")
    return None


def _load_yaml_safe(path: Path, fmt: str = "yaml") -> Optional[dict]:
    """Load YAML or JSON config with fallback parser.
    P1-15: validate return type — non-dict results are rejected with a warning.
    """
    try:
        text = path.read_text(encoding="utf-8")
        if fmt == "json" or path.suffix == ".json":
            import json
            data = json.loads(text)
            if not isinstance(data, dict):
                logger.warning("Config %s root is not a dict (got %s)", path, type(data).__name__)
                return None
            return data
        try:
            import yaml
            data = yaml.safe_load(text)
            if not isinstance(data, dict):
                logger.warning("Config %s root is not a dict (got %s)", path, type(data).__name__)
                return None
            return data
        except ImportError:
            from model_router.config.validator import _simple_yaml_load
            return _simple_yaml_load(str(path))
    except Exception as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return None


def parse_agent_providers(config: dict) -> dict[str, dict]:
    """
    Extract provider configurations from Agent config.

    Supports:
    - Hermes: providers.<name> + custom_providers[].models.<id>.context_length
    - Standard: providers.<name>.api_key + base_url

    Returns: {provider_name: {api_key, base_url, models: [...], model_meta: {id: {context_length, ...}}}}
    """
    providers = {}
    raw_providers = config.get("providers", {})

    for name, cfg in raw_providers.items():
        if not isinstance(cfg, dict):
            continue
        api_key = cfg.get("api_key", "")
        if not api_key:
            continue

        base_url = cfg.get(
            "base_url",
            PROVIDER_BASE_URLS.get(name.lower(), ""),
        )

        # Extract model list from various config formats
        models = _extract_models(config, name)

        providers[name] = {
            "api_key": api_key,
            "base_url": base_url,
            "models": models,
        }

    # Extract custom_providers (Hermes) — these have context_length per model
    custom_providers = config.get("custom_providers", [])
    if isinstance(custom_providers, list):
        for cp in custom_providers:
            if not isinstance(cp, dict):
                continue
            cp_name = cp.get("name", "")
            cp_key = cp.get("api_key", "") or cp.get("apiKey", "")
            cp_url = cp.get("base_url", "") or cp.get("baseUrl", "")
            if not cp_key:
                continue

            # Use name as key, or derive from URL
            prov_name = cp_name if cp_name else cp_url.split("/")[2] if cp_url else "unknown"

            # Extract models with metadata (context_length, etc.)
            cp_models_dict = cp.get("models", {})
            model_ids = []
            model_meta = {}
            if isinstance(cp_models_dict, dict):
                for mid, mcfg in cp_models_dict.items():
                    if not isinstance(mcfg, dict):
                        continue
                    model_ids.append(mid)
                    meta = {}
                    ctx = mcfg.get("context_length") or mcfg.get("contextWindow")
                    if ctx and isinstance(ctx, int) and ctx > 0:
                        meta["context_length"] = ctx
                    max_tok = mcfg.get("max_output_tokens") or mcfg.get("maxTokens")
                    if max_tok and isinstance(max_tok, int) and max_tok > 0:
                        meta["max_output_tokens"] = max_tok
                    if meta:
                        model_meta[mid] = meta

            # Merge with existing provider or create new
            if prov_name in providers:
                # Merge models (avoid duplicates)
                for mid in model_ids:
                    if mid not in providers[prov_name]["models"]:
                        providers[prov_name]["models"].append(mid)
                providers[prov_name].setdefault("model_meta", {}).update(model_meta)
            else:
                providers[prov_name] = {
                    "api_key": cp_key,
                    "base_url": cp_url or PROVIDER_BASE_URLS.get(prov_name.lower(), ""),
                    "models": model_ids,
                    "model_meta": model_meta,
                }

    return providers


def _extract_models(config: dict, provider_name: str) -> list[str]:
    """Extract model list for a provider from Agent config."""
    import json
    models = []

    # Format 1: moa.reference_models (JSON string)
    moa = config.get("moa", {})
    ref_str = moa.get("reference_models", "")
    if isinstance(ref_str, str) and ref_str:
        try:
            ref_models = json.loads(ref_str)
            for m in ref_models:
                if m.get("provider") == provider_name:
                    models.append(m.get("model", ""))
        except (json.JSONDecodeError, TypeError):
            pass

    # Format 2: moa.presets.*.reference_models
    presets = moa.get("presets", {})
    for preset_name, preset_cfg in presets.items():
        if not isinstance(preset_cfg, dict):
            continue
        ref_str2 = preset_cfg.get("reference_models", "")
        if isinstance(ref_str2, str) and ref_str2:
            try:
                ref_models2 = json.loads(ref_str2)
                for m in ref_models2:
                    if m.get("provider") == provider_name:
                        mid = m.get("model", "")
                        if mid and mid not in models:
                            models.append(mid)
            except (json.JSONDecodeError, TypeError):
                pass

    # Format 3: moa.aggregator
    agg = moa.get("aggregator", {})
    if isinstance(agg, dict) and agg.get("provider") == provider_name:
        mid = agg.get("model", "")
        if mid and mid not in models:
            models.append(mid)

    return [m for m in models if m]


def build_models_from_agent(config: dict) -> dict[str, dict]:
    """
    Build Router models_config from Agent config.

    Supports:
    - Hermes format (providers + custom_providers + moa)
    - OpenClaw format (models.providers.<key>)

    Returns models_config dict ready for Router use.
    """
    # Try OpenClaw format first (has distinct structure)
    if _is_openclaw_config(config):
        models = _build_from_openclaw(config)
        if models:
            return models

    # Hermes / standard format
    providers = parse_agent_providers(config)
    if not providers:
        return {}

    from model_router.config.auto_inherit.classifier import (
        classify_tier, detect_multimodal,
    )
    from model_router.config.model_metadata import enrich_model_config

    models_config = {}
    for provider_name, prov_cfg in providers.items():
        model_meta = prov_cfg.get("model_meta", {})
        for model_id in prov_cfg["models"]:
            # Generate clean config key
            key = model_id.replace("/", "-").replace(":", "-").lower()

            model_cfg = {
                "name": model_id,
                "base_url": prov_cfg["base_url"],
                "api_key": prov_cfg["api_key"],
                "model": model_id,
                "provider": provider_name,
            }

            # P0-2: Extract context_length from Agent config BEFORE enrichment
            meta = model_meta.get(model_id, {})
            if "context_length" in meta:
                model_cfg["context_window"] = meta["context_length"]
                model_cfg["max_context"] = meta["context_length"]
            if "max_output_tokens" in meta:
                model_cfg["max_output_tokens"] = meta["max_output_tokens"]

            # Auto-classify tier and multimodal
            model_cfg["tier"] = classify_tier(model_id)
            model_cfg["multimodal"] = detect_multimodal(model_id)
            model_cfg["selection_mode"] = "auto"

            # Enrich with built-in metadata (only fills MISSING fields)
            model_cfg = enrich_model_config(model_cfg)

            models_config[key] = model_cfg
            logger.info(
                "Inherited model: %s (provider=%s, tier=%s, ctx=%s)",
                key, provider_name, model_cfg.get("tier"),
                model_cfg.get("context_window", "?"),
            )

    return models_config


# ── OpenClaw format support ──

def _is_openclaw_config(config: dict) -> bool:
    """Detect OpenClaw config format."""
    # OpenClaw uses models.providers.<key> structure
    models = config.get("models", {})
    if isinstance(models, dict) and "providers" in models:
        return True
    return False


def _build_from_openclaw(config: dict) -> dict[str, dict]:
    """
    Build Router models_config from OpenClaw format.

    OpenClaw structure:
      models.providers.<key>.apiKey / baseUrl / models[]
      Each model: {id, contextWindow, maxTokens, reasoning}
    """
    from model_router.config.auto_inherit.classifier import (
        classify_tier, detect_multimodal,
    )
    from model_router.config.model_metadata import enrich_model_config

    models_section = config.get("models", {})
    providers_section = models_section.get("providers", {})
    if not isinstance(providers_section, dict):
        return {}

    models_config = {}
    for prov_key, prov_cfg in providers_section.items():
        if not isinstance(prov_cfg, dict):
            continue
        api_key = prov_cfg.get("apiKey", "") or prov_cfg.get("api_key", "")
        base_url = prov_cfg.get("baseUrl", "") or prov_cfg.get("base_url", "")
        if not api_key or not base_url:
            continue

        # Normalize base_url (ensure /v1 suffix)
        if not base_url.rstrip("/").endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"

        raw_models = prov_cfg.get("models", [])
        if isinstance(raw_models, list):
            model_list = raw_models
        elif isinstance(raw_models, dict):
            # Some OpenClaw versions use dict format
            model_list = [{"id": k, **v} for k, v in raw_models.items() if isinstance(v, dict)]
        else:
            continue

        for model_entry in model_list:
            if not isinstance(model_entry, dict):
                continue
            model_id = model_entry.get("id", "") or model_entry.get("model", "")
            if not model_id:
                continue

            key = model_id.replace("/", "-").replace(":", "-").lower()
            model_cfg = {
                "name": model_entry.get("name", model_id),
                "base_url": base_url,
                "api_key": api_key,
                "model": model_id,
                "provider": prov_key,
            }

            # Extract context_length / contextWindow from OpenClaw
            ctx = model_entry.get("contextWindow") or model_entry.get("context_length")
            if ctx and isinstance(ctx, int) and ctx > 0:
                model_cfg["context_window"] = ctx
                model_cfg["max_context"] = ctx

            # Extract maxTokens / max_output_tokens
            max_tok = model_entry.get("maxTokens") or model_entry.get("max_output_tokens")
            if max_tok and isinstance(max_tok, int) and max_tok > 0:
                model_cfg["max_output_tokens"] = max_tok

            # Auto-classify
            model_cfg["tier"] = classify_tier(model_id)
            model_cfg["multimodal"] = detect_multimodal(model_id)
            model_cfg["selection_mode"] = "auto"

            # Enrich with built-in metadata (only fills missing fields)
            model_cfg = enrich_model_config(model_cfg)

            models_config[key] = model_cfg
            logger.info(
                "OpenClaw: inherited %s (provider=%s, tier=%s, ctx=%s)",
                key, prov_key, model_cfg.get("tier"),
                model_cfg.get("context_window", "?"),
            )

    return models_config
