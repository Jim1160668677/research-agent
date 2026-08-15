"""API routes for plugin market - 工具插件市场

功能端点:
- GET    /plugins/                  列表 (搜索/分类/排序/已安装/可更新)
- GET    /plugins/categories       分类浏览
- GET    /plugins/updates          版本更新检测
- GET    /plugins/{id}             详情 (含版本历史/评分)
- POST   /plugins/install          安装
- DELETE /plugins/{id}             卸载
- PUT    /plugins/{id}             更新元数据
- GET    /plugins/{id}/versions    版本历史
- POST   /plugins/{id}/versions    注册新版本
- POST   /plugins/{id}/versions/{version}/switch   切换版本
- GET    /plugins/{id}/reviews     评价列表
- POST   /plugins/{id}/reviews     提交评价
- GET    /plugins/{id}/dependencies   依赖解析
- POST   /plugins/{id}/deploy      一键部署 (simulate=1 生成计划)
- GET    /plugins/{id}/deploy/history   部署历史
- POST   /plugins/{id}/verify      验证真实安装
- POST   /plugins/{id}/upgrade     升级到最新版
"""


from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...plugins.catalog_sync import BiocondaCatalogSync
from ...plugins.dependency_resolver import DependencyResolver
from ...plugins.deployer import Deployer
from ...plugins.manager import PluginManager
from ...plugins.manifest import (
    CapabilityManifestV1,
    manifest_digest,
    validated_manifest_for_plugin,
)
from ...plugins.platform_probe import PlatformCapabilityProbe
from ..auth import get_current_user, require_role
from ..db import get_db
from ..models.db import Plugin as PluginModel
from ..models.schemas import (
    PluginInstallRequest,
    PluginResponse,
    PluginReviewCreate,
    PluginUpdate,
)

router = APIRouter()


class PluginUpgradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_version: str | None = None


class PluginDeployRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulate: bool = True


class PluginSmokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smoke_id: str | None = None


class BiocondaSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packages: list[str] = Field(
        default_factory=lambda: ["fastqc", "samtools", "bwa", "fastp", "bowtie2"],
        min_length=1,
        max_length=100,
    )
    subdirs: list[str] = Field(
        default_factory=lambda: ["linux-64", "noarch"],
        min_length=1,
        max_length=5,
    )
    allow_cached_on_error: bool = True


@router.get("/manifest/schema")
async def capability_manifest_schema(
    current_user: dict = Depends(get_current_user),
):
    """Return the stable JSON Schema for third-party capability manifests."""
    return CapabilityManifestV1.model_json_schema()


@router.post("/manifest/validate")
async def validate_capability_manifest(
    manifest: CapabilityManifestV1,
    current_user: dict = Depends(get_current_user),
):
    return {
        "valid": True,
        "schema_version": manifest.schema_version,
        "digest": manifest_digest(manifest),
        "manifest": manifest.model_dump(mode="json"),
    }


@router.post("/catalogs/bioconda/sync")
async def sync_bioconda_catalog(
    request: BiocondaSyncRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    service = BiocondaCatalogSync(db, current_user["user_id"])
    try:
        return await service.sync(
            request.packages,
            request.subdirs,
            allow_cached_on_error=request.allow_cached_on_error,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"Bioconda catalog sync failed: {exc}")
        raise HTTPException(status_code=502, detail=f"Bioconda sync failed: {exc}") from exc


@router.get("/catalogs/bioconda/history")
async def bioconda_sync_history(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    return {
        "registry": "bioconda",
        "history": await BiocondaCatalogSync(
            db, current_user["user_id"]
        ).history(limit),
    }


@router.get("/platform/capabilities")
async def platform_capabilities(
    deep: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    if deep and current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Deep platform probing requires the admin role",
        )
    return await PlatformCapabilityProbe().probe(deep=deep)


@router.get("/", response_model=list[PluginResponse])
async def list_plugins(
    category: str | None = Query(None, description="按分类筛选"),
    status: str | None = Query(None, description="按状态筛选"),
    search: str | None = Query(None, description="搜索关键词"),
    sort: str | None = Query(None, description="排序: rating/downloads/name/newest"),
    installed_only: bool = Query(False, description="只看已安装"),
    update_available_only: bool = Query(False, description="只看有更新的"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取插件列表"""
    manager = PluginManager(db)
    plugins = await manager.list_plugins(
        category=category, status=status, search=search,
        sort=sort, installed_only=installed_only,
        update_available_only=update_available_only,
        user_id=current_user["user_id"],
    )
    return plugins


@router.get("/categories")
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """分类浏览带计数"""
    manager = PluginManager(db)
    return await manager.list_categories()


@router.get("/updates")
async def list_updates(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """版本更新检测 - 返回有可用更新的插件"""
    manager = PluginManager(db)
    updates = await manager.check_updates(user_id=current_user["user_id"])
    return {"updates": updates}


@router.get("/{plugin_id}")
async def get_plugin_detail(
    plugin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取插件详情 (含版本历史/评分/依赖)"""
    manager = PluginManager(db)
    plugin = await manager.get_plugin(plugin_id, user_id=current_user["user_id"])
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin


@router.get("/{plugin_id}/manifest")
async def get_plugin_manifest(
    plugin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(PluginModel).where(PluginModel.id == plugin_id))
    plugin = result.scalar_one_or_none()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    manifest = validated_manifest_for_plugin(plugin)
    return {
        "plugin_id": plugin_id,
        "schema_version": manifest.schema_version,
        "digest": plugin.manifest_digest or manifest_digest(manifest),
        "manifest": manifest.model_dump(mode="json"),
    }


@router.post("/install", response_model=PluginResponse)
async def install_plugin(
    request: PluginInstallRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """安装插件 (标记安装，可选指定版本)"""
    manager = PluginManager(db)
    try:
        payload = request.model_dump()
        payload["user_id"] = current_user["user_id"]
        plugin = await manager.select_plugin(payload)
        return plugin
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{plugin_id}")
async def uninstall_plugin(
    plugin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """卸载插件"""
    manager = PluginManager(db)
    try:
        plugin = await manager.deselect_plugin(
            plugin_id, user_id=current_user["user_id"]
        )
        return {"status": "ok", "plugin": plugin}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/{plugin_id}", response_model=PluginResponse)
async def update_plugin(
    plugin_id: int,
    update: PluginUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """更新插件元数据"""
    manager = PluginManager(db)
    plugin = await manager.update_plugin(plugin_id, update.model_dump(exclude_unset=True))
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin


@router.post("/{plugin_id}/enable")
async def enable_plugin(
    plugin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    manager = PluginManager(db)
    try:
        return await manager.set_enabled(plugin_id, current_user["user_id"], True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{plugin_id}/disable")
async def disable_plugin(
    plugin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    manager = PluginManager(db)
    try:
        return await manager.set_enabled(plugin_id, current_user["user_id"], False)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ========== 版本控制 ==========

@router.get("/{plugin_id}/versions")
async def list_versions(
    plugin_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取插件版本历史"""
    manager = PluginManager(db)
    versions = await manager.list_versions(plugin_id)
    return {"plugin_id": plugin_id, "versions": versions}


@router.post("/{plugin_id}/versions")
async def add_version(
    plugin_id: int,
    version_data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """注册新版本 (升级发布)"""
    manager = PluginManager(db)
    try:
        plugin = await manager.add_version(plugin_id, version_data)
        if not plugin:
            raise HTTPException(status_code=404, detail="Plugin not found")
        return plugin
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{plugin_id}/versions/{version}/switch")
async def switch_version(
    plugin_id: int,
    version: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """切换插件版本 (版本回滚/选择)"""
    manager = PluginManager(db)
    ok = await manager.switch_version(
        plugin_id, version, user_id=current_user["user_id"]
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"版本不可用: {version}")
    return {"status": "ok", "plugin_id": plugin_id, "version": version}


@router.delete("/{plugin_id}/versions/{version}")
async def remove_version(
    plugin_id: int,
    version: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """删除版本 (撤回发布)"""
    manager = PluginManager(db)
    try:
        ok = await manager.remove_version(plugin_id, version)
        if not ok:
            raise HTTPException(status_code=404, detail="版本不存在")
        return {"status": "ok", "plugin_id": plugin_id, "version": version}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{plugin_id}/upgrade")
async def upgrade_plugin(
    plugin_id: int,
    body: PluginUpgradeRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """升级插件到最新版 (或指定版本)"""
    manager = PluginManager(db)
    try:
        result = await manager.upgrade_plugin(
            plugin_id,
            body.target_version if body else None,
            user_id=current_user["user_id"],
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ========== 用户评价 ==========

@router.get("/{plugin_id}/reviews")
async def list_reviews(
    plugin_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """获取插件评价列表"""
    manager = PluginManager(db)
    reviews = await manager.list_reviews(plugin_id, limit)
    summary = await manager.rating_summary(plugin_id)
    return {"plugin_id": plugin_id, "summary": summary, "reviews": reviews}


@router.post("/{plugin_id}/reviews")
async def add_review(
    plugin_id: int,
    review_data: PluginReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """提交用户评价 (rating 1-5, comment 可选)"""
    manager = PluginManager(db)
    try:
        review = await manager.add_review(
            plugin_id,
            rating=review_data.rating,
            comment=review_data.comment,
            user_id=current_user["user_id"],
        )
        return review
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{plugin_id}/reviews/{review_id}")
async def remove_review(
    plugin_id: int,
    review_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除用户评价"""
    manager = PluginManager(db)
    ok = await manager.remove_review(
        plugin_id, review_id, user_id=current_user["user_id"]
    )
    if not ok:
        raise HTTPException(status_code=404, detail="评价不存在")
    return {"status": "ok", "plugin_id": plugin_id, "review_id": review_id}


# ========== 依赖管理 ==========

@router.get("/{plugin_id}/dependencies")
async def resolve_dependencies(
    plugin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """解析插件依赖关系 (传递依赖/循环/冲突/安装顺序)"""
    manager = PluginManager(db)
    async def get_user_plugin(name: str):
        return await manager.get_plugin_by_name(
            name, user_id=current_user["user_id"]
        )

    resolver = DependencyResolver(get_user_plugin)

    plugin = await manager.get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    try:
        result = await resolver.resolve(plugin["name"])
        result["plugin_id"] = plugin_id
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ========== 一键部署 ==========

@router.post("/{plugin_id}/deploy")
async def deploy_plugin(
    plugin_id: int,
    body: PluginDeployRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """一键部署插件

    body.simulate: true 时仅生成安装计划 (dry-run)
    真实执行: 通过 conda/pip 自动安装，或给出手动下载引导
    """
    manager = PluginManager(db)
    deployer = Deployer(db, user_id=current_user["user_id"])

    plugin = await manager.get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    simulate = body.simulate if body else True
    if not simulate and current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Actual plugin deployment requires the admin role",
        )
    # 重新获取 ORM 对象供 deployer 使用
    result = await db.execute(
        select(PluginModel).where(PluginModel.id == plugin_id)
    )
    plugin_obj = result.scalar_one_or_none()
    if not plugin_obj:
        raise HTTPException(status_code=404, detail="Plugin not found")

    try:
        outcome = await deployer.deploy(plugin_obj, simulate=simulate)
        return outcome.to_dict()
    except Exception as e:
        logger.error(f"deploy failed: {e}")
        if not simulate:
            await deployer.record_unhandled_failure(plugin_obj, str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{plugin_id}/deploy/history")
async def deploy_history(
    plugin_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """一键部署历史"""
    deployer = Deployer(db, user_id=current_user["user_id"])
    return {"plugin_id": plugin_id, "history": await deployer.get_deploy_history(plugin_id, limit)}


@router.delete("/{plugin_id}/deployment")
async def remove_plugin_deployment(
    plugin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """Remove the current user's managed isolated environment."""
    result = await db.execute(select(PluginModel).where(PluginModel.id == plugin_id))
    plugin_obj = result.scalar_one_or_none()
    if not plugin_obj:
        raise HTTPException(status_code=404, detail="Plugin not found")
    try:
        return await Deployer(
            db, user_id=current_user["user_id"]
        ).remove_environment(plugin_obj)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{plugin_id}/verify")
async def verify_installation(
    plugin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """验证软件是否真实安装 (探测命令/PATH)"""
    deployer = Deployer(db, user_id=current_user["user_id"])
    result = await db.execute(select(PluginModel).where(PluginModel.id == plugin_id))
    plugin_obj = result.scalar_one_or_none()
    if not plugin_obj:
        raise HTTPException(status_code=404, detail="Plugin not found")
    verification = await deployer.verify_installation(plugin_obj)
    return {"plugin_id": plugin_id, "name": plugin_obj.name, **verification}


@router.post("/{plugin_id}/smoke")
async def run_plugin_smoke(
    plugin_id: int,
    body: PluginSmokeRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """运行插件的断言型冒烟用例（RA-Eval v1）。

    仅限已部署环境的插件；用例经白名单校验，argv-only 受管执行。
    """
    from ...plugins.smoke_runner import SmokeRunner

    result = await db.execute(select(PluginModel).where(PluginModel.id == plugin_id))
    plugin_obj = result.scalar_one_or_none()
    if not plugin_obj:
        raise HTTPException(status_code=404, detail="Plugin not found")
    try:
        return await SmokeRunner(db, user_id=current_user["user_id"]).run(
            plugin_obj, body.smoke_id if body else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{plugin_id}/smoke-history")
async def plugin_smoke_history(
    plugin_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """插件冒烟评测历史（最近 N 条）"""
    from ...plugins.smoke_runner import SmokeRunner

    history = await SmokeRunner(db, user_id=current_user["user_id"]).history(plugin_id, limit)
    return {"plugin_id": plugin_id, "history": history}


__all__ = ["router"]
