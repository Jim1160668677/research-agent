"""Capability Manifest v1 for discoverable and executable research tools."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MANIFEST_SCHEMA_VERSION = "1.0"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


def pinned_package_spec(package: str, version: str) -> str:
    """Pin an unconstrained package name to the advertised capability version."""
    value = package.strip()
    if re.search(r"(?:==|>=|<=|~=|!=|>|<|=)", value):
        return value
    return f"{value}=={version}"


class ManifestContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)


class ManifestRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executor: Literal["conda", "pip", "binary", "container", "remote", "manual"]
    platforms: List[Literal["windows", "linux", "macos"]] = Field(default_factory=list)
    package: Optional[str] = None
    channels: List[str] = Field(default_factory=list)
    image: Optional[str] = None
    executable: Optional[str] = None
    default_args: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_executor_contract(self):
        if self.executor in {"conda", "pip"} and not self.package:
            raise ValueError(f"{self.executor} runtime requires package")
        if self.executor == "container" and not self.image:
            raise ValueError("container runtime requires a digest-pinned image")
        if self.image and "@sha256:" not in self.image:
            raise ValueError("container image must be pinned by sha256 digest")
        return self


class ManifestPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    network: Literal["denied", "restricted", "required"] = "denied"
    allowed_hosts: List[str] = Field(default_factory=list)
    filesystem_read: List[str] = Field(default_factory=list)
    filesystem_write: List[str] = Field(default_factory=list)
    requires_approval: bool = True


class ManifestResources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu: int = Field(default=1, ge=1, le=256)
    memory_mb: int = Field(default=512, ge=64, le=2_097_152)
    timeout_seconds: int = Field(default=600, ge=1, le=604_800)
    gpu: bool = False


class ManifestProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry: Literal["builtin", "bioconda", "toolshed", "biocontainers", "user"]
    identifier: str = Field(min_length=1, max_length=255)
    source_url: Optional[str] = None
    source_digest: Optional[str] = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("source_url must be an absolute HTTPS URL")
        return value


class CapabilityManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = MANIFEST_SCHEMA_VERSION
    kind: Literal["tool", "skill", "workflow"] = "tool"
    name: str
    version: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    category: str = Field(default="general", min_length=1, max_length=100)
    tags: List[str] = Field(default_factory=list, max_length=50)
    license: Optional[str] = Field(default=None, max_length=100)
    contract: ManifestContract = Field(default_factory=ManifestContract)
    runtime: ManifestRuntime
    permissions: ManifestPermissions = Field(default_factory=ManifestPermissions)
    resources: ManifestResources = Field(default_factory=ManifestResources)
    provenance: ManifestProvenance

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _SAFE_NAME.fullmatch(value):
            raise ValueError("manifest name contains unsupported characters")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: List[str]) -> List[str]:
        result = []
        for value in values:
            value = value.strip().lower()
            if value and value not in result:
                result.append(value[:50])
        return result


def manifest_digest(manifest: CapabilityManifestV1 | Dict[str, Any]) -> str:
    data = manifest.model_dump(mode="json") if isinstance(manifest, BaseModel) else manifest
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def manifest_from_plugin(plugin) -> CapabilityManifestV1:
    install = plugin.install_method or {"method": "manual"}
    executor = str(install.get("method") or "manual").lower()
    if executor not in {"conda", "pip", "binary", "container", "remote", "manual"}:
        executor = "manual"
    package = install.get("spec") or install.get("package")
    if package and executor in {"conda", "pip"}:
        package = pinned_package_spec(str(package), plugin.version)
    channels = install.get("channels") or (
        [install.get("channel")] if install.get("channel") else []
    )
    registry = plugin.source_registry or "builtin"
    if registry not in {"builtin", "bioconda", "toolshed", "biocontainers", "user"}:
        registry = "user"
    return CapabilityManifestV1(
        name=plugin.name,
        version=plugin.version,
        description=plugin.description or "",
        category=plugin.category or "general",
        tags=plugin.tags or [],
        license=plugin.license,
        contract=ManifestContract(inputs=plugin.config_schema or {}, outputs={}),
        runtime=ManifestRuntime(
            executor=executor,
            platforms=plugin.os_compatibility or [],
            package=str(package) if package else None,
            channels=[str(item) for item in channels if item],
            image=install.get("image"),
            executable=install.get("executable"),
            default_args=[str(item) for item in install.get("default_args", [])],
        ),
        permissions=ManifestPermissions(
            network="restricted" if executor in {"conda", "pip"} else "denied",
            allowed_hosts=(
                ["conda.anaconda.org"]
                if executor == "conda"
                else ["pypi.org", "files.pythonhosted.org"]
                if executor == "pip"
                else []
            ),
            requires_approval=True,
        ),
        provenance=ManifestProvenance(
            registry=registry,
            identifier=plugin.source_identifier or plugin.name,
            source_url=(
                plugin.source_url
                if str(plugin.source_url or "").startswith("https://")
                else None
            ),
            source_digest=(plugin.source_metadata or {}).get("source_digest"),
        ),
    )


def validated_manifest_for_plugin(plugin) -> CapabilityManifestV1:
    if plugin.manifest:
        return CapabilityManifestV1.model_validate(plugin.manifest)
    return manifest_from_plugin(plugin)


__all__ = [
    "MANIFEST_SCHEMA_VERSION", "CapabilityManifestV1", "ManifestContract",
    "ManifestRuntime", "ManifestPermissions", "ManifestResources",
    "ManifestProvenance", "manifest_digest", "manifest_from_plugin",
    "validated_manifest_for_plugin", "pinned_package_spec",
]
