"""
Entry point for Model Router CLI.

Multilingual: Supports EN, ZH, JA, KO, ES, FR, DE.

Usage:
    model-router serve              # Start the server (default)
    model-router setup              # Interactive setup wizard
    model-router setup --quick      # Quick auto-detect mode
    model-router setup --list       # Show current config
    model-router setup --lang zh    # Force Chinese
    python -m model_router serve    # Same as above
"""

import sys

from model_router import __version__
from model_router.config.defaults import DEFAULT_HOST, DEFAULT_PORT
from model_router.locales.i18n import init_language, t, get_language


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


def _print_help() -> None:
    """Print help text in current language."""
    _print_banner()
    print()
    print(f"  {t('help.commands')}:")
    print(f"    serve    {t('help.serve_desc')}")
    print(f"    setup    {t('help.setup_desc')}")
    print()
    print(f"  {t('help.options')}:")
    print(f"    model-router setup --quick    {t('help.quick_desc')}")
    print(f"    model-router setup --list     {t('help.list_desc')}")
    print(f"    model-router setup -c PATH    {t('help.config_desc')}")
    print(f"    model-router setup --lang XX  Language (en/zh/ja/ko/es/fr/de)")
    print()
    print(f"  Examples:")
    print(f"    model-router                  # Start server")
    print(f"    model-router setup            # Configure models")
    print(f"    model-router setup --lang zh  # 中文配置向导")
    print()


def main() -> None:
    """Main CLI entry point with subcommand routing."""
    # Parse --lang early
    args_raw = sys.argv[1:]
    lang = None
    for i, arg in enumerate(args_raw):
        if arg == "--lang" and i + 1 < len(args_raw):
            lang = args_raw[i + 1]

    init_language(lang)

    args = [a for a in args_raw if not a.startswith("--")]

    if not args or args[0] in ("serve", "start", "run"):
        _cmd_serve()
    elif args[0] == "setup":
        _cmd_setup()
    elif args[0] in ("help", "--help", "-h"):
        _print_help()
    else:
        print(f"Unknown command: {args[0]}")
        print("Run 'model-router help' for usage.")
        sys.exit(1)


if __name__ == "__main__":
    main()
