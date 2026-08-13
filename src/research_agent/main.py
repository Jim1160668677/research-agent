"""Main application entry point"""

import uvicorn
from loguru import logger
from .core.app import create_app, settings

app = create_app()


def main():
    """CLI entry point"""
    logger.info(f"Starting {settings.app_name}")
    uvicorn.run(
        "research_agent.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
