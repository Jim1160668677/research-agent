"""Read-only synchronization of trusted bioinformatics package indexes."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx
from packaging.version import InvalidVersion, Version
from sqlalchemy import select, update

from ..core.app import settings
from ..core.models.db import CatalogSync, Plugin, PluginVersion
from .manifest import manifest_digest, manifest_from_plugin


BIOCONDA_BASE = "https://conda.anaconda.org/bioconda"
ALLOWED_SUBDIRS = {"linux-64", "linux-aarch64", "osx-64", "osx-arm64", "noarch"}
_SAFE_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,99}$")
_MAX_REPODATA_BYTES = 128 * 1024 * 1024


def _version_key(value: str):
    try:
        return 1, Version(value)
    except InvalidVersion:
        return 0, value


def _dependency(value: str) -> Dict[str, str]:
    parts = value.strip().split(maxsplit=1)
    return {"name": parts[0], "version": parts[1] if len(parts) > 1 else ""}


class BiocondaCatalogSync:
    """Import metadata from fixed HTTPS repodata URLs; never execute packages."""

    def __init__(
        self,
        db,
        user_id: int,
        *,
        client: Optional[httpx.AsyncClient] = None,
        cache_root: Optional[Path] = None,
    ):
        self.db = db
        self.user_id = user_id
        self.client = client
        self.cache_root = cache_root or self._default_cache_root()

    @staticmethod
    def _default_cache_root() -> Path:
        configured = os.environ.get("RESEARCH_AGENT_DATA_DIR")
        if configured:
            return Path(configured).expanduser().resolve() / "catalog-cache"
        prefix = "sqlite+aiosqlite:///"
        if settings.database_url.startswith(prefix):
            database = Path(settings.database_url[len(prefix):]).expanduser().resolve()
            return database.parent / "catalog-cache"
        return Path.cwd().resolve() / ".research-agent" / "catalog-cache"

    @staticmethod
    def validate_request(
        packages: Iterable[str], subdirs: Iterable[str]
    ) -> tuple[list[str], list[str]]:
        names = list(dict.fromkeys(str(item).strip().lower() for item in packages))
        targets = list(dict.fromkeys(str(item).strip().lower() for item in subdirs))
        if not names or len(names) > 100:
            raise ValueError("Bioconda sync requires between 1 and 100 package names")
        invalid = [item for item in names if not _SAFE_PACKAGE.fullmatch(item)]
        if invalid:
            raise ValueError(f"Invalid Bioconda package name: {invalid[0]}")
        if not targets or any(item not in ALLOWED_SUBDIRS for item in targets):
            raise ValueError("Unsupported Bioconda subdir")
        return names, targets

    async def sync(
        self,
        packages: Iterable[str],
        subdirs: Iterable[str] = ("linux-64", "noarch"),
        *,
        allow_cached_on_error: bool = True,
    ) -> Dict[str, Any]:
        names, targets = self.validate_request(packages, subdirs)
        urls = [f"{BIOCONDA_BASE}/{item}/current_repodata.json" for item in targets]
        sync_record = CatalogSync(
            registry="bioconda",
            user_id=self.user_id,
            status="running",
            source_urls=urls,
            request={"packages": names, "subdirs": targets},
        )
        self.db.add(sync_record)
        await self.db.flush()
        try:
            payloads = []
            cache_states = []
            for subdir, url in zip(targets, urls):
                payload, cache_state, digest = await self._fetch_subdir(
                    subdir, url, allow_cached_on_error
                )
                payloads.append((subdir, payload, digest))
                cache_states.append(cache_state)
            result = await self._apply(names, payloads)
            combined_digest = hashlib.sha256(
                "".join(sorted(item[2] for item in payloads)).encode("ascii")
            ).hexdigest()
            sync_record.status = "completed"
            sync_record.result = result
            sync_record.source_digest = combined_digest
            sync_record.cache_status = ",".join(sorted(set(cache_states)))
            sync_record.completed_at = datetime.now()
            await self.db.commit()
            return {
                "sync_id": sync_record.id,
                "registry": "bioconda",
                "source_urls": urls,
                "source_digest": combined_digest,
                "cache_status": sync_record.cache_status,
                **result,
            }
        except Exception as exc:
            # Keep the catalog atomic: never commit a partially imported index.
            await self.db.rollback()
            failed_record = CatalogSync(
                registry="bioconda",
                user_id=self.user_id,
                status="failed",
                source_urls=urls,
                request={"packages": names, "subdirs": targets},
                error_message=str(exc)[:2000],
                completed_at=datetime.now(),
            )
            self.db.add(failed_record)
            await self.db.commit()
            raise

    async def _fetch_subdir(
        self, subdir: str, url: str, allow_cached_on_error: bool
    ) -> tuple[Dict[str, Any], str, str]:
        self.cache_root.mkdir(parents=True, exist_ok=True)
        data_path = self.cache_root / f"bioconda-{subdir}-current.json"
        meta_path = self.cache_root / f"bioconda-{subdir}-current.meta.json"
        metadata: Dict[str, Any] = {}
        if meta_path.is_file():
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                metadata = {}
        headers = {"Accept": "application/json"}
        if metadata.get("etag"):
            headers["If-None-Match"] = metadata["etag"]
        if metadata.get("last_modified"):
            headers["If-Modified-Since"] = metadata["last_modified"]
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(45.0),
            follow_redirects=True,
            headers={"User-Agent": f"ResearchAgent/{settings.version}"},
        )
        try:
            response = await client.get(url, headers=headers)
            if response.status_code == 304 and data_path.is_file():
                raw = data_path.read_bytes()
                return json.loads(raw), "not_modified", hashlib.sha256(raw).hexdigest()
            response.raise_for_status()
            content_length = int(response.headers.get("content-length") or 0)
            if content_length > _MAX_REPODATA_BYTES or len(response.content) > _MAX_REPODATA_BYTES:
                raise ValueError("Bioconda repodata exceeds the configured safety limit")
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Bioconda repodata root must be an object")
            raw = response.content
            temporary = data_path.with_suffix(".json.tmp")
            temporary.write_bytes(raw)
            temporary.replace(data_path)
            meta = {
                "url": url,
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            meta_tmp = meta_path.with_suffix(".json.tmp")
            meta_tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            meta_tmp.replace(meta_path)
            return payload, "fresh", meta["sha256"]
        except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError):
            if allow_cached_on_error and data_path.is_file():
                raw = data_path.read_bytes()
                return json.loads(raw), "fallback_cache", hashlib.sha256(raw).hexdigest()
            raise
        finally:
            if owns_client:
                await client.aclose()

    async def _apply(
        self,
        requested: List[str],
        payloads: List[tuple[str, Dict[str, Any], str]],
    ) -> Dict[str, Any]:
        records: Dict[str, List[Dict[str, Any]]] = {name: [] for name in requested}
        for subdir, payload, _digest in payloads:
            combined = {**(payload.get("packages") or {}), **(payload.get("packages.conda") or {})}
            for filename, metadata in combined.items():
                if isinstance(metadata, dict) and str(metadata.get("name") or "").lower() in records:
                    name = str(metadata["name"]).lower()
                    records[name].append({**metadata, "filename": filename, "subdir": subdir})

        imported = 0
        updated_count = 0
        missing = []
        now = datetime.now()
        for name in requested:
            candidates = records[name]
            if not candidates:
                missing.append(name)
                continue
            candidates.sort(
                key=lambda item: (
                    _version_key(str(item.get("version") or "0")),
                    int(item.get("build_number") or 0),
                    int(item.get("timestamp") or 0),
                ),
                reverse=True,
            )
            latest = candidates[0]
            latest_version = str(latest.get("version") or "0")
            plugin_result = await self.db.execute(select(Plugin).where(Plugin.name == name))
            plugin = plugin_result.scalar_one_or_none()
            subdir_set = {str(item.get("subdir")) for item in candidates}
            platforms = []
            if any(item.startswith("linux-") for item in subdir_set):
                platforms.append("linux")
            if any(item.startswith("osx-") for item in subdir_set):
                platforms.append("macos")
            if "noarch" in subdir_set:
                platforms.extend(item for item in ("linux", "macos") if item not in platforms)
            summary = {
                "latest_build": latest.get("build"),
                "latest_filename": latest.get("filename"),
                "subdirs": sorted(subdir_set),
                "sha256": latest.get("sha256"),
                "md5": latest.get("md5"),
                "size": latest.get("size"),
                "timestamp": latest.get("timestamp"),
                "depends": latest.get("depends") or [],
            }
            if plugin is None:
                plugin = Plugin(
                    name=name,
                    version=latest_version,
                    latest_version=latest_version,
                    description=f"Bioconda package: {name}",
                    author="Bioconda community",
                    category="bioinformatics",
                    tags=["bioconda", "external-catalog"],
                    source_url=f"https://anaconda.org/bioconda/{name}",
                    homepage=latest.get("home"),
                    license=latest.get("license"),
                    dependencies=[_dependency(item) for item in latest.get("depends") or []],
                    os_compatibility=platforms,
                    install_method={"method": "conda", "package": f"{name}=={latest_version}", "channels": ["conda-forge", "bioconda"]},
                    status="available",
                    is_installed=False,
                    source_registry="bioconda",
                    source_identifier=name,
                    source_metadata={"bioconda": summary},
                    source_synced_at=now,
                    trust_status="unreviewed",
                )
                self.db.add(plugin)
                await self.db.flush()
                imported += 1
            else:
                plugin.latest_version = latest_version
                plugin.source_metadata = {**(plugin.source_metadata or {}), "bioconda": summary}
                plugin.source_synced_at = now
                if plugin.source_registry == "bioconda":
                    plugin.version = latest_version
                    plugin.license = latest.get("license") or plugin.license
                    plugin.os_compatibility = platforms
                    plugin.dependencies = [_dependency(item) for item in latest.get("depends") or []]
                    plugin.install_method = {"method": "conda", "package": f"{name}=={latest_version}", "channels": ["conda-forge", "bioconda"]}
                updated_count += 1

            unique_versions = {}
            for item in candidates:
                version = str(item.get("version") or "")
                if version and version not in unique_versions:
                    unique_versions[version] = item
            existing_result = await self.db.execute(
                select(PluginVersion.version).where(PluginVersion.plugin_id == plugin.id)
            )
            existing_versions = set(existing_result.scalars().all())
            for version, item in unique_versions.items():
                if version in existing_versions:
                    continue
                timestamp = item.get("timestamp")
                self.db.add(PluginVersion(
                    plugin_id=plugin.id,
                    version=version,
                    release_date=(datetime.fromtimestamp(int(timestamp) / 1000, tz=timezone.utc).date().isoformat() if timestamp else None),
                    changelog=f"Synced from Bioconda build {item.get('build') or ''}".strip(),
                    size_mb=round(int(item.get("size") or 0) / 1024 / 1024, 3),
                    checksum=item.get("sha256"),
                    download_url=f"{BIOCONDA_BASE}/{item.get('subdir')}/{item.get('filename')}",
                    is_latest=version == latest_version,
                    is_active=True,
                ))
            await self.db.execute(update(PluginVersion).where(PluginVersion.plugin_id == plugin.id).values(is_latest=False))
            await self.db.execute(
                update(PluginVersion)
                .where(PluginVersion.plugin_id == plugin.id, PluginVersion.version == latest_version)
                .values(is_latest=True)
            )
            capability_manifest = manifest_from_plugin(plugin)
            plugin.manifest_schema_version = capability_manifest.schema_version
            plugin.manifest = capability_manifest.model_dump(mode="json")
            plugin.manifest_digest = manifest_digest(capability_manifest)

        return {"requested": len(requested), "imported": imported, "updated": updated_count, "missing": missing}

    async def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        result = await self.db.execute(
            select(CatalogSync)
            .where(CatalogSync.registry == "bioconda")
            .order_by(CatalogSync.started_at.desc(), CatalogSync.id.desc())
            .limit(limit)
        )
        return [
            {
                "id": item.id,
                "registry": item.registry,
                "user_id": item.user_id,
                "status": item.status,
                "source_urls": item.source_urls or [],
                "request": item.request or {},
                "result": item.result or {},
                "source_digest": item.source_digest,
                "cache_status": item.cache_status,
                "error_message": item.error_message,
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            }
            for item in result.scalars().all()
        ]


__all__ = ["BIOCONDA_BASE", "ALLOWED_SUBDIRS", "BiocondaCatalogSync"]
