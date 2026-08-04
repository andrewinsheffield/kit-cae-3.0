#!/usr/bin/env python3
"""Apply opt-in local dependency artifacts after the normal dependency fetch."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WARP_SIMDATA_PACKAGE_ENV = "KIT_CAE_WARP_SIMDATA_PACKAGE"
OPENUSD_PLUGINS_PACKAGE_ENV = "KIT_CAE_OPENUSD_PLUGINS_PACKAGE"


def _artifact_path(variable: str) -> Path | None:
    value = os.environ.get(variable)
    if not value:
        return None

    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(f"{variable} does not name a file: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            member_path = (destination / member.filename).resolve()
            if member_path != destination and destination not in member_path.parents:
                raise RuntimeError(f"Package contains an unsafe path: {member.filename}")
        package.extractall(destination)


def _openusd_plugins_package_root(extracted: Path) -> Path:
    required_directories = (Path("plugin/usd"), Path("lib/python/cae_openusd_plugins"))
    candidates = [extracted]
    candidates.extend(path for path in extracted.iterdir() if path.is_dir())
    matches = [
        candidate
        for candidate in candidates
        if all((candidate / item).is_dir() for item in required_directories)
        and (candidate / "cae-package-metadata.env").is_file()
    ]

    if len(matches) != 1:
        raise RuntimeError(
            "Local cae_openusd_plugins package must contain one install tree with "
            "plugin/usd, lib/python/cae_openusd_plugins, and cae-package-metadata.env"
        )
    return matches[0]


def _warp_simdata_package_root(extracted: Path) -> Path:
    candidates = [extracted]
    candidates.extend(path for path in extracted.iterdir() if path.is_dir())
    matches = [
        candidate
        for candidate in candidates
        if (candidate / "warp_simdata").is_dir() and len(list(candidate.glob("warp_simdata-*.dist-info"))) == 1
    ]

    if len(matches) != 1:
        raise RuntimeError(
            "Local warp_simdata package must contain one install tree with "
            "warp_simdata and its distribution metadata"
        )
    return matches[0]


def _read_package_metadata(package_root: Path) -> dict[str, str]:
    metadata = {}
    for line in (package_root / "cae-package-metadata.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            metadata[key] = value
    return metadata


def _validate_package_compatibility(local_root: Path, published_root: Path) -> None:
    local = _read_package_metadata(local_root)
    published = _read_package_metadata(published_root)
    compatibility_fields = (
        "CAE_PACKAGE_NAME",
        "CAE_PACKAGE_VARIANT",
        "CAE_PACKAGE_OPENUSD_VERSION",
        "CAE_PACKAGE_PYTHON_ABI",
        "CAE_PACKAGE_PLATFORM",
    )
    mismatches = [
        f"{field}: local={local.get(field)!r}, expected={published.get(field)!r}"
        for field in compatibility_fields
        if local.get(field) != published.get(field)
    ]
    if mismatches:
        raise RuntimeError("Local cae_openusd_plugins package is incompatible:\n  " + "\n  ".join(mismatches))


def _extract_openusd_plugins(package: Path, cache_root: Path) -> Path:
    if not zipfile.is_zipfile(package):
        raise RuntimeError(f"{OPENUSD_PLUGINS_PACKAGE_ENV} must point to a ZIP package: {package}")

    destination = cache_root / _sha256(package)
    if destination.is_dir():
        return _openusd_plugins_package_root(destination)

    cache_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="extract-", dir=cache_root))
    try:
        _safe_extract_zip(package, temporary)
        _openusd_plugins_package_root(temporary)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return _openusd_plugins_package_root(destination)


def _extract_warp_simdata(package: Path, cache_root: Path) -> Path:
    if not zipfile.is_zipfile(package):
        raise RuntimeError(f"{WARP_SIMDATA_PACKAGE_ENV} must point to a ZIP package: {package}")

    destination = cache_root / _sha256(package)
    if destination.is_dir():
        return _warp_simdata_package_root(destination)

    cache_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="extract-", dir=cache_root))
    try:
        _safe_extract_zip(package, temporary)
        _warp_simdata_package_root(temporary)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return _warp_simdata_package_root(destination)


def _remove_packman_link(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
        return

    is_junction = getattr(path, "is_junction", lambda: False)
    if is_junction():
        os.rmdir(path)
        return

    if path.exists():
        raise RuntimeError(f"Refusing to replace non-link Packman target: {path}")


def _link_directory(source: Path, destination: Path) -> None:
    _remove_packman_link(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(destination), str(source)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    else:
        destination.symlink_to(source, target_is_directory=True)


def main() -> int:
    warp_package = _artifact_path(WARP_SIMDATA_PACKAGE_ENV)
    openusd_package = _artifact_path(OPENUSD_PLUGINS_PACKAGE_ENV)
    if warp_package is None and openusd_package is None:
        return 0

    root = Path(__file__).resolve().parents[1]
    target_deps = root / "_build/target-deps"

    if warp_package is not None:
        print(f"[local-deps] Using warp_simdata package: {warp_package}")
        package_root = _extract_warp_simdata(warp_package, root / "_build/local-deps/warp_simdata")
        _link_directory(package_root, target_deps / "warp_simdata")
        print(f"[local-deps] Linked warp_simdata to: {package_root}")

    if openusd_package is not None:
        print(f"[local-deps] Using cae_openusd_plugins package: {openusd_package}")
        package_root = _extract_openusd_plugins(openusd_package, root / "_build/local-deps/cae_openusd_plugins")
        published_root = target_deps / "cae_openusd_plugins"
        _validate_package_compatibility(package_root, published_root)
        _link_directory(package_root, published_root)
        print(f"[local-deps] Linked cae_openusd_plugins to: {package_root}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"[local-deps] error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
