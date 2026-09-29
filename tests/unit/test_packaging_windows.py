"""Tests for Windows packaging and WinGet manifest generation."""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_SCRIPT_PATH = REPO_ROOT / "packaging" / "windows" / "build.py"

_spec = importlib.util.spec_from_file_location("windows_build", BUILD_SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
windows_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(windows_build)

calculate_sha256 = windows_build.calculate_sha256
generate_winget_manifests = windows_build.generate_winget_manifests
get_authoritative_version = windows_build.get_authoritative_version
locate_iscc = windows_build.locate_iscc


def test_get_authoritative_version() -> None:
    """Authoritative version matches in pyproject.toml and bitchat.__init__."""
    version = get_authoritative_version()
    assert isinstance(version, str)
    assert len(version.split(".")) >= 2


def test_calculate_sha256(tmp_path: Path) -> None:
    """SHA-256 calculation matches hashlib digest."""
    test_file = tmp_path / "sample.bin"
    sample_bytes = b"BitChat Windows Installer Packaging Test"
    test_file.write_bytes(sample_bytes)

    expected_hash = hashlib.sha256(sample_bytes).hexdigest().upper()
    assert calculate_sha256(test_file) == expected_hash


def test_generate_winget_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WinGet manifests are generated with accurate fields and schema."""
    version = get_authoritative_version()
    dummy_sha = "A" * 64

    # Redirect manifests and packaging output dirs to tmp_path
    monkeypatch.setattr(windows_build, "MANIFESTS_ROOT", tmp_path / "manifests")
    monkeypatch.setattr(windows_build, "PACKAGING_DIR", tmp_path / "packaging")

    manifest_dir, singleton_file = generate_winget_manifests(version, dummy_sha)

    # Verify multi-file manifest files exist
    version_file = manifest_dir / "Java-Mx.BitChat.yaml"
    installer_file = manifest_dir / "Java-Mx.BitChat.installer.yaml"
    locale_file = manifest_dir / "Java-Mx.BitChat.locale.en-US.yaml"

    assert version_file.is_file()
    assert installer_file.is_file()
    assert locale_file.is_file()
    assert singleton_file.is_file()

    # Check contents
    version_content = version_file.read_text(encoding="utf-8")
    assert "PackageIdentifier: Java-Mx.BitChat" in version_content
    assert f"PackageVersion: {version}" in version_content

    installer_content = installer_file.read_text(encoding="utf-8")
    assert "PackageIdentifier: Java-Mx.BitChat" in installer_content
    assert "InstallerType: inno" in installer_content
    assert "Architecture: x64" in installer_content
    assert dummy_sha in installer_content
    assert "Commands:\n  - bitchat" in installer_content
    assert f"BitChat-{version}-windows-x64.exe" in installer_content

    locale_content = locale_file.read_text(encoding="utf-8")
    assert "PackageIdentifier: Java-Mx.BitChat" in locale_content
    assert "PackageName: BitChat" in locale_content
    assert "Publisher: Java-Mx" in locale_content
    assert "License: MIT" in locale_content

    singleton_content = singleton_file.read_text(encoding="utf-8")
    assert "PackageIdentifier: Java-Mx.BitChat" in singleton_content
    assert "ManifestType: singleton" in singleton_content


@pytest.mark.skipif(
    shutil.which("winget") is None, reason="winget CLI not available on system"
)
def test_winget_manifest_validation() -> None:
    """Existing generated WinGet manifests pass `winget validate`."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    version = get_authoritative_version()
    manifest_dir = repo_root / "manifests" / "j" / "Java-Mx" / "BitChat" / version
    singleton_file = (
        repo_root / "packaging" / "windows" / "winget" / "Java-Mx.BitChat.yaml"
    )

    assert manifest_dir.is_dir(), f"Manifest directory {manifest_dir} does not exist"
    assert singleton_file.is_file(), f"Singleton file {singleton_file} does not exist"

    # Validate multi-file manifest
    res_multi = subprocess.run(
        ["winget", "validate", str(manifest_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_multi.returncode == 0, (
        f"Validation failed:\n{res_multi.stderr}\n{res_multi.stdout}"
    )

    # Validate singleton manifest
    res_single = subprocess.run(
        ["winget", "validate", "--manifest", str(singleton_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_single.returncode == 0, (
        f"Validation failed:\n{res_single.stderr}\n{res_single.stdout}"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
def test_locate_iscc() -> None:
    """ISCC is locatable on Windows if Inno Setup is installed."""
    iscc = locate_iscc()
    # If installed in standard paths, it must exist
    if iscc is not None:
        assert iscc.is_file()
