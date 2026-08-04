"""
Agent configuration auto-discovery for Model Router v1.6.1.

Discovers ALL agent configurations on the system (not just the first one).
Supports:
- Hermes (YAML)
- OpenClaw and derivatives (JSON) -- LobsterAI, AutoClaw, etc.

Discovery strategies (in priority order):
1. Environment variables (OPENCLAW_CONFIG, OPENCLAW_RUNTIME_CONFIG)
2. Process scanning (find running agent processes, extract config paths)
3. Known path scanning (standard locations)
4. Recursive directory scanning (common AI data directories)
"""

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent type definitions
# ---------------------------------------------------------------------------

AGENT_TYPES = {
    "hermes": {
        "format": "yaml",
        "config_filenames": ["config.yaml"],
        "standard_paths": [
            "~/.hermes/config.yaml",
        ],
    },
    "openclaw": {
        "format": "json",
        "config_filenames": ["openclaw.runtime.json"],
        "standard_paths": [
            "~/.openclaw/openclaw.runtime.json",
            "~/.config/openclaw/openclaw.runtime.json",
        ],
    },
}

# Directories to scan for agent configs (common AI data locations)
# P3-1 fix: use Path.home()-based cross-platform paths
SCAN_ROOT_DIRS = [
    Path.home() / ".openclaw",
    Path.home() / ".config" / "openclaw",
    Path.home() / ".hermes",
    Path.home() / "HermesData",
    Path.home() / "LobsterAIData",
]

# Process names to look for when scanning running processes
AGENT_PROCESS_PATTERNS = {
    "openclaw": [r"openclaw", r"lobster", r"autoclaw", r"LobsterAI"],
    "hermes": [r"hermes"],
}


# ---------------------------------------------------------------------------
# Discovered agent info
# ---------------------------------------------------------------------------

class DiscoveredAgent:
    """Represents a discovered agent configuration."""

    def __init__(self, agent_type, config_path, discovery_method, config_data):
        self.agent_type = agent_type
        self.config_path = config_path
        self.discovery_method = discovery_method
        self.config_data = config_data

    def __repr__(self):
        return (
            "DiscoveredAgent(type={!r}, path={}, method={!r})".format(
                self.agent_type, self.config_path, self.discovery_method
            )
        )


# ---------------------------------------------------------------------------
# Strategy 1: Environment variables
# ---------------------------------------------------------------------------

def _discover_from_env():
    """Check environment variables for config paths."""
    agents = []
    env_vars = {
        "openclaw": ["OPENCLAW_CONFIG", "OPENCLAW_RUNTIME_CONFIG"],
    }
    for agent_type, var_names in env_vars.items():
        for var in var_names:
            val = os.environ.get(var)
            if val:
                p = Path(val).expanduser()
                if p.is_file():
                    data = _load_config_file(p, AGENT_TYPES[agent_type]["format"])
                    if data is not None:
                        agents.append(DiscoveredAgent(
                            agent_type=agent_type,
                            config_path=p,
                            discovery_method="env:" + var,
                            config_data=data,
                        ))
                        logger.info("Found %s config via env %s: %s", agent_type, var, p)
    return agents


# ---------------------------------------------------------------------------
# Strategy 2: Process scanning
# ---------------------------------------------------------------------------

def _discover_from_processes():
    """Scan running processes to find agent config paths."""
    agents = []
    found_paths = set()

    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["wmic", "process", "get", "CommandLine"],
                capture_output=True, text=True, timeout=5,
            )
            lines = result.stdout.split("\n")
            for line in lines:
                for agent_type, patterns in AGENT_PROCESS_PATTERNS.items():
                    for pat in patterns:
                        if re.search(pat, line, re.IGNORECASE):
                            for path_match in re.finditer(
                                r'[A-Za-z]:\\[^\s"]+\.json|[A-Za-z]:\\[^\s"]+\.yaml', line
                            ):
                                p = Path(path_match.group())
                                if p.is_file() and p not in found_paths:
                                    found_paths.add(p)
                                    fmt = AGENT_TYPES[agent_type]["format"]
                                    data = _load_config_file(p, fmt)
                                    if data is not None:
                                        agents.append(DiscoveredAgent(
                                            agent_type=agent_type,
                                            config_path=p,
                                            discovery_method="process",
                                            config_data=data,
                                        ))
                                        logger.info("Found %s config via process: %s", agent_type, p)
        else:
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.split("\n"):
                for agent_type, patterns in AGENT_PROCESS_PATTERNS.items():
                    for pat in patterns:
                        if re.search(pat, line, re.IGNORECASE):
                            for path_match in re.finditer(
                                r'/[\w./\-]+\.json|/[\w./\-]+\.yaml', line
                            ):
                                p = Path(path_match.group())
                                if p.is_file() and p not in found_paths:
                                    found_paths.add(p)
                                    fmt = AGENT_TYPES[agent_type]["format"]
                                    data = _load_config_file(p, fmt)
                                    if data is not None:
                                        agents.append(DiscoveredAgent(
                                            agent_type=agent_type,
                                            config_path=p,
                                            discovery_method="process",
                                            config_data=data,
                                        ))
                                        logger.info("Found %s config via process: %s", agent_type, p)
    except Exception as e:
        logger.debug("Process scanning failed: %s", e)

    return agents


# ---------------------------------------------------------------------------
# Strategy 3: Known path scanning
# ---------------------------------------------------------------------------

def _discover_from_known_paths():
    """Check standard/known paths for agent configs."""
    agents = []
    found_paths = set()

    for agent_type, info in AGENT_TYPES.items():
        for sp in info["standard_paths"]:
            p = Path(sp).expanduser()
            if p.is_file() and p not in found_paths:
                found_paths.add(p)
                data = _load_config_file(p, info["format"])
                if data is not None:
                    agents.append(DiscoveredAgent(
                        agent_type=agent_type,
                        config_path=p,
                        discovery_method="known_path",
                        config_data=data,
                    ))
                    logger.info("Found %s config at known path: %s", agent_type, p)

    return agents


# ---------------------------------------------------------------------------
# Strategy 4: Recursive directory scanning
# ---------------------------------------------------------------------------

def _discover_from_dir_scan():
    """Recursively scan common directories for agent config files."""
    agents = []
    found_paths = set()

    target_filenames = set()
    for info in AGENT_TYPES.values():
        for fn in info["config_filenames"]:
            target_filenames.add(fn)

    for root_dir in SCAN_ROOT_DIRS:
        rd = root_dir.expanduser() if isinstance(root_dir, Path) else Path(root_dir)
        if not rd.exists():
            continue
        try:
            # Only check direct children (1 level deep) - fast and safe
            for p in rd.iterdir():
                # P0-4 fix: skip hidden directories (e.g. .openclaw-autoclaw/)
                if p.is_dir() and p.name.startswith('.'):
                    continue
                if p.is_file() and p.name in target_filenames and p not in found_paths:
                    agent_type = None
                    for at, info in AGENT_TYPES.items():
                        if p.name in info["config_filenames"]:
                            agent_type = at
                            break
                    if agent_type:
                        found_paths.add(p)
                        fmt = AGENT_TYPES[agent_type]["format"]
                        data = _load_config_file(p, fmt)
                        if data is not None:
                            agents.append(DiscoveredAgent(
                                agent_type=agent_type,
                                config_path=p,
                                discovery_method="dir_scan",
                                config_data=data,
                            ))
                            logger.info("Found %s config via dir scan: %s", agent_type, p)
                # Also check one level subdirectories
                elif p.is_dir():
                    try:
                        for sub in p.iterdir():
                            if sub.is_file() and sub.name in target_filenames and sub not in found_paths:
                                agent_type = None
                                for at, info in AGENT_TYPES.items():
                                    if sub.name in info["config_filenames"]:
                                        agent_type = at
                                        break
                                if agent_type:
                                    found_paths.add(sub)
                                    fmt = AGENT_TYPES[agent_type]["format"]
                                    data = _load_config_file(sub, fmt)
                                    if data is not None:
                                        agents.append(DiscoveredAgent(
                                            agent_type=agent_type,
                                            config_path=sub,
                                            discovery_method="dir_scan",
                                            config_data=data,
                                        ))
                                        logger.info("Found %s config via dir scan: %s", agent_type, sub)
                    except PermissionError:
                        pass
        except PermissionError:
            continue
        except Exception as e:
            logger.debug("Dir scan error at %s: %s", root_dir, e)

    return agents


# ---------------------------------------------------------------------------
# Config file loading
# ---------------------------------------------------------------------------

def _load_config_file(path, fmt="yaml"):
    """Safely load a YAML or JSON config file."""
    try:
        text = path.read_text(encoding="utf-8")
        if fmt == "json" or path.suffix == ".json":
            return json.loads(text) or {}
        # YAML
        try:
            import yaml
            result = yaml.safe_load(text)
            return result if isinstance(result, dict) else {}
        except ImportError:
            return {}
    except Exception as e:
        logger.debug("Failed to load %s: %s", path, e)
        return None


# ---------------------------------------------------------------------------
# Main discovery function
# ---------------------------------------------------------------------------

def discover_all_agents():
    """
    Discover ALL agent configurations on the system.

    Tries strategies in priority order:
    1. Environment variables
    2. Process scanning
    3. Known paths
    4. Directory scanning

    Deduplicates by config path. Returns list of all found agents.
    """
    all_agents = []
    seen_paths = set()

    strategies = [
        ("env", _discover_from_env),
        ("process", _discover_from_processes),
        ("known_path", _discover_from_known_paths),
        ("dir_scan", _discover_from_dir_scan),
    ]

    for strategy_name, strategy_fn in strategies:
        found = strategy_fn()
        for agent in found:
            real_path = agent.config_path.resolve()
            if real_path not in seen_paths:
                seen_paths.add(real_path)
                all_agents.append(agent)

    if all_agents:
        logger.info(
            "Discovered %d agent(s): %s",
            len(all_agents),
            ["{}@{}".format(a.agent_type, a.config_path) for a in all_agents],
        )
    else:
        logger.debug("No agent configurations discovered")

    return all_agents


def discover_agents_by_type(agent_type):
    """Discover all agents of a specific type."""
    return [a for a in discover_all_agents() if a.agent_type == agent_type]


def find_openclaw_configs():
    """Find all OpenClaw-format configs (including derivatives)."""
    return discover_agents_by_type("openclaw")


def find_hermes_configs():
    """Find all Hermes configs."""
    return discover_agents_by_type("hermes")
