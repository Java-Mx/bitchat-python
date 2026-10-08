#!/usr/bin/env python3
"""BitChat Linux Packaging Builder.

Automates the complete Linux packaging workflow:
1. Version verification (pyproject.toml vs src/bitchat/__init__.py)
2. PyInstaller freeze of BitChat into a self-contained runtime directory (bitchat.spec)
3. Executable verification (--version, --help, --configure)
4. Debian package compilation (.deb)
5. AppImage compilation (.AppImage)
6. Flatpak manifest & AppStream metainfo validation
7. SHA-256 hash generation
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"
LINUX_PACKAGING_DIR = REPO_ROOT / "packaging" / "linux"


def get_authoritative_version() -> str:
    """Retrieve and verify version from pyproject.toml and bitchat.__init__."""
    pyproject_file = REPO_ROOT / "pyproject.toml"
    if not pyproject_file.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_file}")

    with open(pyproject_file, "rb") as f:
        pyproject_data = tomllib.load(f)

    pyproject_version = pyproject_data.get("project", {}).get("version")
    if not pyproject_version:
        raise ValueError("Could not find project.version in pyproject.toml")

    init_file = SRC_DIR / "bitchat" / "__init__.py"
    if not init_file.exists():
        raise FileNotFoundError(f"__init__.py not found at {init_file}")

    pkg_version = None
    with open(init_file, encoding="utf-8") as f:
        for line in f:
            if line.startswith("__version__"):
                pkg_version = line.split("=")[1].strip().strip("\"'")
                break

    if not pkg_version:
        raise ValueError(f"Could not find __version__ in {init_file}")

    if pyproject_version != pkg_version:
        raise ValueError(
            f"Version mismatch! pyproject.toml has '{pyproject_version}' "
            f"while bitchat/__init__.py has '{pkg_version}'"
        )

    return str(pyproject_version)


def calculate_sha256(file_path: Path) -> str:
    """Compute uppercase SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest().upper()


def build_pyinstaller(spec_file: Path) -> Path:
    """Run PyInstaller with the given Linux spec file."""
    print(f"[*] Running PyInstaller using spec: {spec_file}")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(spec_file),
        "--clean",
        "--noconfirm",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
    ]
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"PyInstaller build failed with exit code {result.returncode}"
        )

    exe_name = "bitchat.exe" if sys.platform == "win32" else "bitchat"
    exe_path = DIST_DIR / "bitchat" / exe_name
    if not exe_path.is_file():
        alt_name = "bitchat" if sys.platform == "win32" else "bitchat.exe"
        alt_path = DIST_DIR / "bitchat" / alt_name
        if alt_path.is_file():
            exe_path = alt_path
        else:
            raise FileNotFoundError(f"Expected binary not found at {exe_path}")

    print(f"[+] PyInstaller build succeeded: {exe_path}")
    return exe_path


def verify_executable(exe_path: Path, expected_version: str) -> None:
    """Verify that the compiled binary executes --version, --help, and --configure."""
    print(f"[*] Verifying compiled executable: {exe_path}")

    # --version
    res_ver = subprocess.run(
        [str(exe_path), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if res_ver.returncode != 0:
        raise RuntimeError(
            f"Executable failed --version (exit {res_ver.returncode}): {res_ver.stderr}"
        )
    if expected_version not in res_ver.stdout:
        raise ValueError(
            f"Expected version {expected_version} not in output: {res_ver.stdout}"
        )
    print(f"[+] Executable --version verified: {res_ver.stdout.strip()}")

    # --help
    res_help = subprocess.run(
        [str(exe_path), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if res_help.returncode != 0:
        raise RuntimeError(
            f"Executable failed --help (exit {res_help.returncode}): {res_help.stderr}"
        )
    if "BitChat" not in res_help.stdout:
        raise ValueError(f"'BitChat' not found in help: {res_help.stdout}")
    print("[+] Executable --help verified.")

    # --configure
    res_conf = subprocess.run(
        [str(exe_path), "--configure"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if res_conf.returncode != 0:
        raise RuntimeError(
            f"Executable failed --configure (exit {res_conf.returncode}): "
            f"{res_conf.stderr}"
        )
    if "BitChat Configuration" not in res_conf.stdout:
        raise ValueError(f"'BitChat Configuration' not found: {res_conf.stdout}")
    print("[+] Executable --configure verified.")


def validate_flatpak_metadata(expected_version: str) -> None:
    """Verify Flatpak manifest and AppStream metainfo consistency."""
    flatpak_dir = LINUX_PACKAGING_DIR / "flatpak"
    manifest_file = flatpak_dir / "io.github.java_mx.bitchat.yaml"
    metainfo_file = flatpak_dir / "io.github.java_mx.bitchat.metainfo.xml"
    desktop_file = flatpak_dir / "io.github.java_mx.bitchat.desktop"

    if not manifest_file.is_file():
        raise FileNotFoundError(f"Missing Flatpak manifest: {manifest_file}")
    if not metainfo_file.is_file():
        raise FileNotFoundError(f"Missing Metainfo file: {metainfo_file}")
    if not desktop_file.is_file():
        raise FileNotFoundError(f"Missing Desktop file: {desktop_file}")

    # Check manifest content
    content = manifest_file.read_text(encoding="utf-8")
    assert "app-id: io.github.java_mx.bitchat" in content
    assert "--share=network" in content
    assert "--system-talk-name=org.bluez" in content

    # Check XML metainfo
    tree = ET.parse(metainfo_file)
    root = tree.getroot()
    id_elem = root.find("id")
    assert id_elem is not None and id_elem.text == "io.github.java_mx.bitchat"

    releases = root.find("releases")
    assert releases is not None
    rel_elem = releases.find("release")
    assert rel_elem is not None
    rel_version = rel_elem.get("version")
    if rel_version != expected_version:
        raise ValueError(
            f"Flatpak metainfo version mismatch: {rel_version} vs {expected_version}"
        )

    print("[+] Flatpak manifest and AppStream metadata verified.")


def build_flatpak_bundle(output_dir: Path | None = None) -> Path | None:
    """Build single-file Flatpak bundle if flatpak-builder and flatpak are available."""
    out_dir = output_dir or DIST_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = LINUX_PACKAGING_DIR / "flatpak" / "io.github.java_mx.bitchat.yaml"
    bundle_path = out_dir / "io.github.java_mx.bitchat.flatpak"

    flatpak_builder = shutil.which("flatpak-builder")
    flatpak = shutil.which("flatpak")

    if not (flatpak_builder and flatpak):
        print(
            "[*] flatpak-builder or flatpak not found on PATH. Validated metadata only."
        )
        return None

    print(f"[*] Building Flatpak bundle with {flatpak_builder}...")
    build_dir = BUILD_DIR / "flatpak_build"
    repo_dir = BUILD_DIR / "flatpak_repo"

    builder_cmd = [
        flatpak_builder,
        "--force-clean",
        "--repo=" + str(repo_dir),
        "--share=network",
        str(build_dir),
        str(manifest_file),
    ]
    res = subprocess.run(builder_cmd, cwd=str(REPO_ROOT), check=False)
    if res.returncode != 0:
        print(f"[!] flatpak-builder failed with return code {res.returncode}")
        return None

    bundle_cmd = [
        flatpak,
        "build-bundle",
        str(repo_dir),
        str(bundle_path),
        "io.github.java_mx.bitchat",
    ]
    res_bundle = subprocess.run(bundle_cmd, cwd=str(REPO_ROOT), check=False)
    if res_bundle.returncode != 0 or not bundle_path.is_file():
        print(
            f"[!] flatpak build-bundle failed with return code {res_bundle.returncode}"
        )
        return None

    sha = calculate_sha256(bundle_path)
    sha_file = out_dir / f"{bundle_path.name}.sha256"
    sha_file.write_text(f"{sha} *{bundle_path.name}\n", encoding="utf-8")
    print(f"[+] Flatpak bundle ready: {bundle_path} (SHA-256: {sha})")
    return bundle_path


def main() -> int:
    parser = argparse.ArgumentParser(description="BitChat Linux Packaging Builder")
    parser.add_argument(
        "--skip-pyinstaller", action="store_true", help="Skip PyInstaller build"
    )
    parser.add_argument(
        "--skip-deb", action="store_true", help="Skip Debian package (.deb) build"
    )
    parser.add_argument(
        "--skip-appimage", action="store_true", help="Skip AppImage build"
    )
    parser.add_argument(
        "--skip-flatpak", action="store_true", help="Skip Flatpak validation"
    )
    parser.add_argument(
        "--build-flatpak", action="store_true", help="Build single-file Flatpak bundle"
    )
    args = parser.parse_args()

    version = get_authoritative_version()
    print(f"=== Building BitChat v{version} Linux Distributables ===")

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    source_bundle = DIST_DIR / "bitchat"

    # 1. PyInstaller
    if not args.skip_pyinstaller:
        spec_file = LINUX_PACKAGING_DIR / "bitchat.spec"
        exe_path = build_pyinstaller(spec_file)
        if sys.platform.startswith("linux"):
            verify_executable(exe_path, version)
    else:
        exe_path = source_bundle / "bitchat"
        if exe_path.is_file() and sys.platform.startswith("linux"):
            verify_executable(exe_path, version)

    # 2. Debian Package (.deb)
    if not args.skip_deb:
        sys.path.insert(0, str(LINUX_PACKAGING_DIR / "deb"))
        import importlib

        deb_mod = importlib.import_module("build_deb")
        deb_file = deb_mod.build_deb_package(source_bundle)
        print(f"[+] .deb ready: {deb_file}")

    # 3. AppImage
    if not args.skip_appimage:
        sys.path.insert(0, str(LINUX_PACKAGING_DIR / "appimage"))
        import importlib

        appimage_mod = importlib.import_module("build_appimage")
        appimage_file = appimage_mod.build_appimage_package(source_bundle)
        print(f"[+] AppImage ready: {appimage_file}")

    # 4. Flatpak Validation & Bundle Build
    if not args.skip_flatpak:
        validate_flatpak_metadata(version)
        should_build = args.build_flatpak or (
            sys.platform.startswith("linux") and bool(shutil.which("flatpak-builder"))
        )
        if should_build:
            build_flatpak_bundle()

    print(f"=== Linux Packaging finished successfully for BitChat v{version} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
