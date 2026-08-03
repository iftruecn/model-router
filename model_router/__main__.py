"""
Entry point for Model Router CLI.

Usage:
    model-router serve              # Start the server (default)
    model-router setup              # Interactive setup wizard
    model-router setup --quick      # Quick auto-detect mode
    model-router setup --list       # Show current config
    python -m model_router serve    # Same as above
"""

import sys

from model_router import __version__
from model_router.config.defaults import DEFAULT_HOST, DEFAULT_PORT


def _print_banner() -> None:
    """Print startup banner."""
    print("=" * 60)
    print(f"  Model Router v{__version__} — MOA Middleware")
    print("  by iftrue-hermes / MIT License")
    print("=" * 60)


def _cmd_serve() -> None:
    """Start the Model Router server."""
    import uvicorn

    _print_banner()
    print(f"  Listening: http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"  API Docs:  http://{DEFAULT_HOST}:{DEFAULT_PORT}/docs")
    print(f"  Admin API: http://{DEFAULT_HOST}:{DEFAULT_PORT}/admin/models")
    print("=" * 60)

    uvicorn.run(
        "model_router.app:app",
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        log_level="warning",
    )


def _cmd_setup() -> None:
    """Run the interactive setup wizard."""
    from model_router.cli.setup import main as setup_main

    # Remove 'setup' from argv so setup module sees only its own flags
    sys.argv = [a for a in sys.argv if a != "setup"]
    sys.argv.insert(0, "model-router")
    setup_main()


def main() -> None:
    """Main CLI entry point with subcommand routing."""
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not args or args[0] in ("serve", "start", "run"):
        _cmd_serve()
    elif args[0] == "setup":
        _cmd_setup()
    elif args[0] in ("help", "--help", "-h"):
        _print_banner()
        print()
        print("  Commands:")
        print("    serve    Start the server (default)")
        print("    setup    Interactive model configuration wizard")
        print()
        print("  Setup options:")
        print("    model-router setup --quick    Auto-detect expensive models")
        print("    model-router setup --list     Show current configuration")
        print("    model-router setup -c PATH    Use custom config path")
        print()
        print("  Examples:")
        print("    model-router                  # Start server")
        print("    model-router setup            # Configure models")
        print("    model-router setup --quick    # Quick auto-detect")
        print()
    else:
        print(f"Unknown command: {args[0]}")
        print("Run 'model-router help' for usage.")
        sys.exit(1)


if __name__ == "__main__":
    main()
