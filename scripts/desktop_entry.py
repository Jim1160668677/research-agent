"""PyInstaller entry point that preserves the research_agent package context."""

from research_agent.desktop_app import main


if __name__ == "__main__":
    raise SystemExit(main())
