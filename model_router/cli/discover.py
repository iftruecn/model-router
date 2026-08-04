"""
Model auto-discovery CLI for Model Router.

Given a base_url + api_key, discovers all models available at that
OpenAI-compatible endpoint, auto-classifies them, and generates
config.yaml entries.

Usage:
    model-router discover --base-url https://api.deepseek.com/v1 --api-key sk-xxx
    model-router discover --base-url https://api.openai.com/v1 --api-key sk-xxx --output config.yaml
"""

import sys
from pathlib import Path
from typing import Optional

import httpx
import yaml

from model_router.locales.i18n import init_language, t

# ANSI colors (same as setup.py)
class C:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    RESET = "\033[0m"

# Tier classification keywords
_FLASH_KEYWORDS = ("flash", "lite", "turbo", "mini", "nano", "fast", "haiku")
# Multimodal detection keywords
_MULTIMODAL_KEYWORDS = ("vision", "vl", "gemini", "claude", "gpt-4o", "gpt-4v", "grok")


def _classify_tier(model_id: str) -> str:
    """Classify model into tier based on name heuristics."""
    name_lower = model_id.lower()
    # Split by hyphens, slashes, dots to avoid substring matches
    # (e.g., "gemini" contains "mini" but should NOT be flash)
    parts = set(name_lower.replace("/", "-").replace(".", "-").split("-"))
    for kw in _FLASH_KEYWORDS:
        if kw in parts:
            return "flash"
    return "pro"


def _detect_multimodal(model_id: str) -> bool:
    """Detect if model likely supports multimodal input.
    
    P2-4 fix: use part-based matching to avoid false positives
    (e.g. "text-gemini-classifier" should not match "gemini").
    """
    name_lower = model_id.lower()
    parts = set(name_lower.replace("/", "-").replace(".", "-").split("-"))
    for kw in _MULTIMODAL_KEYWORDS:
        if kw in parts:
            return True
    # Also match compound patterns like "gpt-4o-mini" (gpt-4o is in parts)
    for kw in _MULTIMODAL_KEYWORDS:
        if "-" in kw and kw in name_lower:
            return True
    return False


def _make_config_key(model_id: str) -> str:
    """Generate a clean config key from model id."""
    return model_id.replace("/", "-").replace(":", "-").lower()


def discover_models(
    base_url: str,
    api_key: str,
    timeout: float = 30.0,
) -> list[dict]:
    """
    Call GET /v1/models and return classified model list.

    Each entry: {id, key, name, tier, multimodal, base_url, api_key}
    """
    url = f"{base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    models_raw = data if isinstance(data, list) else data.get("data", [])

    results = []
    for m in models_raw:
        model_id = m.get("id", "")
        if not model_id:
            continue

        tier = _classify_tier(model_id)
        multimodal = _detect_multimodal(model_id)
        key = _make_config_key(model_id)

        results.append({
            "id": model_id,
            "key": key,
            "name": model_id,
            "tier": tier,
            "multimodal": multimodal,
            "base_url": base_url.rstrip("/"),
            "api_key": api_key,
        })

    return results


def _print_table(models: list[dict]) -> None:
    """Print a nice discovery table."""
    auto_word = "auto"
    manual_word = "manual"

    print(f"\n{C.BOLD}Discovered {len(models)} models:{C.RESET}")
    print(f"{'─' * 70}")
    print(f"  {'Model':<40} {'Tier':<8} {'Vision':<8}")
    print(f"{'─' * 70}")

    for m in models:
        tier_color = C.GREEN if m["tier"] == "flash" else C.CYAN
        vision = f"{C.GREEN}yes{C.RESET}" if m["multimodal"] else f"{C.DIM}no{C.RESET}"
        print(f"  {m['id']:<40} {tier_color}{m['tier']:<8}{C.RESET} {vision}")

    print(f"{'─' * 70}")
    flash_count = sum(1 for m in models if m["tier"] == "flash")
    pro_count = len(models) - flash_count
    mm_count = sum(1 for m in models if m["multimodal"])
    print(f"  {C.GREEN}{flash_count} flash{C.RESET} | {C.CYAN}{pro_count} pro{C.RESET} | {mm_count} multimodal")
    print()


def _generate_yaml(models: list[dict], existing_keys: set) -> str:
    """Generate config.yaml content from discovered models.
    
    P2-12 fix: also generate fallback_chain section for resilience.
    """
    models_section = {}
    for m in models:
        if m["key"] in existing_keys:
            continue
        models_section[m["key"]] = {
            "name": m["name"],
            "base_url": m["base_url"],
            "api_key": m["api_key"],
            "model": m["id"],
            "tier": m["tier"],
            "multimodal": m["multimodal"],
            "selection_mode": "auto",
        }

    if not models_section:
        return ""

    # P2-12: generate fallback_chain — each model falls back to next same-tier model
    fallback_chain = {}
    model_keys = list(models_section.keys())
    for i, key in enumerate(model_keys):
        tier = models_section[key].get("tier", "pro")
        # Find next model of same tier as fallback
        for j in range(i + 1, min(i + 4, len(model_keys))):
            next_key = model_keys[j]
            if models_section[next_key].get("tier", "pro") == tier:
                fallback_chain[key] = [next_key]
                break

    config = {"models": models_section}
    if fallback_chain:
        config["fallback_chain"] = fallback_chain

    return yaml.dump(
        config,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def main() -> None:
    """CLI entry point for model discovery."""
    args = sys.argv[1:]

    # Parse --lang
    lang = None
    for i, arg in enumerate(args):
        if arg == "--lang" and i + 1 < len(args):
            lang = args[i + 1]
    init_language(lang)

    # Parse options
    base_url = None
    api_key = None
    output_path = "config.yaml"

    for i, arg in enumerate(args):
        if arg in ("--base-url", "-u") and i + 1 < len(args):
            base_url = args[i + 1]
        elif arg in ("--api-key", "-k") and i + 1 < len(args):
            api_key = args[i + 1]
        elif arg in ("--output", "-o") and i + 1 < len(args):
            output_path = args[i + 1]

    if not base_url or not api_key:
        print(f"{C.YELLOW}Usage:{C.RESET}")
        print(f"  model-router discover --base-url URL --api-key KEY")
        print(f"  model-router discover -u https://api.deepseek.com/v1 -k sk-xxx")
        print()
        print(f"{C.DIM}Options:{C.RESET}")
        print(f"  --base-url, -u   OpenAI-compatible API base URL")
        print(f"  --api-key, -k    API key for authentication")
        print(f"  --output, -o     Output config file (default: config.yaml)")
        sys.exit(1)

    print(f"\n{C.BOLD}Discovering models at {base_url}...{C.RESET}\n")

    try:
        models = discover_models(base_url, api_key)
    except httpx.HTTPStatusError as e:
        print(f"{C.RED}Error: HTTP {e.response.status_code}{C.RESET}")
        print(f"Check your base_url and api_key.")
        sys.exit(1)
    except httpx.ConnectError:
        print(f"{C.RED}Error: Cannot connect to {base_url}{C.RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"{C.RED}Error: {e}{C.RESET}")
        sys.exit(1)

    if not models:
        print(f"{C.YELLOW}No models found at this endpoint.{C.RESET}")
        sys.exit(0)

    _print_table(models)

    # Load existing config to avoid overwriting
    config_path = Path(output_path)
    existing_keys = set()
    if config_path.exists():
        try:
            existing = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            existing_keys = set(existing.get("models", {}).keys())
        except Exception:
            pass

    # Filter out already-configured models
    new_models = [m for m in models if m["key"] not in existing_keys]
    skipped = len(models) - len(new_models)

    if skipped > 0:
        print(f"{C.DIM}Skipped {skipped} already-configured model(s).{C.RESET}")

    if not new_models:
        print(f"{C.YELLOW}No new models to add.{C.RESET}")
        sys.exit(0)

    # Generate and write YAML
    yaml_content = _generate_yaml(models, existing_keys)
    if not yaml_content:
        sys.exit(0)

    if config_path.exists():
        # Append to existing config
        print(f"{C.CYAN}Appending {len(new_models)} new model(s) to {output_path}{C.RESET}")
        with open(config_path, "a", encoding="utf-8") as f:
            f.write("\n")
            f.write(yaml_content)
    else:
        # Create new config
        print(f"{C.GREEN}Creating {output_path} with {len(new_models)} model(s){C.RESET}")
        config_path.write_text(yaml_content, encoding="utf-8")

    print(f"{C.GREEN}Done! Run 'model-router serve' to start routing.{C.RESET}")


if __name__ == "__main__":
    main()
