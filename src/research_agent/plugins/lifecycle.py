"""Truthful per-user lifecycle for marketplace capabilities."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from ..core.models.db import PluginInstallation

SELECTED = "selected"
DEPLOYING = "deploying"
DEPLOYED = "deployed"
VERIFIED = "verified"
ENABLED = "enabled"
DISABLED = "disabled"
ERROR = "error"
DESELECTED = "deselected"
UNINSTALLED = "uninstalled"

INSTALLED_STATES = {DEPLOYED, VERIFIED, ENABLED, DISABLED}
VERIFIED_STATES = {VERIFIED, ENABLED, DISABLED}

ALLOWED_TRANSITIONS = {
    None: {SELECTED, DEPLOYING},
    SELECTED: {DEPLOYING, DESELECTED, ERROR},
    DEPLOYING: {DEPLOYED, ERROR},
    DEPLOYED: {DEPLOYING, VERIFIED, ERROR, UNINSTALLED},
    VERIFIED: {DEPLOYING, ENABLED, ERROR, UNINSTALLED},
    ENABLED: {DEPLOYING, DISABLED, ERROR, UNINSTALLED},
    DISABLED: {DEPLOYING, ENABLED, ERROR, UNINSTALLED},
    ERROR: {SELECTED, DEPLOYING, VERIFIED, DESELECTED, UNINSTALLED},
    DESELECTED: {SELECTED, DEPLOYING},
    UNINSTALLED: {SELECTED, DEPLOYING},
}


def state_flags(state: str | None) -> dict[str, bool]:
    return {
        "is_selected": state not in {None, DESELECTED, UNINSTALLED},
        "is_deployed": state in INSTALLED_STATES,
        "is_verified": state in VERIFIED_STATES,
        "is_enabled": state == ENABLED,
    }


def require_transition(current: str | None, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(
            f"Invalid plugin lifecycle transition: {current or 'none'} -> {target}"
        )


async def latest_installation(db, plugin_id: int, user_id: int | None):
    result = await db.execute(
        select(PluginInstallation)
        .where(
            PluginInstallation.plugin_id == plugin_id,
            PluginInstallation.user_id == user_id,
        )
        .order_by(
            PluginInstallation.state_changed_at.desc(),
            PluginInstallation.installed_at.desc(),
            PluginInstallation.id.desc(),
        )
    )
    return result.scalars().first()


async def latest_installations_for_user(db, user_id: int | None):
    """Return exactly one current lifecycle record per plugin for a user."""
    result = await db.execute(
        select(PluginInstallation)
        .where(PluginInstallation.user_id == user_id)
        .order_by(
            PluginInstallation.state_changed_at.desc(),
            PluginInstallation.installed_at.desc(),
            PluginInstallation.id.desc(),
        )
    )
    records: dict[int, PluginInstallation] = {}
    for installation in result.scalars().all():
        records.setdefault(installation.plugin_id, installation)
    return records


async def transition(
    db,
    plugin_id: int,
    user_id: int | None,
    target: str,
    *,
    version: str | None = None,
    config: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    error_message: str | None = None,
    force: bool = False,
) -> PluginInstallation:
    current = await latest_installation(db, plugin_id, user_id)
    current_state = current.status if current else None
    if not force:
        require_transition(current_state, target)
    record = PluginInstallation(
        plugin_id=plugin_id,
        user_id=user_id,
        version=version or (current.version if current else None),
        config={**((current.config or {}) if current else {}), **(config or {})},
        status=target,
        error_message=error_message,
        state_changed_at=datetime.now(),
        provenance={
            **((current.provenance or {}) if current else {}),
            **(provenance or {}),
            "previous_state": current_state,
        },
    )
    db.add(record)
    await db.flush()
    return record


__all__ = [
    "SELECTED", "DEPLOYING", "DEPLOYED", "VERIFIED", "ENABLED",
    "DISABLED", "ERROR", "DESELECTED", "UNINSTALLED", "INSTALLED_STATES",
    "VERIFIED_STATES", "ALLOWED_TRANSITIONS", "state_flags",
    "require_transition", "latest_installation", "latest_installations_for_user",
    "transition",
]
