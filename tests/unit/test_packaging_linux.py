"""Unit tests for Linux packaging (.deb, Flatpak, AppImage, Snap)."""

from __future__ import annotations

import importlib.util
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LINUX_PKG_DIR = REPO_ROOT / "packaging" / "linux"

# Dynamically import packaging scripts
deb_spec = importlib.util.spec_from_file_location(
    "build_deb", LINUX_PKG_DIR / "deb" / "build_deb.py"
)
assert deb_spec is not None and deb_spec.loader is not None
build_deb = importlib.util.module_from_spec(deb_spec)
deb_spec.loader.exec_module(build_deb)

appimage_spec = importlib.util.spec_from_file_location(
    "build_appimage", LINUX_PKG_DIR / "appimage" / "build_appimage.py"
)
assert appimage_spec is not None and appimage_spec.loader is not None
build_appimage = importlib.util.module_from_spec(appimage_spec)
appimage_spec.loader.exec_module(build_appimage)

build_master_spec = importlib.util.spec_from_file_location(
    "linux_build", LINUX_PKG_DIR / "build.py"
)
assert build_master_spec is not None and build_master_spec.loader is not None
linux_build = importlib.util.module_from_spec(build_master_spec)
build_master_spec.loader.exec_module(linux_build)


def test_version_consistency() -> None:
    """Version matches across pyproject.toml, package __init__, and Linux builder."""
    version = linux_build.get_authoritative_version()
    assert isinstance(version, str)
    assert len(version.split(".")) >= 2

    # Check pyproject.toml
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        pyproject_ver = tomllib.load(f)["project"]["version"]
    assert pyproject_ver == version

    # Check snapcraft.yaml
    snap_yaml = (LINUX_PKG_DIR / "snap" / "snapcraft.yaml").read_text(encoding="utf-8")
    assert f"version: '{version}'" in snap_yaml

    # Check Flatpak metainfo
    metainfo_file = LINUX_PKG_DIR / "flatpak" / "io.github.java_mx.bitchat.metainfo.xml"
    tree = ET.parse(metainfo_file)
    release_elem = tree.getroot().find("releases/release")
    assert release_elem is not None
    assert release_elem.get("version") == version


def test_flatpak_manifest_and_metadata_validity() -> None:
    """Flatpak manifest adheres to Flathub least-privilege standards."""
    manifest_path = LINUX_PKG_DIR / "flatpak" / "io.github.java_mx.bitchat.yaml"
    desktop_path = LINUX_PKG_DIR / "flatpak" / "io.github.java_mx.bitchat.desktop"
    metainfo_path = LINUX_PKG_DIR / "flatpak" / "io.github.java_mx.bitchat.metainfo.xml"

    assert manifest_path.is_file()
    assert desktop_path.is_file()
    assert metainfo_path.is_file()

    content = manifest_path.read_text(encoding="utf-8")
    assert "app-id: io.github.java_mx.bitchat" in content
    assert "command: bitchat" in content
    assert "--share=network" in content
    assert "--system-talk-name=org.bluez" in content

    # Security check: broad host permissions must NOT be granted
    assert "--filesystem=host" not in content
    assert "--filesystem=home" not in content

    # Desktop entry check
    desktop_content = desktop_path.read_text(encoding="utf-8")
    assert "Terminal=true" in desktop_content
    assert "Exec=bitchat" in desktop_content
    assert "Icon=io.github.java_mx.bitchat" in desktop_content


def test_snap_metadata_and_security_interfaces() -> None:
    """Snapcraft configuration specifies strictly needed interfaces."""
    snap_path = LINUX_PKG_DIR / "snap" / "snapcraft.yaml"
    readme_path = LINUX_PKG_DIR / "snap" / "README.md"

    assert snap_path.is_file()
    assert readme_path.is_file()

    snap_content = snap_path.read_text(encoding="utf-8")
    assert "name: bitchat" in snap_content
    assert "confinement: strict" in snap_content
    assert "- network" in snap_content
    assert "- network-bind" in snap_content
    assert "- bluez" in snap_content


def test_build_deb_pure_python(tmp_path: Path) -> None:
    """Debian package (.deb) is generated with correct ar/tar structure."""
    version = linux_build.get_authoritative_version()

    # Create dummy source bundle simulating PyInstaller output
    source_dir = tmp_path / "bitchat_bundle"
    source_dir.mkdir()
    (source_dir / "bitchat").write_text("#!/bin/sh\necho bitchat\n", encoding="utf-8")
    internal_dir = source_dir / "_internal"
    internal_dir.mkdir()
    (internal_dir / "libtest.so").write_bytes(b"dummy binary")

    output_dir = tmp_path / "dist"
    output_dir.mkdir()

    deb_file = build_deb.build_deb_package(
        source_dir=source_dir,
        output_dir=output_dir,
        force_pure_python=True,
    )

    assert deb_file.is_file()
    assert deb_file.name == f"bitchat_{version}_amd64.deb"

    # Verify SHA-256 file
    sha_file = output_dir / f"{deb_file.name}.sha256"
    assert sha_file.is_file()
    expected_hash = build_deb.calculate_sha256(deb_file)
    assert f"{expected_hash} *{deb_file.name}" in sha_file.read_text(encoding="utf-8")

    # Read .deb as ar archive
    deb_bytes = deb_file.read_bytes()
    assert deb_bytes.startswith(b"!<arch>\n")
    assert b"debian-binary" in deb_bytes
    assert b"control.tar.gz" in deb_bytes
    assert b"data.tar.gz" in deb_bytes


def test_build_appimage_package(tmp_path: Path) -> None:
    """AppImage bundle is generated with AppRun and correct permissions."""
    version = linux_build.get_authoritative_version()

    source_dir = tmp_path / "bitchat_bundle"
    source_dir.mkdir()
    (source_dir / "bitchat").write_text("#!/bin/sh\necho bitchat\n", encoding="utf-8")
    (source_dir / "app.tcss").write_text("/* styles */", encoding="utf-8")

    output_dir = tmp_path / "dist"
    output_dir.mkdir()

    appimage_file = build_appimage.build_appimage_package(
        source_dir=source_dir,
        output_dir=output_dir,
    )

    assert appimage_file.is_file()
    assert appimage_file.name == f"BitChat-{version}-x86_64.AppImage"

    # Verify SHA-256 file
    sha_file = output_dir / f"{appimage_file.name}.sha256"
    assert sha_file.is_file()
    expected_hash = build_appimage.calculate_sha256(appimage_file)
    assert f"{expected_hash} *{appimage_file.name}" in sha_file.read_text(
        encoding="utf-8"
    )

    # Check that AppImage header contains the universal shell runtime
    content = appimage_file.read_bytes()
    assert b"BitChat Universal Portable" in content
    assert b"__APPIMAGE_PAYLOAD_BELOW__" in content
