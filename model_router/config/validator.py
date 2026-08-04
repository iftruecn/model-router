"""
Configuration validation for Model Router (v1.6.1).

Pure-Python config validator using dataclasses.
No pydantic, no external dependencies.

Validates:
- YAML structure (models section, fallback_chain section)
- Required fields per model (base_url, api_key, model)
- Field types and allowed values
- Fallback chain references valid models
- URL format (must start with http:// or https://)

Usage:
    from model_router.config.validator import validate_config
    errors, warnings = validate_config(config_dict)

CLI:
    python -m model_router.config.validator config.yaml
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Valid values for enum-like fields
_VALID_TIERS = {"flash", "pro"}
_VALID_COSTS = {"low", "medium", "high"}
_VALID_SPEEDS = {"fast", "medium", "slow"}

# Required fields for each model entry
_REQUIRED_MODEL_FIELDS = {"base_url", "api_key", "model"}

# All known model fields (to detect typos)
_KNOWN_MODEL_FIELDS = {
    "name", "base_url", "api_key", "model", "tier", "multimodal",
    "cost", "speed", "enabled", "selection_mode", "capabilities",
    "vision", "max_tokens", "temperature",
}


@dataclass
class ValidationError:
    """A single config validation error."""
    path: str       # e.g. "models.gpt-4o.base_url"
    message: str    # human-readable error description
    severity: str = "error"  # error | warning

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.path}: {self.message}"


@dataclass
class ValidationResult:
    """Result of config validation."""
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        n_err = len(self.errors)
        n_warn = len(self.warnings)
        if self.is_valid:
            return f"Config valid ({n_warn} warnings)"
        return f"Config INVALID ({n_err} errors, {n_warn} warnings)"

    def to_dict(self) -> dict:
        return {
            "valid": self.is_valid,
            "errors": [str(e) for e in self.errors],
            "warnings": [str(w) for w in self.warnings],
            "summary": self.summary(),
        }


def validate_config(config: dict) -> ValidationResult:
    """
    Validate a Model Router config dict (parsed from YAML).

    Returns ValidationResult with errors and warnings.
    """
    result = ValidationResult()

    if not isinstance(config, dict):
        result.errors.append(ValidationError(
            path="(root)", message="Config must be a YAML mapping (dict)"
        ))
        return result

    # Top-level sections
    models = config.get("models")
    fallback_chain = config.get("fallback_chain")

    # Must have at least models or fallback_chain
    if models is None and fallback_chain is None:
        result.errors.append(ValidationError(
            path="(root)",
            message="Config must have at least 'models' or 'fallback_chain' section",
        ))
        return result

    # Validate models section
    model_ids: set[str] = set()
    if models is not None:
        _validate_models_section(models, model_ids, result)

    # Validate fallback_chain section
    if fallback_chain is not None:
        _validate_fallback_section(fallback_chain, model_ids, result)

    # Warn about unknown top-level keys
    known_top = {"models", "fallback_chain"}
    for key in config:
        if key not in known_top:
            result.warnings.append(ValidationError(
                path=key,
                message=f"Unknown top-level key '{key}' (expected: models, fallback_chain)",
                severity="warning",
            ))

    return result


def _validate_models_section(
    models: dict,
    model_ids: set[str],
    result: ValidationResult,
) -> None:
    """Validate the 'models' section of the config."""
    if not isinstance(models, dict):
        result.errors.append(ValidationError(
            path="models", message="'models' must be a mapping"
        ))
        return

    if len(models) == 0:
        result.warnings.append(ValidationError(
            path="models", message="No models defined", severity="warning"
        ))
        return

    for model_id, model_cfg in models.items():
        prefix = f"models.{model_id}"

        if not isinstance(model_cfg, dict):
            result.errors.append(ValidationError(
                path=prefix, message="Model config must be a mapping"
            ))
            continue

        model_ids.add(model_id)

        # Required fields
        for req in _REQUIRED_MODEL_FIELDS:
            if req not in model_cfg:
                result.errors.append(ValidationError(
                    path=f"{prefix}.{req}",
                    message=f"Required field '{req}' is missing",
                ))

        # Check for placeholder API keys
        api_key = model_cfg.get("api_key", "")
        if isinstance(api_key, str) and (
            api_key.startswith("sk-your-") or
            api_key.startswith("your-") or
            api_key == "" or
            "placeholder" in api_key.lower()
        ):
            result.warnings.append(ValidationError(
                path=f"{prefix}.api_key",
                message="API key looks like a placeholder — model won't work until configured",
                severity="warning",
            ))

        # Validate base_url format
        base_url = model_cfg.get("base_url", "")
        if isinstance(base_url, str) and base_url:
            parsed = urlparse(base_url)
            if parsed.scheme not in ("http", "https"):
                result.errors.append(ValidationError(
                    path=f"{prefix}.base_url",
                    message=f"Invalid URL scheme '{parsed.scheme}' (expected http or https)",
                ))

        # Validate enum fields
        tier = model_cfg.get("tier")
        if tier is not None and tier not in _VALID_TIERS:
            result.errors.append(ValidationError(
                path=f"{prefix}.tier",
                message=f"Invalid tier '{tier}' (expected: {', '.join(sorted(_VALID_TIERS))})",
            ))

        cost = model_cfg.get("cost")
        if cost is not None and cost not in _VALID_COSTS:
            result.errors.append(ValidationError(
                path=f"{prefix}.cost",
                message=f"Invalid cost '{cost}' (expected: {', '.join(sorted(_VALID_COSTS))})",
            ))

        speed = model_cfg.get("speed")
        if speed is not None and speed not in _VALID_SPEEDS:
            result.errors.append(ValidationError(
                path=f"{prefix}.speed",
                message=f"Invalid speed '{speed}' (expected: {', '.join(sorted(_VALID_SPEEDS))})",
            ))

        # Validate multimodal is boolean
        multimodal = model_cfg.get("multimodal")
        if multimodal is not None and not isinstance(multimodal, bool):
            result.warnings.append(ValidationError(
                path=f"{prefix}.multimodal",
                message=f"'multimodal' should be true/false, got {type(multimodal).__name__}",
                severity="warning",
            ))

        # Warn about unknown fields
        for key in model_cfg:
            if key not in _KNOWN_MODEL_FIELDS:
                result.warnings.append(ValidationError(
                    path=f"{prefix}.{key}",
                    message=f"Unknown field '{key}'",
                    severity="warning",
                ))


def _validate_fallback_section(
    fallback: dict,
    model_ids: set[str],
    result: ValidationResult,
) -> None:
    """Validate the 'fallback_chain' section."""
    if not isinstance(fallback, dict):
        result.errors.append(ValidationError(
            path="fallback_chain", message="'fallback_chain' must be a mapping"
        ))
        return

    for source, targets in fallback.items():
        prefix = f"fallback_chain.{source}"

        if not isinstance(targets, list):
            result.errors.append(ValidationError(
                path=prefix, message="Fallback targets must be a list"
            ))
            continue

        # Source model should exist in models section (if models defined)
        if model_ids and source not in model_ids:
            result.warnings.append(ValidationError(
                path=prefix,
                message=f"Source model '{source}' not in models section",
                severity="warning",
            ))

        for target in targets:
            if not isinstance(target, str):
                result.errors.append(ValidationError(
                    path=prefix,
                    message=f"Fallback target must be a string, got {type(target).__name__}",
                ))
            elif model_ids and target not in model_ids:
                result.warnings.append(ValidationError(
                    path=f"{prefix}.{target}",
                    message=f"Fallback target '{target}' not in models section",
                    severity="warning",
                ))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _load_yaml_file(path: str) -> dict:
    """Load YAML file. Try PyYAML first, then built-in parser."""
    try:
        import yaml
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        pass

    # Built-in minimal YAML loader (handles our config format)
    from model_router.config.pricing import _load_yaml_builtin
    # For config.yaml we need a more complete parser
    # Use a simple approach: try to parse key-value pairs
    return _simple_yaml_load(path)


def _simple_yaml_load(path: str) -> dict:
    """Very basic YAML loader for config validation (handles nested mappings + lists)."""
    import json

    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Remove comments and blank lines, track indentation
    result: dict = {}
    stack: list[tuple[int, dict]] = [(-1, result)]
    # P2-10 fix: track last key explicitly instead of relying on dict order
    pending_list_key: Optional[str] = None
    pending_list_indent: int = -1

    for line in lines:
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith('#'):
            continue

        indent = len(line) - len(line.lstrip())
        content = stripped.lstrip()

        # Pop stack to find parent
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
            pending_list_key = None  # reset on stack pop

        parent = stack[-1][1]

        if ':' in content and not content.startswith('- '):
            key, _, value = content.partition(':')
            key = key.strip().strip('"').strip("'")
            value = value.strip()

            if value == '' or value.startswith('#'):
                # Nested mapping — could be dict or list (determined by next line)
                new_dict: dict = {}
                parent[key] = new_dict
                stack.append((indent, new_dict))
                pending_list_key = key
                pending_list_indent = indent
            else:
                # Scalar value
                value = value.strip('"').strip("'")
                # Type coercion
                if value.lower() == 'true':
                    value = True
                elif value.lower() == 'false':
                    value = False
                else:
                    try:
                        value = int(value)
                    except ValueError:
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                parent[key] = value
                pending_list_key = None

        elif content.startswith('- '):
            # List item
            item = content[2:].strip().strip('"').strip("'")
            # Use tracked key if at correct indent level
            if pending_list_key and indent > pending_list_indent:
                if not isinstance(parent.get(pending_list_key), list):
                    parent[pending_list_key] = []
                parent[pending_list_key].append(item)
            elif isinstance(parent, dict):
                # Fallback: find last key (old behavior)
                last_key = list(parent.keys())[-1] if parent else None
                if last_key and not isinstance(parent[last_key], list):
                    parent[last_key] = []
                if last_key:
                    parent[last_key].append(item)

    return result


def main():
    """CLI entry point: python -m model_router.config.validator <config.yaml>"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m model_router.config.validator <config.yaml>")
        print("       Validates a Model Router config file.")
        sys.exit(1)

    path = sys.argv[1]

    try:
        config = _load_yaml_file(path)
    except FileNotFoundError:
        print(f"Error: File not found: {path}")
        sys.exit(1)
    except Exception as exc:
        print(f"Error loading {path}: {exc}")
        sys.exit(1)

    result = validate_config(config)

    # Print results
    for err in result.errors:
        print(f"  {err}")
    for warn in result.warnings:
        print(f"  {warn}")

    print(f"\n{result.summary()}")

    if not result.is_valid:
        sys.exit(1)


if __name__ == "__main__":
    main()
