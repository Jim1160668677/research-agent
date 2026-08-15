"""安全模块 - 数据加密、访问控制与审计"""

import base64
import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from loguru import logger

from .core.app import settings

try:
    from sqlalchemy import desc, select

    from .core.models.db import AuditLog
    _db_available = True
except ImportError:
    _db_available = False


class CryptoService:
    """加密服务 - 使用Fernet对称加密保护敏感数据"""

    _fernet: Fernet | None = None
    _salt: bytes | None = None

    @classmethod
    def _load_or_create_salt(cls) -> bytes:
        """加载或创建安装级唯一 salt (持久化到文件)"""
        if cls._salt is not None:
            return cls._salt

        import os
        from pathlib import Path

        configured_data_dir = os.environ.get("RESEARCH_AGENT_DATA_DIR")
        if configured_data_dir:
            salt_file = Path(configured_data_dir) / ".enc_salt"
        else:
            user_data = os.environ.get("APPDATA", os.path.expanduser("~"))
            salt_file = Path(user_data) / "ResearchAgent" / ".enc_salt"

        try:
            if salt_file.exists():
                cls._salt = salt_file.read_bytes()
            else:
                cls._salt = secrets.token_bytes(32)
                salt_file.parent.mkdir(parents=True, exist_ok=True)
                salt_file.write_bytes(cls._salt)
                logger.info(f"已创建加密盐: {salt_file}")
        except Exception as e:
            logger.warning(f"盐文件读写失败，使用临时盐: {e}")
            cls._salt = secrets.token_bytes(32)

        return cls._salt

    @classmethod
    def _get_fernet(cls) -> Fernet:
        """获取或创建Fernet实例"""
        if cls._fernet is None:
            salt = cls._load_or_create_salt()
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(
                kdf.derive(settings.jwt_secret.encode())
            )
            cls._fernet = Fernet(key)
        return cls._fernet

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        """加密字符串"""
        if not plaintext:
            return plaintext
        token = cls._get_fernet().encrypt(plaintext.encode())
        return token.decode()

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        """解密字符串"""
        if not ciphertext:
            return ciphertext
        try:
            return cls._get_fernet().decrypt(ciphertext.encode()).decode()
        except Exception as e:
            logger.error(f"解密失败: {e}")
            return ""

    @classmethod
    def derive_key(cls, purpose: str, *, length: int = 32) -> bytes:
        """Derive a domain-separated installation key without storing raw key material."""
        if not purpose or length < 16:
            raise ValueError("A purpose and a key length of at least 16 bytes are required")
        salt = cls._load_or_create_salt()
        return hashlib.pbkdf2_hmac(
            "sha256",
            settings.jwt_secret.encode("utf-8"),
            salt + b"\x00" + purpose.encode("utf-8"),
            210_000,
            dklen=length,
        )

    @classmethod
    def hash_password(cls, password: str) -> str:
        """密码哈希 (PBKDF2-SHA256)"""
        salt = secrets.token_bytes(16)
        derived = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, 100_000
        )
        return f"pbkdf2${salt.hex()}${derived.hex()}"

    @classmethod
    def verify_password(cls, password: str, stored_hash: str) -> bool:
        """验证密码"""
        try:
            algo, salt_hex, hash_hex = stored_hash.split("$")
            if algo != "pbkdf2":
                return False
            salt = bytes.fromhex(salt_hex)
            derived = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt, 100_000
            )
            return hmac.compare_digest(derived.hex(), hash_hex)
        except Exception:
            return False

    @classmethod
    def generate_token(cls) -> str:
        """生成随机令牌"""
        return secrets.token_urlsafe(32)

    @classmethod
    def generate_api_key(cls) -> str:
        """生成API密钥"""
        return f"ra_{secrets.token_urlsafe(32)}"


class AccessControl:
    """访问控制 - 基于角色的权限管理"""

    # 角色定义
    ROLES = {
        "admin": {"plugins": "rw", "workflows": "rw", "skills": "rw", "data": "rw"},
        "researcher": {"plugins": "r", "workflows": "rw", "skills": "rw", "data": "rw"},
        "viewer": {"plugins": "r", "workflows": "r", "skills": "r", "data": "r"},
    }

    @classmethod
    def check_permission(cls, role: str, resource: str, action: str = "r") -> bool:
        """检查权限"""
        perms = cls.ROLES.get(role, {})
        perm = perms.get(resource, "")
        if action == "r":
            return "r" in perm
        elif action == "w":
            return "w" in perm
        return False

    @classmethod
    def can_manage_plugins(cls, role: str) -> bool:
        """是否可以管理插件"""
        return cls.check_permission(role, "plugins", "w")

    @classmethod
    def can_edit_workflow(cls, role: str) -> bool:
        """是否可以编辑工作流"""
        return cls.check_permission(role, "workflows", "w")


class AuditLogger:
    """审计日志 - 记录所有敏感操作 (支持内存和数据库双模式)

    在无数据库环境下回退到内存模式。
    """

    _events: list[dict[str, Any]] = []

    @classmethod
    def log(cls, user_id: int | None, action: str, resource: str,
            detail: dict | None = None,
            ip_address: str | None = None,
            request_id: str | None = None,
            success: bool = True,
            error_message: str | None = None,
            user_agent: str | None = None):
        """记录审计事件 (内存模式)"""
        event = {
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "action": action,
            "resource": resource,
            "detail": detail or {},
            "ip_address": ip_address,
            "request_id": request_id,
            "success": success,
            "error_message": error_message,
            "user_agent": user_agent,
        }
        cls._events.append(event)
        log_level = logger.warning if not success else logger.info
        log_level(f"[AUDIT] user={user_id} action={action} resource={resource} "
                  f"success={success} req_id={request_id}")

    @classmethod
    async def log_to_db(cls, db, user_id: int | None, action: str,
                        resource: str, resource_id: str | None = None,
                        detail: dict | None = None,
                        ip_address: str | None = None,
                        request_id: str | None = None,
                        success: bool = True,
                        error_message: str | None = None,
                        user_agent: str | None = None):
        """记录审计事件 (持久化到数据库)"""
        if not _db_available:
            cls.log(user_id, action, resource, detail,
                    ip_address, request_id, success, error_message, user_agent)
            return

        try:
            from .audit_chain import append_audit

            await append_audit(
                db,
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
            )
        except Exception as e:
            try:
                await db.rollback()
            except Exception:
                pass
            logger.error(f"审计日志持久化失败: {e}")
            # 回退到内存模式
            cls.log(user_id, action, resource, detail,
                    ip_address, request_id, success, error_message, user_agent)

    @classmethod
    async def query(cls, db, user_id: int | None = None,
                    action: str | None = None,
                    resource: str | None = None,
                    limit: int = 100) -> list[dict]:
        """查询审计日志 (从数据库)"""
        if not _db_available:
            return cls._events[-limit:]

        query = select(AuditLog).order_by(desc(AuditLog.created_at))
        if user_id is not None:
            query = query.where(AuditLog.user_id == user_id)
        if action is not None:
            query = query.where(AuditLog.action == action)
        if resource is not None:
            query = query.where(AuditLog.resource == resource)
        query = query.limit(limit)

        result = await db.execute(query)
        rows = result.scalars().all()
        return [cls._log_to_dict(r) for r in rows]

    @staticmethod
    def _log_to_dict(log: AuditLog) -> dict:
        return {
            "id": log.id,
            "user_id": log.user_id,
            "action": log.action,
            "resource": log.resource,
            "resource_id": log.resource_id,
            "detail": log.detail,
            "ip_address": log.ip_address,
            "request_id": log.request_id,
            "success": log.success,
            "error_message": log.error_message,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }

    @classmethod
    def get_events(cls, limit: int = 100) -> list:
        """获取内存中的审计事件"""
        return cls._events[-limit:]

    @classmethod
    def export(cls, path: str = "audit.log"):
        """导出审计日志"""
        import json
        with open(path, "w", encoding="utf-8") as f:
            for event in cls._events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")


__all__ = ["CryptoService", "AccessControl", "AuditLogger"]
