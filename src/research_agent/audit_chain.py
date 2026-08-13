"""Application-keyed, tamper-evident audit chain support."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import weakref
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .core.models.db import AuditLog

CHAIN_VERSION = "hmac-sha256-v1"
GENESIS_HASH = "0" * 64
_loop_locks: weakref.WeakKeyDictionary[Any, asyncio.Lock] = weakref.WeakKeyDictionary()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _chain_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _loop_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _loop_locks[loop] = lock
    return lock


def _timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds") + "Z"


def _canonical_payload(entry: AuditLog) -> bytes:
    value = {
        "chain_version": entry.chain_version,
        "chain_index": entry.chain_index,
        "previous_hash": entry.previous_hash,
        "user_id": entry.user_id,
        "action": entry.action,
        "resource": entry.resource,
        "resource_id": entry.resource_id,
        "detail": entry.detail or {},
        "ip_address": entry.ip_address,
        "user_agent": entry.user_agent,
        "request_id": entry.request_id,
        "success": bool(entry.success),
        "error_message": entry.error_message,
        "created_at": _timestamp(entry.created_at),
    }
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _entry_hash(entry: AuditLog) -> str:
    # Imported lazily to avoid a security-module import cycle.
    from .security import CryptoService

    return hmac.new(
        CryptoService.derive_key("audit-chain-v1"),
        _canonical_payload(entry),
        hashlib.sha256,
    ).hexdigest()


async def append_audit(
    db: Any,
    *,
    user_id: int | None,
    action: str,
    resource: str,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> AuditLog:
    """Atomically commit caller changes with one serialized chained event."""

    async with _chain_lock():
        result = await db.execute(
            select(AuditLog)
            .where(AuditLog.entry_hash.is_not(None))
            .order_by(AuditLog.chain_index.desc(), AuditLog.id.desc())
            .limit(1)
        )
        previous = result.scalars().first()
        entry = AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            detail=detail or {},
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            success=success,
            error_message=error_message,
            chain_index=(int(previous.chain_index) + 1) if previous else 1,
            previous_hash=str(previous.entry_hash) if previous else GENESIS_HASH,
            chain_version=CHAIN_VERSION,
            created_at=_utcnow(),
        )
        entry.entry_hash = _entry_hash(entry)
        db.add(entry)
        # Commit while the append lock is held so concurrent in-process requests
        # cannot calculate the same predecessor/index pair.
        await db.commit()
        return entry


async def verify_audit_chain(db: Any) -> dict[str, Any]:
    """Verify all chained rows and report pre-chain legacy rows separately."""

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.entry_hash.is_not(None))
        .order_by(AuditLog.chain_index.asc(), AuditLog.id.asc())
    )
    rows = result.scalars().all()
    legacy_result = await db.execute(
        select(AuditLog.id).where(AuditLog.entry_hash.is_(None))
    )
    legacy_count = len(legacy_result.scalars().all())
    issues: list[dict[str, Any]] = []
    previous_hash = GENESIS_HASH
    expected_index = 1
    for row in rows:
        reasons: list[str] = []
        if row.chain_version != CHAIN_VERSION:
            reasons.append("unsupported_chain_version")
        if row.chain_index != expected_index:
            reasons.append("non_contiguous_index")
        if not hmac.compare_digest(str(row.previous_hash or ""), previous_hash):
            reasons.append("previous_hash_mismatch")
        expected_hash = _entry_hash(row)
        if not hmac.compare_digest(str(row.entry_hash or ""), expected_hash):
            reasons.append("entry_hash_mismatch")
        if reasons:
            issues.append({"id": row.id, "chain_index": row.chain_index, "reasons": reasons})
        previous_hash = str(row.entry_hash or "")
        expected_index += 1
    return {
        "valid": not issues,
        "chain_version": CHAIN_VERSION,
        "chained_entries": len(rows),
        "legacy_unchained_entries": legacy_count,
        "head_hash": previous_hash if rows else None,
        "issues": issues[:100],
        "limitations": [
            "This detects modified, reordered, or internally deleted chained rows.",
            (
                "Detecting tail truncation requires anchoring the head hash in "
                "external WORM or signed storage."
            ),
        ],
    }


__all__ = ["CHAIN_VERSION", "append_audit", "verify_audit_chain"]
