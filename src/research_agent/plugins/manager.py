"""Plugin manager - 插件市场管理

功能:
- 插件 CRUD / 搜索 / 分类浏览 / 排序
- 版本控制: 版本历史 / 版本切换 / 更新检测 / 升级
- 用户评价与评分聚合
- 依赖解析入口
"""

from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import delete, func, select, update

from ..core.db import AsyncSession
from ..core.models.db import Plugin, PluginInstallation, PluginReview, PluginVersion
from .lifecycle import (
    DESELECTED,
    DISABLED,
    ENABLED,
    ERROR,
    INSTALLED_STATES,
    SELECTED,
    VERIFIED_STATES,
    latest_installation,
    latest_installations_for_user,
    state_flags,
    transition,
)
from .manifest import manifest_digest, validated_manifest_for_plugin


def _latest_of(versions: list[dict[str, Any]]) -> str | None:
    """从版本历史中取最新版本 (优先 is_latest 标记, 否则取最后一个)"""
    if not versions:
        return None
    for v in versions:
        if v.get("is_latest"):
            return v["version"]
    return versions[-1]["version"]


class PluginManager:
    """插件管理器"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self._plugin_cache: dict[str, Plugin] = {}

    @classmethod
    def initialize(cls):
        """初始化插件系统"""
        logger.info("Plugin system initialized")

    # ---------- 查询 ----------

    async def list_plugins(
        self,
        category: str | None = None,
        status: str | None = None,
        search: str | None = None,
        sort: str | None = None,
        installed_only: bool = False,
        update_available_only: bool = False,
        user_id: int | None = None,
    ) -> list[dict]:
        """列出插件，支持搜索/分类/排序 (已优化: 批量预加载版本数据)

        sort: rating | downloads | name | newest | update
        """
        query = select(Plugin)

        if category:
            query = query.where(Plugin.category == category)
        if status:
            query = query.where(Plugin.status == status)
        if installed_only and user_id is None:
            query = query.where(Plugin.is_installed == True)  # noqa: E712
        if search:
            query = query.where(
                Plugin.name.contains(search) |
                Plugin.description.contains(search) |
                Plugin.tags.contains(search)
            )

        order_col = {
            "rating": Plugin.rating_avg.desc(),
            "downloads": Plugin.downloads.desc(),
            "name": Plugin.name.asc(),
            "newest": Plugin.created_at.desc(),
        }.get(sort, Plugin.created_at.desc())

        result = await self.db.execute(query.order_by(order_col))
        plugins = result.scalars().all()

        installations: dict[int, PluginInstallation] = {}
        if user_id is not None and plugins:
            installation_result = await self.db.execute(
                select(PluginInstallation)
                .where(PluginInstallation.user_id == user_id)
                .order_by(
                    PluginInstallation.state_changed_at.desc(),
                    PluginInstallation.installed_at.desc(),
                    PluginInstallation.id.desc(),
                )
            )
            for installation in installation_result.scalars().all():
                installations.setdefault(installation.plugin_id, installation)

        # 批量预加载所有版本数据 (解决N+1问题)
        plugin_ids = [p.id for p in plugins]
        versions_map = await self._batch_load_versions(plugin_ids)

        items = [
            self._plugin_to_dict_fast(
                p,
                versions_map.get(p.id, []),
                installations.get(p.id),
                user_scoped=user_id is not None,
            )
            for p in plugins
        ]
        if installed_only and user_id is not None:
            items = [item for item in items if item["is_installed"]]
        if update_available_only:
            items = [p for p in items if p.get("update_available")]

        return items

    async def _batch_load_versions(self, plugin_ids: list[int]) -> dict[int, list[dict]]:
        """批量加载多个插件的版本数据 (1次查询)"""
        if not plugin_ids:
            return {}

        result = await self.db.execute(
            select(PluginVersion)
            .where(PluginVersion.plugin_id.in_(plugin_ids))
            .order_by(PluginVersion.created_at.desc())
        )
        all_versions = result.scalars().all()

        # 按 plugin_id 分组
        versions_map: dict[int, list[dict]] = {}
        for v in all_versions:
            if v.plugin_id not in versions_map:
                versions_map[v.plugin_id] = []
            versions_map[v.plugin_id].append({
                "id": v.id,
                "version": v.version,
                "release_date": v.release_date,
                "changelog": v.changelog,
                "size_mb": v.size_mb,
                "download_url": v.download_url,
                "is_latest": bool(v.is_latest),
                "is_active": bool(v.is_active),
            })
        return versions_map

    def _plugin_to_dict_fast(
        self,
        plugin: Plugin,
        versions: list[dict],
        installation: PluginInstallation | None = None,
        user_scoped: bool = False,
    ) -> dict:
        """优化版: 使用预加载版本数据构造插件字典"""
        market_latest = plugin.latest_version or _latest_of(versions) or plugin.version

        selected_version = (
            installation.version if installation and installation.version else plugin.version
        )
        lifecycle_state = installation.status if installation else "discovered"
        flags = state_flags(installation.status if installation else None)
        return {
            "id": plugin.id,
            "name": plugin.name,
            "version": selected_version,
            "latest_version": market_latest,
            "update_available": bool(installation and market_latest != selected_version),
            "description": plugin.description,
            "author": plugin.author,
            "category": plugin.category,
            "tags": plugin.tags or [],
            "icon": plugin.icon,
            "license": plugin.license,
            "source_url": plugin.source_url,
            "homepage": plugin.homepage,
            "docs_url": plugin.docs_url,
            "support_email": plugin.support_email,
            "dependencies": plugin.dependencies or [],
            "downloads": plugin.downloads or 0,
            "rating_avg": round(plugin.rating_avg or 0, 1),
            "rating_count": plugin.rating_count or 0,
            "os_compatibility": plugin.os_compatibility or [],
            "install_method": plugin.install_method or {"method": "manual"},
            "is_installed": flags["is_deployed"] if user_scoped else False,
            "status": lifecycle_state if user_scoped else plugin.status,
            "lifecycle_state": lifecycle_state,
            **flags,
            "manifest_schema_version": plugin.manifest_schema_version or "1.0",
            "manifest_digest": plugin.manifest_digest,
            "source_registry": plugin.source_registry or "builtin",
            "source_identifier": plugin.source_identifier or plugin.name,
            "source_synced_at": (
                plugin.source_synced_at.isoformat() if plugin.source_synced_at else None
            ),
            "trust_status": plugin.trust_status or "unreviewed",
            "config_schema": plugin.config_schema or {},
            "created_at": plugin.created_at.isoformat() if plugin.created_at else None,
            "updated_at": plugin.updated_at.isoformat() if plugin.updated_at else None,
        }

    async def get_plugin(
        self, plugin_id: int, user_id: int | None = None
    ) -> dict | None:
        """获取插件详情 (含版本历史与评分摘要)"""
        result = await self.db.execute(select(Plugin).where(Plugin.id == plugin_id))
        plugin = result.scalar_one_or_none()
        if not plugin:
            return None
        data = await self._plugin_to_dict(plugin)
        if user_id is not None:
            installation_result = await self.db.execute(
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
            installation = installation_result.scalars().first()
            lifecycle_state = installation.status if installation else "discovered"
            flags = state_flags(installation.status if installation else None)
            data.update(flags)
            data["is_installed"] = flags["is_deployed"]
            data["status"] = lifecycle_state
            data["lifecycle_state"] = lifecycle_state
            if installation and installation.version:
                data["version"] = installation.version
            data["update_available"] = bool(
                installation and data["latest_version"] != data["version"]
            )
        data["versions"] = await self.list_versions(plugin_id)
        data["rating_summary"] = await self.rating_summary(plugin_id)
        data.setdefault("os_compatibility", [])
        manifest = validated_manifest_for_plugin(plugin)
        data["manifest"] = manifest.model_dump(mode="json")
        data["manifest_digest"] = plugin.manifest_digest or manifest_digest(manifest)
        return data

    async def get_plugin_by_name(
        self, name: str, user_id: int | None = None
    ) -> dict | None:
        """按名称获取插件"""
        result = await self.db.execute(select(Plugin).where(Plugin.name == name))
        plugin = result.scalar_one_or_none()
        return await self.get_plugin(plugin.id, user_id=user_id) if plugin else None

    async def search_plugins(self, query_str: str) -> list[dict]:
        """搜索插件 (名称/描述/标签)"""
        result = await self.db.execute(
            select(Plugin).where(
                (Plugin.name.contains(query_str)) |
                (Plugin.description.contains(query_str)) |
                (Plugin.tags.contains(query_str))
            )
        )
        plugins = result.scalars().all()
        return [await self._plugin_to_dict(p) for p in plugins]

    async def list_categories(self) -> list[dict[str, Any]]:
        """分类浏览: 分类名 + 计数"""
        result = await self.db.execute(
            select(Plugin.category, func.count(Plugin.id)).group_by(Plugin.category)
        )
        rows = result.all()
        return [{"category": c, "count": n} for c, n in rows]

    async def _plugin_to_dict(self, plugin: Plugin) -> dict:
        """插件转字典 (含市场信息)"""
        versions = None
        try:
            versions = await self.list_versions(plugin.id)
        except Exception:
            versions = []
        market_latest = plugin.latest_version or _latest_of(versions) or plugin.version

        return {
            "id": plugin.id,
            "name": plugin.name,
            "version": plugin.version,
            "latest_version": market_latest,
            "update_available": bool(market_latest != plugin.version),
            "description": plugin.description,
            "author": plugin.author,
            "category": plugin.category,
            "tags": plugin.tags or [],
            "icon": plugin.icon,
            "license": plugin.license,
            "source_url": plugin.source_url,
            "homepage": plugin.homepage,
            "docs_url": plugin.docs_url,
            "support_email": plugin.support_email,
            "dependencies": plugin.dependencies or [],
            "downloads": plugin.downloads or 0,
            "rating_avg": round(plugin.rating_avg or 0, 1),
            "rating_count": plugin.rating_count or 0,
            "os_compatibility": plugin.os_compatibility or [],
            "install_method": plugin.install_method or {"method": "manual"},
            "is_installed": False,
            "status": plugin.status,
            "lifecycle_state": "discovered",
            **state_flags(None),
            "manifest_schema_version": plugin.manifest_schema_version or "1.0",
            "manifest_digest": plugin.manifest_digest,
            "source_registry": plugin.source_registry or "builtin",
            "source_identifier": plugin.source_identifier or plugin.name,
            "source_synced_at": (
                plugin.source_synced_at.isoformat() if plugin.source_synced_at else None
            ),
            "trust_status": plugin.trust_status or "unreviewed",
            "config_schema": plugin.config_schema or {},
            "created_at": plugin.created_at.isoformat() if plugin.created_at else None,
            "updated_at": plugin.updated_at.isoformat() if plugin.updated_at else None,
        }

    # ---------- 安装 / 卸载 ----------

    async def _legacy_install_plugin(self, request: dict[str, Any]) -> dict:
        """安装插件 (保持兼容旧接口，标记已安装)"""
        plugin_id = request.get("plugin_id")
        config = request.get("config", {})
        version = request.get("version")  # 可选: 指定版本
        user_id = request.get("user_id")  # 当前用户ID

        result = await self.db.execute(select(Plugin).where(Plugin.id == plugin_id))
        plugin = result.scalar_one_or_none()

        if not plugin:
            raise ValueError(f"Plugin not found: {plugin_id}")

        selected_version = version or plugin.version
        if version:
            version_result = await self.db.execute(
                select(PluginVersion).where(
                    PluginVersion.plugin_id == plugin_id,
                    PluginVersion.version == version,
                    PluginVersion.is_active == True,  # noqa: E712
                )
            )
            if version_result.scalar_one_or_none() is None:
                raise ValueError(f"版本不可用: {version}")

        # 创建安装记录
        existing_installation = None
        if user_id is not None:
            existing_result = await self.db.execute(
                select(PluginInstallation)
                .where(
                    PluginInstallation.plugin_id == plugin_id,
                    PluginInstallation.user_id == user_id,
                )
                .order_by(PluginInstallation.installed_at.desc())
            )
            existing_installation = existing_result.scalars().first()
        if existing_installation:
            existing_installation.version = selected_version
            existing_installation.config = config
            existing_installation.status = "installed"
            existing_installation.error_message = None
            existing_installation.installed_at = datetime.now()
        else:
            self.db.add(PluginInstallation(
                plugin_id=plugin_id,
                user_id=user_id,
                version=selected_version,
                config=config,
                status="installed",
            ))

        # 更新插件状态
        await self.db.execute(
            update(Plugin)
            .where(Plugin.id == plugin_id)
            .values(is_installed=True, status="enabled", installed_at=datetime.now(),
                    installed_by=user_id,
                    downloads=Plugin.downloads + 1)
        )

        await self.db.commit()
        logger.info(f"Plugin installed: {plugin.name} v{selected_version}")

        await self.db.refresh(plugin)
        if user_id is not None:
            return await self.get_plugin(plugin_id, user_id=user_id)
        data = await self._plugin_to_dict(plugin)
        data["is_installed"] = True
        data["status"] = "enabled"
        return data

    async def select_plugin(self, request: dict[str, Any]) -> dict:
        """Select a catalog entry without claiming software is deployed."""
        plugin_id = request.get("plugin_id")
        config = request.get("config", {})
        version = request.get("version")
        user_id = request.get("user_id")
        result = await self.db.execute(select(Plugin).where(Plugin.id == plugin_id))
        plugin = result.scalar_one_or_none()
        if not plugin:
            raise ValueError(f"Plugin not found: {plugin_id}")
        selected_version = version or plugin.version
        if version:
            version_result = await self.db.execute(
                select(PluginVersion).where(
                    PluginVersion.plugin_id == plugin_id,
                    PluginVersion.version == version,
                    PluginVersion.is_active == True,  # noqa: E712
                )
            )
            if version_result.scalar_one_or_none() is None:
                raise ValueError(f"Plugin version is not available: {version}")
        current = await latest_installation(self.db, plugin_id, user_id)
        if current and current.status not in {DESELECTED, ERROR, "uninstalled"}:
            if current.version == selected_version:
                return await self.get_plugin(plugin_id, user_id=user_id)
            if current.status in INSTALLED_STATES:
                raise ValueError(
                    "A deployed plugin version cannot be switched without redeployment"
                )
        await transition(
            self.db,
            plugin_id,
            user_id,
            SELECTED,
            version=selected_version,
            config=config,
            provenance={"event": "catalog_selected"},
        )
        await self.db.commit()
        logger.info(f"Plugin selected: {plugin.name} v{selected_version}")
        return await self.get_plugin(plugin_id, user_id=user_id)

    async def _legacy_uninstall_plugin(self, plugin_id: int, user_id: int | None = None):
        """卸载插件"""
        result = await self.db.execute(select(Plugin).where(Plugin.id == plugin_id))
        plugin = result.scalar_one_or_none()

        if not plugin:
            raise ValueError(f"Plugin not found: {plugin_id}")

        if user_id is not None:
            await self.db.execute(
                update(PluginInstallation)
                .where(
                    PluginInstallation.plugin_id == plugin_id,
                    PluginInstallation.user_id == user_id,
                    PluginInstallation.status == "installed",
                )
                .values(status="uninstalled")
            )
            remaining = await self.db.scalar(
                select(func.count(PluginInstallation.id)).where(
                    PluginInstallation.plugin_id == plugin_id,
                    PluginInstallation.status == "installed",
                )
            )
            if not remaining:
                await self.db.execute(
                    update(Plugin).where(Plugin.id == plugin_id)
                    .values(is_installed=False, status="available")
                )
        else:
            await self.db.execute(
                update(Plugin)
                .where(Plugin.id == plugin_id)
                .values(is_installed=False, status="available")
            )

        await self.db.commit()
        logger.info(f"Plugin uninstalled: {plugin.name}")
        await self.db.refresh(plugin)

    async def deselect_plugin(
        self, plugin_id: int, user_id: int | None = None
    ) -> dict:
        """Remove a selection; physical environments require explicit removal."""
        plugin = await self.get_plugin(plugin_id, user_id=user_id)
        if not plugin:
            raise ValueError(f"Plugin not found: {plugin_id}")
        current = await latest_installation(self.db, plugin_id, user_id)
        if not current or current.status in {DESELECTED, "uninstalled"}:
            return plugin
        if current.status in INSTALLED_STATES:
            raise ValueError(
                "Plugin has a deployed environment; disable or remove that environment first"
            )
        await transition(
            self.db,
            plugin_id,
            user_id,
            DESELECTED,
            provenance={"event": "catalog_deselected"},
        )
        await self.db.commit()
        return await self.get_plugin(plugin_id, user_id=user_id)

    async def set_enabled(
        self, plugin_id: int, user_id: int | None, enabled: bool
    ) -> dict:
        current = await latest_installation(self.db, plugin_id, user_id)
        if not current:
            raise ValueError("Plugin has not been selected or deployed")
        target = ENABLED if enabled else DISABLED
        await transition(
            self.db,
            plugin_id,
            user_id,
            target,
            provenance={"event": "enabled" if enabled else "disabled"},
        )
        await self.db.commit()
        return await self.get_plugin(plugin_id, user_id=user_id)

    async def install_plugin(self, request: dict[str, Any]) -> dict:
        """Compatibility alias: marketplace install now means selection only."""
        return await self.select_plugin(request)

    async def uninstall_plugin(
        self, plugin_id: int, user_id: int | None = None
    ) -> dict:
        """Compatibility alias: remove a marketplace selection only."""
        return await self.deselect_plugin(plugin_id, user_id=user_id)

    async def get_installed_plugins(
        self, user_id: int | None = None
    ) -> list[dict]:
        """Return plugins backed by a deployed environment for this user."""
        latest_by_plugin = await latest_installations_for_user(self.db, user_id)
        items: list[dict] = []
        for plugin_id, installation in latest_by_plugin.items():
            if installation.status not in INSTALLED_STATES:
                continue
            plugin = await self.get_plugin(plugin_id, user_id=user_id)
            if plugin:
                items.append(plugin)
        return items

    async def update_plugin(self, plugin_id: int, update_data: dict) -> dict | None:
        """更新插件"""
        result = await self.db.execute(select(Plugin).where(Plugin.id == plugin_id))
        plugin = result.scalar_one_or_none()

        if not plugin:
            return None

        for key, value in update_data.items():
            if hasattr(plugin, key):
                setattr(plugin, key, value)

        plugin.updated_at = datetime.now()
        await self.db.commit()
        await self.db.refresh(plugin)

        return await self._plugin_to_dict(plugin)

    async def _legacy_get_installed_plugins(self) -> list[dict]:
        """获取已安装插件"""
        result = await self.db.execute(
            select(Plugin).where(Plugin.is_installed)
        )
        plugins = result.scalars().all()
        return [await self._plugin_to_dict(p) for p in plugins]

    # ---------- 版本控制 ----------

    async def list_versions(self, plugin_id: int) -> list[dict[str, Any]]:
        """获取插件版本历史"""
        result = await self.db.execute(
            select(PluginVersion)
            .where(PluginVersion.plugin_id == plugin_id)
            .order_by(PluginVersion.created_at.desc())
        )
        versions = result.scalars().all()
        return [{
            "id": v.id,
            "version": v.version,
            "release_date": v.release_date,
            "changelog": v.changelog,
            "size_mb": v.size_mb,
            "download_url": v.download_url,
            "is_latest": bool(v.is_latest),
            "is_active": bool(v.is_active),
        } for v in versions]

    async def add_version(self, plugin_id: int, version_data: dict) -> dict | None:
        """注册一个新版本 (升级发布)"""
        result = await self.db.execute(select(Plugin).where(Plugin.id == plugin_id))
        plugin = result.scalar_one_or_none()
        if not plugin:
            return None

        version = version_data.get("version", "")
        if not version:
            raise ValueError("version required")

        exists = await self.db.execute(
            select(PluginVersion).where(
                PluginVersion.plugin_id == plugin_id,
                PluginVersion.version == version,
            )
        )
        if exists.scalar_one_or_none():
            return await self.get_plugin(plugin_id)  # 幂等: 已存在则原样返回

        # 取消旧版本的 is_latest 标记
        await self.db.execute(
            update(PluginVersion)
            .where(PluginVersion.plugin_id == plugin_id)
            .values(is_latest=False)
        )

        new_version = PluginVersion(
            plugin_id=plugin_id,
            version=version,
            release_date=version_data.get("release_date", datetime.now().strftime("%Y-%m-%d")),
            changelog=version_data.get("changelog"),
            size_mb=version_data.get("size_mb"),
            download_url=version_data.get("download_url"),
            is_latest=True,
        )
        self.db.add(new_version)

        # 同步插件最新版本
        plugin.latest_version = version
        await self.db.commit()
        logger.info(f"Plugin {plugin.name}: new version {version} registered")
        return await self.get_plugin(plugin_id)

    async def switch_version(
        self, plugin_id: int, version: str, user_id: int | None = None
    ) -> bool:
        """切换插件版本 (版本回滚)"""
        result = await self.db.execute(
            select(PluginVersion).where(
                PluginVersion.plugin_id == plugin_id,
                PluginVersion.version == version,
                PluginVersion.is_active,
            )
        )
        ver = result.scalar_one_or_none()
        if not ver:
            return False

        if user_id is not None:
            installation = await latest_installation(self.db, plugin_id, user_id)
            if not installation or installation.status != SELECTED:
                return False
            await transition(
                self.db,
                plugin_id,
                user_id,
                SELECTED,
                version=version,
                config=installation.config or {},
                provenance={"event": "selected_version_changed"},
                force=True,
            )
        else:
            await self.db.execute(
                update(Plugin).where(Plugin.id == plugin_id).values(version=version)
            )
        await self.db.commit()
        logger.info(f"Plugin {plugin_id}: switched to v{version}")
        return True

    async def remove_version(self, plugin_id: int, version: str) -> bool:
        """删除一个版本 (撤回发布)；不允许删除当前使用中的版本"""
        result = await self.db.execute(select(Plugin).where(Plugin.id == plugin_id))
        plugin = result.scalar_one_or_none()
        if not plugin:
            return False
        if plugin.version == version:
            raise ValueError("不能删除当前使用中的版本")

        result = await self.db.execute(
            delete(PluginVersion).where(
                PluginVersion.plugin_id == plugin_id,
                PluginVersion.version == version,
            )
        )
        await self.db.commit()
        return bool(result.rowcount)

    # ---------- 更新机制 ----------

    async def check_updates(
        self, plugin_id: int | None = None, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """检查可用的版本更新"""
        query = select(Plugin)
        if plugin_id is not None:
            query = query.where(Plugin.id == plugin_id)
        result = await self.db.execute(query)
        plugins = result.scalars().all()

        installed_versions: dict[int, str] = {}
        if user_id is not None:
            installation_query = select(PluginInstallation).where(
                PluginInstallation.user_id == user_id,
                PluginInstallation.status.notin_({DESELECTED, "uninstalled", ERROR}),
            )
            if plugin_id is not None:
                installation_query = installation_query.where(
                    PluginInstallation.plugin_id == plugin_id
                )
            installation_result = await self.db.execute(
                installation_query.order_by(
                    PluginInstallation.state_changed_at.desc(),
                    PluginInstallation.installed_at.desc(),
                    PluginInstallation.id.desc(),
                )
            )
            for installation in installation_result.scalars().all():
                installed_versions.setdefault(
                    installation.plugin_id, installation.version or ""
                )

        updates = []
        for p in plugins:
            current_version = (
                installed_versions.get(p.id) if user_id is not None else p.version
            )
            is_selected = p.id in installed_versions if user_id is not None else False
            if is_selected and p.latest_version and p.latest_version != current_version:
                v_result = await self.db.execute(
                    select(PluginVersion).where(
                        PluginVersion.plugin_id == p.id,
                        PluginVersion.version == p.latest_version,
                    )
                )
                ver = v_result.scalar_one_or_none()
                updates.append({
                    "plugin_id": p.id,
                    "name": p.name,
                    "current_version": current_version,
                    "latest_version": p.latest_version,
                    "changelog": ver.changelog if ver else "",
                    "release_date": ver.release_date if ver else "",
                })
        return updates

    async def upgrade_plugin(
        self,
        plugin_id: int,
        target_version: str | None = None,
        user_id: int | None = None,
    ) -> dict:
        """升级插件到最新版 (或指定版本)"""
        result = await self.db.execute(select(Plugin).where(Plugin.id == plugin_id))
        plugin = result.scalar_one_or_none()
        if not plugin:
            raise ValueError(f"Plugin not found: {plugin_id}")

        installation = None
        current_version = plugin.version
        if user_id is not None:
            installation = await latest_installation(self.db, plugin_id, user_id)
            if not installation:
                raise ValueError("Plugin is not selected for this user")
            current_version = installation.version or plugin.version

        target = target_version or plugin.latest_version
        if not target or target == current_version:
            return {
                "plugin_id": plugin_id,
                "name": plugin.name,
                "current_version": current_version,
                "target_version": target,
                "upgraded": False,
                "message": "已是最新版本",
            }

        # 校验目标版本存在
        v_result = await self.db.execute(
            select(PluginVersion).where(
                PluginVersion.plugin_id == plugin_id,
                PluginVersion.version == target,
            )
        )
        ver = v_result.scalar_one_or_none()
        if ver is None or not ver.is_active:
            raise ValueError(f"Plugin version is not available: {target}")

        old_version = current_version
        if installation is not None and installation.status in INSTALLED_STATES:
            return {
                "plugin_id": plugin_id,
                "name": plugin.name,
                "current_version": old_version,
                "target_version": target,
                "changelog": ver.changelog if ver else "",
                "upgraded": False,
                "requires_redeploy": True,
                "message": "A deployed plugin must be redeployed to change version",
            }
        if installation is not None:
            await transition(
                self.db,
                plugin_id,
                user_id,
                SELECTED,
                version=target,
                config={**(installation.config or {}), "upgraded_from": old_version},
                provenance={"event": "selected_version_upgraded"},
                force=True,
            )
        else:
            await self.db.execute(
                update(Plugin).where(Plugin.id == plugin_id).values(version=target)
            )
            await transition(
                self.db,
                plugin_id,
                user_id,
                SELECTED,
                version=target,
                config={"upgraded_from": old_version},
                provenance={"event": "selected_version_upgraded"},
            )
        await self.db.commit()
        logger.info(f"Plugin {plugin.name}: {old_version} -> {target}")

        return {
            "plugin_id": plugin_id,
            "name": plugin.name,
            "current_version": old_version,
            "target_version": target,
            "changelog": ver.changelog if ver else "",
            "upgraded": True,
            "message": f"已升级: {old_version} -> {target}",
        }

    # ---------- 用户评价 ----------

    async def add_review(self, plugin_id: int, rating: int, comment: str | None = None,
                         user_id: int | None = None) -> dict:
        """添加用户评价"""
        if not (1 <= rating <= 5):
            raise ValueError("评分必须在 1-5 之间")

        result = await self.db.execute(select(Plugin).where(Plugin.id == plugin_id))
        plugin = result.scalar_one_or_none()
        if not plugin:
            raise ValueError(f"Plugin not found: {plugin_id}")

        installation = await latest_installation(self.db, plugin_id, user_id)
        review = PluginReview(
            plugin_id=plugin_id,
            user_id=user_id,
            rating=rating,
            comment=comment,
            is_verified=bool(
                installation and installation.status in VERIFIED_STATES
            ),
        )
        self.db.add(review)
        await self.db.flush()

        # 重新聚合评分
        agg = await self.db.execute(
            select(func.avg(PluginReview.rating), func.count(PluginReview.id))
            .where(PluginReview.plugin_id == plugin_id)
        )
        avg, cnt = agg.one()
        await self.db.execute(
            update(Plugin).where(Plugin.id == plugin_id)
            .values(rating_avg=round(float(avg or 0), 2), rating_count=int(cnt or 0))
        )
        await self.db.commit()

        return {
            "id": review.id,
            "plugin_id": plugin_id,
            "rating": rating,
            "comment": comment,
            "is_verified": review.is_verified,
            "created_at": review.created_at.isoformat() if review.created_at else None,
        }

    async def list_reviews(self, plugin_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """获取插件评价列表"""
        result = await self.db.execute(
            select(PluginReview)
            .where(PluginReview.plugin_id == plugin_id)
            .order_by(PluginReview.created_at.desc())
            .limit(limit)
        )
        reviews = result.scalars().all()
        return [{
            "id": r.id,
            "plugin_id": r.plugin_id,
            "rating": r.rating,
            "comment": r.comment,
            "is_verified": bool(r.is_verified),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in reviews]

    async def remove_review(
        self,
        plugin_id: int,
        review_id: int,
        user_id: int | None = None,
    ) -> bool:
        """删除评价并重新聚合评分"""
        conditions = [
            PluginReview.id == review_id,
            PluginReview.plugin_id == plugin_id,
        ]
        if user_id is not None:
            conditions.append(PluginReview.user_id == user_id)
        result = await self.db.execute(delete(PluginReview).where(*conditions))
        if not result.rowcount:
            return False

        agg = await self.db.execute(
            select(func.avg(PluginReview.rating), func.count(PluginReview.id))
            .where(PluginReview.plugin_id == plugin_id)
        )
        avg, cnt = agg.one()
        await self.db.execute(
            update(Plugin).where(Plugin.id == plugin_id)
            .values(rating_avg=round(float(avg or 0), 2), rating_count=int(cnt or 0))
        )
        await self.db.commit()
        return True

    async def rating_summary(self, plugin_id: int) -> dict[str, Any]:
        """评分分布汇总"""
        result = await self.db.execute(
            select(PluginReview.rating, func.count(PluginReview.id))
            .where(PluginReview.plugin_id == plugin_id)
            .group_by(PluginReview.rating)
        )
        dist = {str(r): c for r, c in result.all()}
        total = sum(dist.values())
        return {
            "avg": round(sum(int(k) * v for k, v in dist.items()) / total, 2) if total else 0.0,
            "count": total,
            "distribution": {str(i): dist.get(str(i), 0) for i in range(1, 6)},
        }

    # ---------- 部署历史 ----------

    async def get_deploy_history(self, plugin_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """获取插件部署/安装历史"""
        result = await self.db.execute(
            select(PluginInstallation)
            .where(PluginInstallation.plugin_id == plugin_id)
            .order_by(PluginInstallation.installed_at.desc())
            .limit(limit)
        )
        records = result.scalars().all()
        return [{
            "id": r.id,
            "version": r.version,
            "status": r.status,
            "error_message": r.error_message,
            "installed_at": r.installed_at.isoformat() if r.installed_at else None,
        } for r in records]


__all__ = ["PluginManager"]
