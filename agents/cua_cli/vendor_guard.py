"""
Vendored Gemini CLI dependency governance.

The TypeScript Gemini CLI tree is intentionally vendored under
``agents/cua_cli/gemini-cli``. This module keeps Python runtime entrypoints from
executing that tree when package metadata or lockfile pins drift outside an
explicit reviewed manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_MANIFEST_FILENAME = "gemini_cli_vendor_manifest.json"
SUPPORTED_SCHEMA_VERSION = 1

_ROOT_LOCK_FIELDS = (
    "name",
    "version",
    "license",
    "workspaces",
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
    "peerDependenciesMeta",
    "bin",
    "engines",
)


class GeminiCliVendorError(RuntimeError):
    """Raised when the vendored Gemini CLI tree is not safe to execute."""


@dataclass(frozen=True)
class GeminiCliVendorValidation:
    vendor_root: Path
    manifest_path: Path
    package_name: str
    package_version: str
    lockfile_version: int
    cli_entrypoint: str
    cli_entrypoint_sha256: str
    package_json_sha256: str
    package_lock_sha256: str

    @property
    def entrypoint_path(self) -> Path:
        return self.vendor_root / self.cli_entrypoint


def validate_gemini_cli_vendor(
    gemini_cli_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> GeminiCliVendorValidation:
    """
    Validate the vendored Gemini CLI tree against the reviewed local manifest.

    This intentionally checks both exact file pins and package-lock/package.json
    consistency. Updating the vendored dependency should be an explicit review
    step that refreshes the manifest after package-manager generated files have
    been regenerated normally.
    """

    vendor_root = Path(gemini_cli_path).resolve()
    resolved_manifest_path = (
        Path(manifest_path).resolve()
        if manifest_path is not None
        else vendor_root.parent / DEFAULT_MANIFEST_FILENAME
    )
    package_json_path = vendor_root / "package.json"
    package_lock_path = vendor_root / "package-lock.json"
    cli_entrypoint: str | None = None
    errors: list[str] = []

    manifest = _read_json_object(resolved_manifest_path, errors, "vendor manifest")
    package_json = _read_json_object(package_json_path, errors, "package.json")
    package_lock = _read_json_object(package_lock_path, errors, "package-lock.json")

    if manifest is not None:
        _validate_manifest_shape(
            manifest=manifest,
            vendor_root=vendor_root,
            errors=errors,
        )

    package_json_sha = _hash_file(package_json_path, errors)
    package_lock_sha = _hash_file(package_lock_path, errors)
    if manifest is not None:
        cli_entrypoint = _validate_cli_entrypoint(manifest, package_json, errors)
    cli_entrypoint_sha = (
        _hash_file(vendor_root / cli_entrypoint, errors) if cli_entrypoint is not None else None
    )

    if manifest is not None:
        _validate_hash_pin(
            manifest=manifest,
            manifest_key="package_json_sha256",
            actual=package_json_sha,
            label="package.json",
            errors=errors,
        )
        _validate_hash_pin(
            manifest=manifest,
            manifest_key="package_lock_sha256",
            actual=package_lock_sha,
            label="package-lock.json",
            errors=errors,
        )
        _validate_hash_pin(
            manifest=manifest,
            manifest_key="cli_entrypoint_sha256",
            actual=cli_entrypoint_sha,
            label=str(cli_entrypoint or "Gemini CLI entrypoint"),
            errors=errors,
        )

    if manifest is not None and package_json is not None:
        _validate_manifest_pin(
            manifest=manifest,
            manifest_key="package_name",
            actual=package_json.get("name"),
            label="package.json name",
            errors=errors,
        )
        _validate_manifest_pin(
            manifest=manifest,
            manifest_key="package_version",
            actual=package_json.get("version"),
            label="package.json version",
            errors=errors,
        )

    root_lock_package: Mapping[str, Any] | None = None
    if package_lock is not None:
        packages = package_lock.get("packages")
        if not isinstance(packages, Mapping):
            errors.append("package-lock.json packages must be an object")
        else:
            root = packages.get("")
            if not isinstance(root, Mapping):
                errors.append('package-lock.json packages[""] root package is missing')
            else:
                root_lock_package = root

    if manifest is not None and package_lock is not None:
        _validate_manifest_pin(
            manifest=manifest,
            manifest_key="lockfile_version",
            actual=package_lock.get("lockfileVersion"),
            label="package-lock.json lockfileVersion",
            errors=errors,
        )

    if package_json is not None and package_lock is not None:
        _validate_lock_package_header(package_json, package_lock, errors)

    if package_json is not None and root_lock_package is not None:
        _validate_root_package_consistency(package_json, root_lock_package, errors)

    if errors:
        raise GeminiCliVendorError(_format_vendor_error(errors, resolved_manifest_path))

    assert manifest is not None
    assert cli_entrypoint is not None
    assert cli_entrypoint_sha is not None
    assert package_json_sha is not None
    assert package_lock_sha is not None
    return GeminiCliVendorValidation(
        vendor_root=vendor_root,
        manifest_path=resolved_manifest_path,
        package_name=str(manifest["package_name"]),
        package_version=str(manifest["package_version"]),
        lockfile_version=int(manifest["lockfile_version"]),
        cli_entrypoint=cli_entrypoint,
        cli_entrypoint_sha256=cli_entrypoint_sha,
        package_json_sha256=package_json_sha,
        package_lock_sha256=package_lock_sha,
    )


def _read_json_object(
    path: Path,
    errors: list[str],
    label: str,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{label} is missing: {path}")
        return None
    except json.JSONDecodeError as exc:
        errors.append(f"{label} is not valid JSON: {path} ({exc})")
        return None

    if not isinstance(payload, dict):
        errors.append(f"{label} must be a JSON object: {path}")
        return None
    return payload


def _hash_file(path: Path, errors: list[str]) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except FileNotFoundError:
        return None
    except OSError as exc:
        errors.append(f"failed to read {path}: {exc}")
        return None


def _validate_manifest_shape(
    *,
    manifest: Mapping[str, Any],
    vendor_root: Path,
    errors: list[str],
) -> None:
    schema_version = manifest.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        errors.append(
            "vendor manifest schema_version must be "
            f"{SUPPORTED_SCHEMA_VERSION}, got {schema_version!r}"
        )

    vendor_root_name = manifest.get("vendor_root")
    if vendor_root_name != vendor_root.name:
        errors.append(
            "vendor manifest vendor_root does not match Gemini CLI directory: "
            f"expected {vendor_root.name!r}, got {vendor_root_name!r}"
        )

    for key in (
        "package_name",
        "package_version",
        "lockfile_version",
        "cli_entrypoint",
        "cli_entrypoint_sha256",
        "package_json_sha256",
        "package_lock_sha256",
    ):
        if key not in manifest:
            errors.append(f"vendor manifest missing required key: {key}")


def _validate_hash_pin(
    *,
    manifest: Mapping[str, Any],
    manifest_key: str,
    actual: str | None,
    label: str,
    errors: list[str],
) -> None:
    if actual is None or manifest_key not in manifest:
        return

    expected = str(manifest[manifest_key]).strip().lower()
    if expected != actual.lower():
        errors.append(f"{label} sha256 mismatch: expected {expected}, got {actual.lower()}")


def _validate_manifest_pin(
    *,
    manifest: Mapping[str, Any],
    manifest_key: str,
    actual: Any,
    label: str,
    errors: list[str],
) -> None:
    if manifest_key not in manifest:
        return

    expected = manifest[manifest_key]
    if actual != expected:
        errors.append(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def _validate_lock_package_header(
    package_json: Mapping[str, Any],
    package_lock: Mapping[str, Any],
    errors: list[str],
) -> None:
    for key in ("name", "version"):
        if package_lock.get(key) != package_json.get(key):
            errors.append(
                f"package-lock.json {key} does not match package.json: "
                f"expected {package_json.get(key)!r}, got {package_lock.get(key)!r}"
            )


def _validate_cli_entrypoint(
    manifest: Mapping[str, Any],
    package_json: Mapping[str, Any] | None,
    errors: list[str],
) -> str | None:
    cli_entrypoint = manifest.get("cli_entrypoint")
    if not isinstance(cli_entrypoint, str) or not cli_entrypoint.strip():
        errors.append("vendor manifest cli_entrypoint must be a non-empty string")
        return None

    normalized_entrypoint = cli_entrypoint.replace("\\", "/").strip()
    if package_json is None:
        return normalized_entrypoint

    bin_field = package_json.get("bin")
    if isinstance(bin_field, str):
        package_entrypoint = bin_field
    elif isinstance(bin_field, Mapping):
        package_entrypoint = bin_field.get("gemini")
    else:
        package_entrypoint = None

    if not isinstance(package_entrypoint, str) or not package_entrypoint.strip():
        errors.append("package.json bin.gemini entrypoint is missing or invalid")
        return normalized_entrypoint

    normalized_package_entrypoint = package_entrypoint.replace("\\", "/").strip()
    if normalized_package_entrypoint != normalized_entrypoint:
        errors.append(
            "package.json Gemini CLI entrypoint does not match vendor manifest: "
            f"expected {normalized_entrypoint!r}, got {normalized_package_entrypoint!r}"
        )

    return normalized_entrypoint


def _validate_root_package_consistency(
    package_json: Mapping[str, Any],
    root_lock_package: Mapping[str, Any],
    errors: list[str],
) -> None:
    sentinel = object()
    for field in _ROOT_LOCK_FIELDS:
        package_value = package_json.get(field, sentinel)
        lock_value = root_lock_package.get(field, sentinel)
        if package_value == sentinel and lock_value == sentinel:
            continue
        if package_value != lock_value:
            errors.append(
                f"package-lock.json root package {field} does not match package.json"
            )


def _format_vendor_error(errors: list[str], manifest_path: Path) -> str:
    bullets = "\n".join(f"- {error}" for error in errors)
    return (
        "Gemini CLI vendor validation failed. The vendored dependency is "
        "inconsistent and will not be executed. Regenerate package-lock.json "
        "with npm, review the diff, then update "
        f"{manifest_path} intentionally; do not hand-edit lockfile pins.\n"
        f"{bullets}"
    )
