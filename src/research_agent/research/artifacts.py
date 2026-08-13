"""用户隔离的科研文件存储、预检、表格剖析与预览图生成。"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import json
import math
import os
import re
import shutil
import tempfile
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import UploadFile

from ..security import CryptoService


class ArtifactError(ValueError):
    pass


class _ArtifactStoreBase:
    MAX_BYTES = 25 * 1024 * 1024
    ENCRYPTION_FORMAT = "ra-aes256-gcm-v1"
    MAGIC = b"RAART001"
    ALLOWED_SUFFIXES = {
        ".csv",
        ".tsv",
        ".txt",
        ".md",
        ".json",
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".fa",
        ".fasta",
        ".fna",
        ".gtf",
        ".gff",
        ".gff3",
        ".bed",
        ".interval_list",
    }

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_database_url(cls, database_url: str) -> _ArtifactStoreBase:
        prefix = "sqlite+aiosqlite:///"
        if database_url.startswith(prefix):
            db_path = Path(database_url[len(prefix) :]).expanduser().resolve()
            return cls(db_path.parent / "artifacts")
        return cls(Path.cwd() / "artifacts")

    @staticmethod
    def safe_name(filename: str | None) -> str:
        original = Path(filename or "artifact.bin").name
        stem = re.sub(r"[^\w\-. ]+", "_", original, flags=re.UNICODE).strip(" .")
        return (stem or "artifact.bin")[:180]

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if not candidate.is_relative_to(self.root):
            raise ArtifactError("非法文件路径")
        return candidate

    def purge_materialized(self) -> int:
        """Remove plaintext left by a previous unclean process exit."""
        folder = (self.root / ".materialized").resolve()
        if not folder.is_relative_to(self.root) or not folder.exists():
            return 0
        count = sum(1 for item in folder.rglob("*") if item.is_file())
        shutil.rmtree(folder)
        return count

    @staticmethod
    def _value(item: Any, name: str, default: Any = None) -> Any:
        return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)

    def _aad(self, artifact_id: str, user_id: int, sha256: str) -> bytes:
        return f"{self.ENCRYPTION_FORMAT}\n{artifact_id}\n{user_id}\n{sha256}".encode()

    def _encrypt(self, data: bytes, artifact_id: str, user_id: int, sha256: str) -> bytes:
        nonce = os.urandom(12)
        ciphertext = AESGCM(CryptoService.derive_key("research-artifact-store-v1")).encrypt(
            nonce,
            data,
            self._aad(artifact_id, user_id, sha256),
        )
        return self.MAGIC + nonce + ciphertext

    def _decrypt(self, payload: bytes, artifact: Any) -> bytes:
        if not payload.startswith(self.MAGIC) or len(payload) < len(self.MAGIC) + 28:
            raise ArtifactError("Encrypted artifact envelope is invalid")
        artifact_id = str(self._value(artifact, "id", ""))
        user_id = int(self._value(artifact, "user_id", 0))
        expected = str(self._value(artifact, "sha256", ""))
        offset = len(self.MAGIC)
        try:
            plaintext = AESGCM(CryptoService.derive_key("research-artifact-store-v1")).decrypt(
                payload[offset : offset + 12],
                payload[offset + 12 :],
                self._aad(artifact_id, user_id, expected),
            )
        except InvalidTag as exc:
            raise ArtifactError(
                "Artifact authentication failed; ciphertext or metadata was modified"
            ) from exc
        if not hmac.compare_digest(hashlib.sha256(plaintext).hexdigest(), expected):
            raise ArtifactError("Artifact plaintext checksum does not match its provenance record")
        return plaintext

    def read_artifact(self, artifact: Any) -> bytes:
        path = self.resolve(str(self._value(artifact, "relative_path", "")))
        if not path.is_file():
            raise ArtifactError("Artifact file is unavailable")
        payload = path.read_bytes()
        encrypted_sha = str(self._value(artifact, "encrypted_sha256", "") or "")
        if encrypted_sha and not hmac.compare_digest(
            hashlib.sha256(payload).hexdigest(), encrypted_sha
        ):
            raise ArtifactError("Encrypted artifact checksum mismatch")
        if self._value(artifact, "encryption_format") == self.ENCRYPTION_FORMAT:
            return self._decrypt(payload, artifact)
        expected = str(self._value(artifact, "sha256", "") or "")
        if expected and not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected):
            raise ArtifactError("Legacy artifact checksum mismatch")
        return payload

    @contextmanager
    def materialize(self, artifact: Any):
        """Yield a verified plaintext path and always clean temporary plaintext."""
        if not self._value(artifact, "encryption_format"):
            path = self.resolve(str(self._value(artifact, "relative_path", "")))
            self.read_artifact(artifact)
            yield path
            return
        user_id = int(self._value(artifact, "user_id", 0))
        folder = self.root / ".materialized" / f"user-{user_id}"
        folder.mkdir(parents=True, exist_ok=True)
        suffix = Path(str(self._value(artifact, "name", "artifact.bin"))).suffix
        fd, raw_path = tempfile.mkstemp(prefix="ra-", suffix=suffix, dir=folder)
        path = Path(raw_path)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(self.read_artifact(artifact))
                handle.flush()
                os.fsync(handle.fileno())
            yield path
        finally:
            path.unlink(missing_ok=True)
            try:
                folder.rmdir()
                folder.parent.rmdir()
            except OSError:
                pass

    def migrate_plaintext(self, artifact: Any) -> dict[str, str]:
        if self._value(artifact, "encryption_format"):
            return {
                "relative_path": str(self._value(artifact, "relative_path")),
                "encryption_format": str(self._value(artifact, "encryption_format")),
                "encrypted_sha256": str(self._value(artifact, "encrypted_sha256", "")),
            }
        source = self.resolve(str(self._value(artifact, "relative_path", "")))
        plaintext = self.read_artifact(artifact)
        artifact_id = str(self._value(artifact, "id"))
        user_id = int(self._value(artifact, "user_id"))
        sha256 = str(self._value(artifact, "sha256"))
        encrypted = self._encrypt(plaintext, artifact_id, user_id, sha256)
        target = source.with_name(f"{artifact_id}.raenc")
        if target == source:
            target = source.with_name(f"{artifact_id}.migrated.raenc")
        temporary = target.with_suffix(".raenc.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        return {
            "relative_path": target.relative_to(self.root).as_posix(),
            "encryption_format": self.ENCRYPTION_FORMAT,
            "encrypted_sha256": hashlib.sha256(encrypted).hexdigest(),
            "legacy_relative_path": source.relative_to(self.root).as_posix(),
        }

    async def save_upload(
        self,
        upload: UploadFile,
        user_id: int,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        name = self.safe_name(upload.filename)
        suffix = Path(name).suffix.lower()
        if suffix not in self.ALLOWED_SUFFIXES:
            raise ArtifactError(f"不支持的文件类型: {suffix or '无扩展名'}")

        artifact_id = str(uuid.uuid4())
        folder = self.root / f"user-{user_id}" / (f"run-{run_id}" if run_id else "inbox")
        folder.mkdir(parents=True, exist_ok=True)
        target = (folder / f"{artifact_id}.raenc").resolve()
        if not target.is_relative_to(self.root):
            raise ArtifactError("非法文件目标")

        digest = hashlib.sha256()
        total = 0
        try:
            with target.open("wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.MAX_BYTES:
                        raise ArtifactError("文件超过 25 MiB 上限")
                    digest.update(chunk)
                    handle.write(chunk)
        except Exception:
            if target.exists() and target.is_file():
                target.unlink()
            raise
        finally:
            await upload.close()

        summary = await asyncio.to_thread(self.inspect, target)
        return {
            "id": artifact_id,
            "name": name,
            "relative_path": target.relative_to(self.root).as_posix(),
            "media_type": upload.content_type or self._media_type(suffix),
            "kind": "input",
            "size_bytes": total,
            "sha256": digest.hexdigest(),
            "summary": summary,
            "status": "ready",
        }

    @staticmethod
    def _media_type(suffix: str) -> str:
        return {
            ".csv": "text/csv",
            ".tsv": "text/tab-separated-values",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".json": "application/json",
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".fa": "text/x-fasta",
            ".fasta": "text/x-fasta",
            ".fna": "text/x-fasta",
            ".gtf": "text/x-gtf",
            ".gff": "text/x-gff",
            ".gff3": "text/x-gff3",
            ".bed": "text/x-bed",
            ".interval_list": "text/plain",
        }.get(suffix, "application/octet-stream")

    def inspect(self, path: Path) -> dict[str, Any]:
        suffix = path.suffix.lower()
        try:
            if suffix in {".csv", ".tsv"}:
                profile = self.profile_table(path, max_rows=5000)
                return {
                    "modality": "table",
                    "rows_scanned": profile["rows_scanned"],
                    "columns": profile["column_count"],
                    "column_names": [item["name"] for item in profile["columns"][:30]],
                    "extraction": "complete" if not profile["truncated"] else "bounded",
                }
            if suffix in {
                ".txt",
                ".md",
                ".fa",
                ".fasta",
                ".fna",
                ".gtf",
                ".gff",
                ".gff3",
                ".bed",
                ".interval_list",
            }:
                text = path.read_text(encoding="utf-8", errors="replace")[:100_000]
                return {
                    "modality": "text",
                    "characters_extracted": len(text),
                    "preview": text[:1500],
                    "extraction": "bounded",
                }
            if suffix == ".json":
                value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                kind = (
                    "array"
                    if isinstance(value, list)
                    else "object"
                    if isinstance(value, dict)
                    else type(value).__name__
                )
                return {"modality": "structured", "root_type": kind, "extraction": "metadata"}
            if suffix == ".pdf":
                from pypdf import PdfReader

                reader = PdfReader(str(path))
                pages = []
                for page in reader.pages[:40]:
                    pages.append((page.extract_text() or "")[:10_000])
                text = "\n".join(pages)[:100_000]
                return {
                    "modality": "document",
                    "pages": len(reader.pages),
                    "pages_extracted": min(len(reader.pages), 40),
                    "characters_extracted": len(text),
                    "preview": text[:1500],
                    "extraction": "bounded",
                }
            if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
                from PIL import Image

                with Image.open(path) as image:
                    return {
                        "modality": "image",
                        "width": image.width,
                        "height": image.height,
                        "mode": image.mode,
                        "format": image.format,
                        "extraction": "metadata",
                        "note": "图像语义解读需要已配置的视觉模型；原图已保留。",
                    }
        except Exception as exc:
            return {"modality": "unknown", "extraction": "failed", "error": str(exc)[:300]}
        return {"modality": "binary", "extraction": "metadata"}

    @staticmethod
    def _coerce_number(value: str) -> float | None:
        try:
            number = float(value.strip())
            return number if math.isfinite(number) else None
        except (TypeError, ValueError):
            return None

    def profile_table(self, path: Path, max_rows: int = 50_000) -> dict[str, Any]:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if not reader.fieldnames:
                raise ArtifactError("表格缺少标题行")
            fields = [
                str(name).strip() or f"column_{index + 1}"
                for index, name in enumerate(reader.fieldnames)
            ]
            stats = {
                name: {
                    "missing": 0,
                    "non_missing": 0,
                    "numeric": 0,
                    "sum": 0.0,
                    "sum_sq": 0.0,
                    "min": None,
                    "max": None,
                    "examples": Counter(),
                }
                for name in fields
            }
            count = 0
            truncated = False
            for row in reader:
                if count >= max_rows:
                    truncated = True
                    break
                count += 1
                for original, name in zip(reader.fieldnames, fields, strict=True):
                    value = (row.get(original) or "").strip()
                    item = stats[name]
                    if value == "" or value.lower() in {"na", "nan", "null", "none"}:
                        item["missing"] += 1
                        continue
                    item["non_missing"] += 1
                    if len(item["examples"]) < 20 or value in item["examples"]:
                        item["examples"][value[:80]] += 1
                    number = self._coerce_number(value)
                    if number is not None:
                        item["numeric"] += 1
                        item["sum"] += number
                        item["sum_sq"] += number * number
                        item["min"] = number if item["min"] is None else min(item["min"], number)
                        item["max"] = number if item["max"] is None else max(item["max"], number)

        columns = []
        for name in fields:
            item = stats[name]
            non_missing = item["non_missing"]
            numeric_ratio = item["numeric"] / non_missing if non_missing else 0.0
            column: dict[str, Any] = {
                "name": name,
                "inferred_type": "numeric" if numeric_ratio >= 0.9 else "categorical_or_text",
                "missing": item["missing"],
                "missing_rate": round(item["missing"] / count, 4) if count else 0.0,
                # Preserve data-shape statistics without copying participant IDs,
                # free text, or other raw sample values into the SQLite summary.
                "unique_sampled": len(item["examples"]),
            }
            if item["numeric"]:
                n = item["numeric"]
                mean = item["sum"] / n
                variance = max(0.0, item["sum_sq"] / n - mean * mean)
                column.update(
                    {
                        "numeric_count": n,
                        "mean": round(mean, 6),
                        "std": round(math.sqrt(variance), 6),
                        "min": item["min"],
                        "max": item["max"],
                    }
                )
            columns.append(column)
        return {
            "rows_scanned": count,
            "column_count": len(columns),
            "columns": columns,
            "truncated": truncated,
            "quality_flags": self._quality_flags(columns, count, truncated),
        }

    @staticmethod
    def _quality_flags(columns: list[dict[str, Any]], rows: int, truncated: bool) -> list[str]:
        flags = []
        if rows < 3:
            flags.append("样本行数少于 3，无法支持稳定推断。")
        if any(column["missing_rate"] > 0.2 for column in columns):
            flags.append("至少一列缺失率超过 20%，建模前需说明缺失机制和处理方案。")
        if len({column["name"] for column in columns}) != len(columns):
            flags.append("存在重复列名。")
        if truncated:
            flags.append("数据剖析采用有界扫描，指标基于前 50,000 行。")
        return flags

    def render_table_preview(self, path: Path, user_id: int, run_id: str) -> dict[str, Any] | None:
        profile = self.profile_table(path, max_rows=10_000)
        numeric = [column for column in profile["columns"] if column["inferred_type"] == "numeric"]
        if not numeric:
            return None

        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        name = numeric[0]["name"]
        values: list[float] = []
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            for row in reader:
                number = self._coerce_number(row.get(name, ""))
                if number is not None:
                    values.append(number)
                if len(values) >= 10_000:
                    break
        if not values:
            return None

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        artifact_id = str(uuid.uuid4())
        folder = self.root / f"user-{user_id}" / f"run-{run_id}" / "generated"
        folder.mkdir(parents=True, exist_ok=True)
        target = (folder / f"{artifact_id}.png").resolve()
        if not target.is_relative_to(self.root):
            raise ArtifactError("非法输出目标")

        fig, ax = plt.subplots(figsize=(8, 4.8))
        ax.hist(
            values, bins=min(30, max(5, int(math.sqrt(len(values))))), color="#2563eb", alpha=0.82
        )
        ax.set_title(f"Distribution preview: {name}")
        ax.set_xlabel(name)
        ax.set_ylabel("Count")
        fig.tight_layout()
        fig.savefig(target, dpi=150)
        plt.close(fig)
        raw = target.read_bytes()
        return {
            "id": artifact_id,
            "name": f"{Path(path).stem}-{name}-distribution.png",
            "relative_path": target.relative_to(self.root).as_posix(),
            "media_type": "image/png",
            "kind": "visualization",
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "summary": {"chart": "histogram", "column": name, "values": len(values)},
            "status": "ready",
        }


class ArtifactStore(_ArtifactStoreBase):
    """Default store for new artifacts; plaintext is never persisted at upload time."""

    async def save_upload(
        self,
        upload: UploadFile,
        user_id: int,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        name = self.safe_name(upload.filename)
        suffix = Path(name).suffix.lower()
        if suffix not in self.ALLOWED_SUFFIXES:
            raise ArtifactError(f"Unsupported artifact type: {suffix or 'no extension'}")
        raw = bytearray()
        try:
            while chunk := await upload.read(1024 * 1024):
                raw.extend(chunk)
                if len(raw) > self.MAX_BYTES:
                    raise ArtifactError("File exceeds the 25 MiB limit")
        finally:
            await upload.close()

        plaintext = bytes(raw)
        artifact_id = str(uuid.uuid4())
        plaintext_sha = hashlib.sha256(plaintext).hexdigest()
        encrypted = self._encrypt(plaintext, artifact_id, user_id, plaintext_sha)
        folder = self.root / f"user-{user_id}" / (f"run-{run_id}" if run_id else "inbox")
        folder.mkdir(parents=True, exist_ok=True)
        target = (folder / f"{artifact_id}.raenc").resolve()
        if not target.is_relative_to(self.root):
            raise ArtifactError("Invalid artifact target")
        temporary = target.with_suffix(".raenc.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        return {
            "id": artifact_id,
            "name": name,
            "relative_path": target.relative_to(self.root).as_posix(),
            "media_type": upload.content_type or self._media_type(suffix),
            "kind": "input",
            "size_bytes": len(plaintext),
            "sha256": plaintext_sha,
            "encryption_format": self.ENCRYPTION_FORMAT,
            "encrypted_sha256": hashlib.sha256(encrypted).hexdigest(),
            "summary": self.inspect_bytes(name, plaintext),
            "status": "ready",
        }

    def inspect_bytes(self, name: str, raw: bytes) -> dict[str, Any]:
        suffix = Path(name).suffix.lower()
        try:
            if suffix in {".csv", ".tsv"}:
                delimiter = "\t" if suffix == ".tsv" else ","
                reader = csv.reader(
                    io.StringIO(raw.decode("utf-8-sig", errors="replace")), delimiter=delimiter
                )
                header = next(reader, [])
                rows = 0
                for _ in reader:
                    rows += 1
                    if rows >= 5000:
                        break
                return {
                    "modality": "table",
                    "rows_scanned": rows,
                    "columns": len(header),
                    "extraction": "bounded" if rows >= 5000 else "complete",
                }
            if suffix in {
                ".txt",
                ".md",
                ".fa",
                ".fasta",
                ".fna",
                ".gtf",
                ".gff",
                ".gff3",
                ".bed",
                ".interval_list",
            }:
                text = raw.decode("utf-8", errors="replace")[:100_000]
                return {
                    "modality": "text",
                    "characters_extracted": len(text),
                    "extraction": "bounded",
                }
            if suffix == ".json":
                value = json.loads(raw.decode("utf-8", errors="replace"))
                kind = (
                    "array"
                    if isinstance(value, list)
                    else "object"
                    if isinstance(value, dict)
                    else type(value).__name__
                )
                return {"modality": "structured", "root_type": kind, "extraction": "metadata"}
            if suffix == ".pdf":
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(raw))
                pages = [(page.extract_text() or "")[:10_000] for page in reader.pages[:40]]
                text = "\n".join(pages)[:100_000]
                return {
                    "modality": "document",
                    "pages": len(reader.pages),
                    "pages_extracted": min(len(reader.pages), 40),
                    "characters_extracted": len(text),
                    "extraction": "bounded",
                }
            if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
                from PIL import Image

                with Image.open(io.BytesIO(raw)) as image:
                    return {
                        "modality": "image",
                        "width": image.width,
                        "height": image.height,
                        "mode": image.mode,
                        "format": image.format,
                        "extraction": "metadata",
                    }
        except Exception as exc:
            return {
                "modality": "unknown",
                "extraction": "failed",
                "error_type": type(exc).__name__,
            }
        return {"modality": "binary", "extraction": "metadata"}

    def render_table_preview(self, path: Path, user_id: int, run_id: str) -> dict[str, Any] | None:
        profile = self.profile_table(path, max_rows=10_000)
        numeric = [column for column in profile["columns"] if column["inferred_type"] == "numeric"]
        if not numeric:
            return None
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        name = numeric[0]["name"]
        values: list[float] = []
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            for row in reader:
                number = self._coerce_number(row.get(name, ""))
                if number is not None:
                    values.append(number)
                if len(values) >= 10_000:
                    break
        if not values:
            return None

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        output = io.BytesIO()
        fig, ax = plt.subplots(figsize=(8, 4.8))
        try:
            ax.hist(
                values,
                bins=min(30, max(5, int(math.sqrt(len(values))))),
                color="#2563eb",
                alpha=0.82,
            )
            ax.set_title("Distribution preview")
            ax.set_xlabel("Numeric value")
            ax.set_ylabel("Count")
            fig.tight_layout()
            fig.savefig(output, format="png", dpi=150)
        finally:
            plt.close(fig)
        raw = output.getvalue()
        artifact_id = str(uuid.uuid4())
        plaintext_sha = hashlib.sha256(raw).hexdigest()
        encrypted = self._encrypt(raw, artifact_id, user_id, plaintext_sha)
        folder = self.root / f"user-{user_id}" / f"run-{run_id}" / "generated"
        folder.mkdir(parents=True, exist_ok=True)
        encrypted_path = (folder / f"{artifact_id}.raenc").resolve()
        if not encrypted_path.is_relative_to(self.root):
            raise ArtifactError("Invalid generated artifact target")
        temporary = encrypted_path.with_suffix(".raenc.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(encrypted_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            encrypted_path.unlink(missing_ok=True)
            raise
        return {
            "id": artifact_id,
            "name": "data-distribution.png",
            "relative_path": encrypted_path.relative_to(self.root).as_posix(),
            "media_type": "image/png",
            "kind": "visualization",
            "size_bytes": len(raw),
            "sha256": plaintext_sha,
            "encryption_format": self.ENCRYPTION_FORMAT,
            "encrypted_sha256": hashlib.sha256(encrypted).hexdigest(),
            "summary": {"chart": "histogram", "values": len(values)},
            "status": "ready",
        }


def public_artifact(artifact: Any) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "run_id": artifact.run_id,
        "name": artifact.name,
        "media_type": artifact.media_type,
        "kind": artifact.kind,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "encrypted_at_rest": artifact.encryption_format == ArtifactStore.ENCRYPTION_FORMAT,
        "summary": artifact.summary or {},
        "status": artifact.status,
        "created_at": artifact.created_at,
    }
