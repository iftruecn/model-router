"""
Interactive CLI setup wizard for Model Router.

Lets users configure model selection modes (auto/manual) without
manually editing config files.

Multilingual: Supports EN, ZH, JA, KO, ES, FR, DE.

Usage:
    model-router setup              # Interactive wizard
    model-router setup --quick      # Quick auto-detect mode
    model-router setup --list       # Show current config
    model-router setup --lang zh    # Force Chinese
"""

import json
import sys
from pathlib import Path
from typing import Optional

import yaml

from model_router.locales.i18n import (
    init_language,
    t,
    get_language,
    set_language,
    SUPPORTED_LANGUAGES,
    LANGUAGE_NAMES,
)


# ANSI colors for terminal
class C:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    BLUE = "\033[34m"
    RESET = "\033[0m"


def _input_colored(prompt: str, color: str = C.CYAN) -> str:
    """Print colored prompt and get input."""
    try:
        return input(f"{color}{prompt}{C.RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def _confirm(prompt: str, default: bool = True) -> bool:
    """Yes/No confirmation with i18n."""
    yes_word = t("common.yes")
    no_word = t("common.no")
    suffix = f" [{yes_word[0].upper()}/{no_word[0].lower()}] " if default else f" [{yes_word[0].lower()}/{no_word[0].upper()}] "
    answer = _input_colored(prompt + suffix, C.YELLOW)
    if not answer:
        return default
    return answer.lower() in (yes_word.lower(), no_word.lower(), "y", "yes") or (
        default and answer.lower() == yes_word[0].lower()
    )


def _select_from_list(
    title: str,
    options: list[dict],
    multi: bool = True,
) -> list[str]:
    """
    Display a numbered list and let user select.

    Args:
        title: Header text
        options: List of {"id": str, "label": str, "hint": str}
        multi: If True, allow multiple selections

    Returns:
        List of selected option IDs
    """
    print(f"\n{C.BOLD}{C.BLUE}{title}{C.RESET}")
    print(f"{C.DIM}{'---' * 20}{C.RESET}")

    for i, opt in enumerate(options, 1):
        hint = f" {C.DIM}({opt.get('hint', '')}){C.RESET}" if opt.get("hint") else ""
        print(f"  {C.BOLD}{i}{C.RESET}. {opt['label']}{hint}")

    print()

    if multi:
        raw = _input_colored(t("setup.select_hint"), C.YELLOW)
        if raw.lower() == "all":
            return [opt["id"] for opt in options]
        if raw.lower() == "none" or raw == "":
            return []

        selected = []
        for part in raw.replace(" ", "").split(","):
            try:
                idx = int(part) - 1
                if 0 <= idx < len(options):
                    selected.append(options[idx]["id"])
            except ValueError:
                pass
        return selected
    else:
        raw = _input_colored(t("setup.select_hint"), C.YELLOW)
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return [options[idx]["id"]]
        except ValueError:
            pass
        return []


def _print_banner() -> None:
    """Print setup wizard banner."""
    print()
    print(f"{C.GREEN}{C.BOLD}{'=' * 56}{C.RESET}")
    print(f"{C.GREEN}{C.BOLD}  {t('setup.welcome')}{C.RESET}")
    print(f"{C.GREEN}{C.BOLD}{'=' * 56}{C.RESET}")
    print()
    print(f"  {C.DIM}{t('setup.description')}{C.RESET}")
    print()


def _load_config(config_path: Path) -> dict:
    """Load existing config or return empty dict."""
    if config_path.exists():
        try:
            return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"{C.RED}Warning: Could not load {config_path}: {e}{C.RESET}")
    return {}


def _save_config(config_path: Path, config: dict) -> None:
    """Save config to YAML file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(
        config,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    config_path.write_text(content, encoding="utf-8")
    print(f"\n{C.GREEN}{t('setup.saved', path=str(config_path))}{C.RESET}")


def _detect_expensive_models(models: list[dict]) -> list[str]:
    """Auto-detect potentially expensive models (vision/video/image gen)."""
    expensive_keywords = [
        "dall-e", "sora", "midjourney", "stable-diffusion",
        "gpt-4-vision", "gemini-pro-vision",
        "o1", "o3",  # reasoning models are expensive
    ]
    detected = []
    for m in models:
        model_id = m.get("id", "").lower()
        for kw in expensive_keywords:
            if kw in model_id:
                detected.append(m["id"])
                break
    return detected


def setup_wizard(config_path: Optional[str] = None) -> None:
    """Run the full interactive setup wizard."""
    _print_banner()

    # Step 1: Find config file
    if config_path:
        path = Path(config_path)
    else:
        default_path = Path("config.yaml")
        raw = _input_colored(
            f"{t('setup.config_path')} [{default_path}]",
            C.CYAN,
        )
        path = Path(raw) if raw else default_path

    config = _load_config(path)
    models = config.get("models", {})

    if not models:
        print(f"\n{C.YELLOW}{t('setup.no_models')}{C.RESET}")
        return

    # Step 2: Build model list
    auto_word = t("common.auto")
    manual_word = t("common.manual")
    model_options = []
    for key, cfg in models.items():
        model_id = cfg.get("model", key)
        name = cfg.get("name", key)
        current_mode = cfg.get("selection_mode", "auto")
        cost_hint = ""
        if cfg.get("cost_per_1k_input", 0) > 0.01:
            cost_hint = f"${cfg['cost_per_1k_input']:.3f}/1k"

        mode_display = f"{C.GREEN}{auto_word}{C.RESET}" if current_mode == "auto" else f"{C.RED}{manual_word}{C.RESET}"
        label = f"{name} [{model_id}] — {mode_display}"
        if cost_hint:
            label += f" {C.DIM}{cost_hint}{C.RESET}"

        model_options.append({
            "id": key,
            "label": label,
            "hint": f"{t('setup.current_mode')}: {current_mode}",
        })

    # Step 3: Ask which models should be manual-only
    selected_manual = _select_from_list(
        t("setup.select_manual"),
        model_options,
        multi=True,
    )
    print(f"\n{C.DIM}{t('setup.selected_manual', count=len(selected_manual))}{C.RESET}")

    # Step 4: Confirm auto-detect for expensive models
    expensive = _detect_expensive_models(
        [{"id": k, **v} for k, v in models.items()]
    )
    if expensive:
        print(f"\n{C.YELLOW}{t('setup.expensive_detected')}:{C.RESET}")
        for m in expensive:
            print(f"  - {m}")
        if _confirm(t("setup.mark_expensive"), default=False):
            selected_manual = list(set(selected_manual + expensive))

    # Step 5: Apply changes
    for key in models:
        if key in selected_manual:
            models[key]["selection_mode"] = "manual"
        else:
            models[key].setdefault("selection_mode", "auto")

    config["models"] = models

    # Step 6: Preview
    print(f"\n{C.BOLD}{t('setup.preview')}:{C.RESET}")
    print(f"{'─' * 50}")
    for key, cfg in models.items():
        mode = cfg.get("selection_mode", "auto")
        icon = f"{C.GREEN}[{auto_word}]{C.RESET}" if mode == "auto" else f"{C.RED}[{manual_word}]{C.RESET}"
        print(f"  {icon} {key}")
    print(f"{'─' * 50}")

    if _confirm(t("setup.confirm_save")):
        _save_config(path, config)
        print(f"\n{C.GREEN}{t('setup.complete')}{C.RESET}")
        print(f"\n{C.DIM}{t('setup.start_hint')}{C.RESET}")
    else:
        print(f"\n{C.YELLOW}{t('setup.cancelled')}{C.RESET}")


def setup_quick(config_path: Optional[str] = None) -> None:
    """Quick auto-detect mode: auto-detect expensive models as manual."""
    if config_path:
        path = Path(config_path)
    else:
        path = Path("config.yaml")

    config = _load_config(path)
    models = config.get("models", {})

    if not models:
        print(f"{C.YELLOW}{t('setup.no_models')}{C.RESET}")
        return

    expensive = _detect_expensive_models(
        [{"id": k, **v} for k, v in models.items()]
    )

    auto_word = t("common.auto")
    manual_word = t("common.manual")

    for key in models:
        if key in expensive:
            models[key]["selection_mode"] = "manual"
            print(f"  {C.RED}[{manual_word}]{C.RESET} {key} (auto-detected)")
        else:
            models[key].setdefault("selection_mode", "auto")
            print(f"  {C.GREEN}[{auto_word}]{C.RESET}   {key}")

    config["models"] = models
    _save_config(path, config)
    print(f"\n{C.GREEN}{t('setup.quick_complete')}{C.RESET}")


def setup_list(config_path: Optional[str] = None) -> None:
    """Show current model configuration."""
    if config_path:
        path = Path(config_path)
    else:
        path = Path("config.yaml")

    config = _load_config(path)
    models = config.get("models", {})

    if not models:
        print(f"{C.YELLOW}{t('setup.no_config')}{C.RESET}")
        return

    auto_word = t("common.auto")
    manual_word = t("common.manual")

    print(f"\n{C.BOLD}{t('setup.current_config')}:{C.RESET}")
    print(f"{'─' * 60}")
    print(f"  {'Model':<30} {'Mode':<10} {'Provider':<15}")
    print(f"{'─' * 60}")

    for key, cfg in models.items():
        mode = cfg.get("selection_mode", "auto")
        provider = cfg.get("provider", "-")
        mode_display = (
            f"{C.GREEN}{mode}{C.RESET}"
            if mode == "auto"
            else f"{C.RED}{mode}{C.RESET}"
        )
        print(f"  {key:<30} {mode_display:<20} {provider:<15}")

    print(f"{'─' * 60}")
    auto_count = sum(1 for c in models.values() if c.get("selection_mode", "auto") == "auto")
    manual_count = len(models) - auto_count
    print(f"  {C.GREEN}{auto_count} {auto_word}{C.RESET} | {C.RED}{manual_count} {manual_word}{C.RESET}")
    print()


def main() -> None:
    """CLI entry point for setup wizard."""
    args = sys.argv[1:]

    # Parse --lang option
    lang = None
    for i, arg in enumerate(args):
        if arg in ("--lang",) and i + 1 < len(args):
            lang = args[i + 1]

    # Initialize language
    init_language(lang)

    config_path = None
    for i, arg in enumerate(args):
        if arg in ("--config", "-c") and i + 1 < len(args):
            config_path = args[i + 1]

    if "--list" in args or "-l" in args:
        setup_list(config_path)
    elif "--quick" in args or "-q" in args:
        setup_quick(config_path)
    else:
        setup_wizard(config_path)


if __name__ == "__main__":
    main()
