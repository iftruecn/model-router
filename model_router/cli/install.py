"""
One-click install command for Model Router v1.5.0.

Automatically discovers all agents and injects Router provider config:
- Hermes: adds to custom_providers
- OpenClaw: adds to models.providers.router

Usage:
    model-router install              # Interactive: discover, confirm, inject
    model-router install --all        # Auto-discover and inject all (skip confirm)
    model-router install --agent hermes   # Only inject Hermes
    model-router install --agent openclaw # Only inject OpenClaw
"""

import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ANSI colors
class C:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    BLUE = "\033[34m"
    RESET = "\033[0m"


def _print(msg, color=""):
    print("{}{}{}".format(color, msg, C.RESET if color else ""))


def _backup_file(path):
    """Create a backup of the file before modifying."""
    bak = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(str(path), str(bak))
    _print("  Backup: {}".format(bak), C.DIM)
    return bak


def _inject_hermes(config_path, router_key, router_url="http://127.0.0.1:6060/v1"):
    """Inject Router provider into Hermes config (custom_providers)."""
    try:
        import yaml
    except ImportError:
        _print("ERROR: PyYAML not installed, cannot modify Hermes config", C.RED)
        return False

    # Backup
    _backup_file(config_path)

    # Load
    text = config_path.read_text(encoding="utf-8")
    config = yaml.safe_load(text) or {}

    # Ensure custom_providers exists
    if "custom_providers" not in config:
        config["custom_providers"] = []

    providers = config["custom_providers"]

    # Check if router already injected (idempotent)
    router_name = "router"
    existing = None
    for p in providers:
        if isinstance(p, dict) and p.get("name") == router_name:
            existing = p
            break

    if existing:
        # Update existing
        existing["base_url"] = router_url
        existing["api_key"] = router_key
        _print("  Updated existing router provider in Hermes config", C.YELLOW)
    else:
        # Add new
        providers.append({
            "name": router_name,
            "base_url": router_url,
            "api_key": router_key,
            "models": {
                "auto-router": {},
            },
        })
        _print("  Added router provider to Hermes config", C.GREEN)

    # Save
    config_path.write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return True


def _inject_openclaw(config_path, router_key, router_url="http://127.0.0.1:6060/v1"):
    """Inject Router provider into OpenClaw config (models.providers.router)."""
    # Backup
    _backup_file(config_path)

    # Load
    text = config_path.read_text(encoding="utf-8")
    config = json.loads(text)

    # Ensure models.providers exists
    models_section = config.setdefault("models", {})
    providers = models_section.setdefault("providers", {})

    # Check if router already exists (idempotent)
    if "router" in providers:
        # Update existing
        providers["router"]["baseUrl"] = router_url
        providers["router"]["apiKey"] = router_key
        _print("  Updated existing router provider in OpenClaw config", C.YELLOW)
    else:
        # Add new
        providers["router"] = {
            "baseUrl": router_url,
            "apiKey": router_key,
            "models": {
                "auto-router": {},
            },
        }
        _print("  Added router provider to OpenClaw config", C.GREEN)

    # Save
    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return True


def install_agents(
    agent_filter=None,
    auto_confirm=False,
    router_url="http://127.0.0.1:6060/v1",
):
    """
    Main install function.

    Args:
        agent_filter: Only install specific agent type (hermes/openclaw)
        auto_confirm: Skip interactive confirmation
        router_url: Router API URL to inject
    """
    from model_router.config.agent_discovery import discover_all_agents
    from model_router.core.agent_registry import get_agent_registry

    _print("")
    _print("=" * 56, C.GREEN + C.BOLD)
    _print("  Model Router v1.5.0 - Agent Install", C.GREEN + C.BOLD)
    _print("=" * 56, C.GREEN + C.BOLD)
    _print("")

    # Step 1: Discover agents
    _print("Scanning for agent configurations...", C.CYAN)
    agents = discover_all_agents()

    if agent_filter:
        agents = [a for a in agents if a.agent_type == agent_filter]

    if not agents:
        _print("No agent configurations found.", C.YELLOW)
        _print("Make sure Hermes or OpenClaw is installed.", C.YELLOW)
        return False

    # Step 2: Show discovered agents
    _print("")
    _print("Discovered agents:", C.BOLD)
    _print("-" * 50)
    for i, agent in enumerate(agents, 1):
        _print("  {}. {} ({})".format(i, agent.agent_type, agent.config_path), C.CYAN)
        _print("     Found via: {}".format(agent.discovery_method), C.DIM)
    _print("-" * 50)

    # Step 3: Confirm
    if not auto_confirm:
        _print("")
        try:
            answer = input("{}Install all agents? [Y/n] {}".format(C.YELLOW, C.RESET)).strip()
        except (EOFError, KeyboardInterrupt):
            _print("")
            return False
        if answer.lower() in ("n", "no"):
            _print("Cancelled.", C.YELLOW)
            return False

    # Step 4: Generate keys and inject
    registry = get_agent_registry()
    success_count = 0

    for agent in agents:
        _print("")
        _print("Installing {}...".format(agent.agent_type), C.BOLD)

        # Generate unique key
        router_key = registry.generate_agent_key(agent.agent_type)

        # Extract model list from agent config
        models = _extract_models(agent)

        # Inject based on type
        ok = False
        if agent.agent_type == "hermes":
            ok = _inject_hermes(agent.config_path, router_key, router_url)
        elif agent.agent_type == "openclaw":
            ok = _inject_openclaw(agent.config_path, router_key, router_url)
        else:
            _print("  Unknown agent type: {}".format(agent.agent_type), C.RED)
            continue

        if ok:
            # Register in agent registry
            registry.register_agent(
                agent_type=agent.agent_type,
                config_path=str(agent.config_path),
                router_key_raw=router_key,
                models=models,
            )
            _print("  Key: {}".format(router_key[:12] + "..."), C.GREEN)
            _print("  Models: {}".format(", ".join(models) if models else "(auto-detect)"), C.DIM)
            success_count += 1

    _print("")
    _print("=" * 56, C.GREEN)
    _print("  Installed {}/{} agent(s)".format(success_count, len(agents)), C.GREEN)
    _print("=" * 56, C.GREEN)
    _print("")
    _print("Next: restart Model Router to activate agent routing.", C.DIM)

    return success_count > 0


def _extract_models(agent):
    """Extract model list from an agent's config data."""
    models = []
    data = agent.config_data

    if agent.agent_type == "hermes":
        # Hermes: custom_providers[].models
        for cp in data.get("custom_providers", []):
            if isinstance(cp, dict):
                cp_models = cp.get("models", {})
                if isinstance(cp_models, dict):
                    models.extend(cp_models.keys())
                elif isinstance(cp_models, list):
                    for m in cp_models:
                        if isinstance(m, dict):
                            models.append(m.get("id", ""))
                        elif isinstance(m, str):
                            models.append(m)

    elif agent.agent_type == "openclaw":
        # OpenClaw: models.providers.*.models
        models_section = data.get("models", {})
        providers = models_section.get("providers", {})
        for pname, pconfig in providers.items():
            if isinstance(pconfig, dict):
                pmodels = pconfig.get("models", {})
                if isinstance(pmodels, dict):
                    models.extend(pmodels.keys())

    # Deduplicate
    return list(dict.fromkeys(models))


def main():
    """CLI entry point for install command."""
    args = sys.argv[1:]

    agent_filter = None
    auto_confirm = False

    for i, arg in enumerate(args):
        if arg == "--agent" and i + 1 < len(args):
            agent_filter = args[i + 1]
        elif arg == "--all":
            auto_confirm = True

    install_agents(
        agent_filter=agent_filter,
        auto_confirm=auto_confirm,
    )


if __name__ == "__main__":
    main()
