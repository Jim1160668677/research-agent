"""Database utilities"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from loguru import logger

from .models.db import Base
from .app import settings

def _create_engine(database_url: str):
    return create_async_engine(
        database_url,
        echo=settings.debug,
        poolclass=NullPool if "sqlite" in database_url else None,
    )


# Create async engine
engine = _create_engine(settings.database_url)
_retired_engines = []

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def configure_database(database_url: str) -> None:
    """Rebind the process-wide session factory to a new database URL.

    Desktop startup configures the URL before import. This explicit hook keeps
    tests, maintenance commands, and future profile switching deterministic
    without reloading modules that imported ``AsyncSessionLocal``.
    """
    global engine
    if str(engine.url) == database_url:
        settings.database_url = database_url
        return
    _retired_engines.append(engine)
    settings.database_url = database_url
    engine = _create_engine(database_url)
    AsyncSessionLocal.configure(bind=engine)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Initialize database - create tables + run light migrations + seed data"""
    async with engine.begin() as conn:
        # 仅创建不存在的表 (checkfirst=True 防止重复创建)
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        if "sqlite" in settings.database_url:
            await conn.run_sync(_light_migrations)
    logger.info("Database initialized successfully")

    # 写入种子数据 (幂等: 已存在的记录不会重复插入)
    try:
        from ..plugins.seed import seed_plugins
        async with AsyncSessionLocal() as session:
            await seed_plugins(session)
        logger.info("Plugin seed data loaded")
    except Exception as e:
        logger.warning(f"Plugin seed data skipped: {e}")


def _light_migrations(conn):
    """轻量迁移: 为已存在的旧表补充新增列"""
    from sqlalchemy import inspect, text

    inspector = inspect(conn)

    # --- plugins 表迁移 ---
    if inspector.has_table("plugins"):
        existing_cols = {c["name"] for c in inspector.get_columns("plugins")}
        new_columns = {
            "latest_version": "VARCHAR(20)",
            "downloads": "INTEGER DEFAULT 0",
            "rating_avg": "FLOAT DEFAULT 0.0",
            "rating_count": "INTEGER DEFAULT 0",
            "homepage": "VARCHAR(500)",
            "docs_url": "VARCHAR(500)",
            "support_email": "VARCHAR(100)",
            "os_compatibility": "JSON",
            "install_method": "JSON",
            "manifest_schema_version": "VARCHAR(20) DEFAULT '1.0'",
            "manifest": "JSON",
            "manifest_digest": "VARCHAR(64)",
            "source_registry": "VARCHAR(50) DEFAULT 'builtin'",
            "source_identifier": "VARCHAR(255)",
            "source_metadata": "JSON",
            "source_synced_at": "DATETIME",
            "trust_status": "VARCHAR(20) DEFAULT 'curated'",
        }
        for col, ddl in new_columns.items():
            if col not in existing_cols:
                conn.execute(text(f"ALTER TABLE plugins ADD COLUMN {col} {ddl}"))
                logger.info(f"Migration: plugins.{col} added")

    if inspector.has_table("plugin_installations"):
        existing_cols = {
            c["name"] for c in inspector.get_columns("plugin_installations")
        }
        installation_columns = {
            "state_changed_at": "DATETIME",
            "provenance": "JSON",
        }
        for col, ddl in installation_columns.items():
            if col not in existing_cols:
                conn.execute(
                    text(f"ALTER TABLE plugin_installations ADD COLUMN {col} {ddl}")
                )
                logger.info(f"Migration: plugin_installations.{col} added")
        conn.execute(text(
            "UPDATE plugin_installations SET state_changed_at = "
            "COALESCE(state_changed_at, installed_at, CURRENT_TIMESTAMP)"
        ))
        conn.execute(text(
            "UPDATE plugin_installations SET status = 'selected' "
            "WHERE status = 'installed' AND "
            "(config IS NULL OR json_extract(config, '$.environment_prefix') IS NULL "
            "OR json_extract(config, '$.environment_prefix') = '')"
        ))
        conn.execute(text(
            "UPDATE plugin_installations SET status = 'deployed' "
            "WHERE status = 'installed' AND "
            "json_extract(config, '$.environment_prefix') IS NOT NULL "
            "AND json_extract(config, '$.environment_prefix') != ''"
        ))

    # --- users 表迁移 ---
    if inspector.has_table("users"):
        existing_cols = {c["name"] for c in inspector.get_columns("users")}
        new_columns = {
            "role": "VARCHAR(20) DEFAULT 'researcher'",
        }
        for col, ddl in new_columns.items():
            if col not in existing_cols:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
                logger.info(f"Migration: users.{col} added")

    if inspector.has_table("research_artifacts"):
        existing_cols = {c["name"] for c in inspector.get_columns("research_artifacts")}
        artifact_columns = {
            "encryption_format": "VARCHAR(30)",
            "encrypted_sha256": "VARCHAR(64)",
        }
        for col, ddl in artifact_columns.items():
            if col not in existing_cols:
                conn.execute(text(f"ALTER TABLE research_artifacts ADD COLUMN {col} {ddl}"))
                logger.info(f"Migration: research_artifacts.{col} added")

    if inspector.has_table("audit_logs"):
        existing_cols = {c["name"] for c in inspector.get_columns("audit_logs")}
        audit_columns = {
            "chain_index": "INTEGER",
            "previous_hash": "VARCHAR(64)",
            "entry_hash": "VARCHAR(64)",
            "chain_version": "VARCHAR(20)",
        }
        for col, ddl in audit_columns.items():
            if col not in existing_cols:
                conn.execute(text(f"ALTER TABLE audit_logs ADD COLUMN {col} {ddl}"))
                logger.info(f"Migration: audit_logs.{col} added")
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_audit_logs_chain_index "
            "ON audit_logs (chain_index)"
        ))


async def close_db():
    """Close database connections"""
    await engine.dispose()
    while _retired_engines:
        retired = _retired_engines.pop()
        try:
            await retired.dispose()
        except Exception:
            pass
    logger.info("Database connections closed")


@asynccontextmanager
async def transaction(session: AsyncSession):
    """Context manager for database transactions"""
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise


__all__ = [
    "engine",
    "AsyncSessionLocal",
    "configure_database",
    "get_db",
    "init_db",
    "close_db",
    "transaction",
]
