#!/usr/bin/env python3
"""BitChat Windows Distributable & WinGet Packaging Builder.

Automates the complete Windows packaging workflow:
1. Version verification (pyproject.toml vs src/bitchat/__init__.py)
2. PyInstaller freeze of BitChat into a self-contained runtime directory
3. Executable verification (--version and --help)
4. Inno Setup installer compilation (BitChat-<version>-windows-x64.exe)
5. SHA-256 hash generation
6. WinGet manifest generation (multi-file and singleton)
7. WinGet manifest schema validation via `winget validate`
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"
PACKAGING_DIR = REPO_ROOT / "packaging" / "windows"
MANIFESTS_ROOT = REPO_ROOT / "manifests"


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

    return pyproject_version


def locate_iscc() -> Path | None:
    """Find Inno Setup Compiler (ISCC.exe) across common Windows locations."""
    # 1. Check PATH
    iscc_path = shutil.which("iscc") or shutil.which("ISCC.exe")
    if iscc_path:
        return Path(iscc_path)

    # 2. Known standard install paths
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    prog_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
    prog_files = Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))

    candidates = [
        local_app_data / "Programs" / "Inno Setup 6" / "ISCC.exe",
        prog_files_x86 / "Inno Setup 6" / "ISCC.exe",
        prog_files / "Inno Setup 6" / "ISCC.exe",
        local_app_data / "Programs" / "Inno Setup 7" / "ISCC.exe",
        prog_files_x86 / "Inno Setup 7" / "ISCC.exe",
        prog_files / "Inno Setup 7" / "ISCC.exe",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def calculate_sha256(file_path: Path) -> str:
    """Compute uppercase SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest().upper()


def build_pyinstaller(spec_file: Path) -> Path:
    """Run PyInstaller with the given spec file."""
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

    exe_path = DIST_DIR / "bitchat" / "bitchat.exe"
    if not exe_path.is_file():
        raise FileNotFoundError(f"Expected binary not found at {exe_path}")

    print(f"[+] PyInstaller build succeeded: {exe_path}")
    return exe_path


def verify_executable(exe_path: Path, expected_version: str) -> None:
    """Verify that the compiled binary executes --version and --help properly."""
    print(f"[*] Verifying compiled executable: {exe_path}")

    res_ver = subprocess.run(
        [str(exe_path), "--version"],
        capture_output=True,
        text=True,
        timeout=15,
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

    res_help = subprocess.run(
        [str(exe_path), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if res_help.returncode != 0:
        raise RuntimeError(
            f"Executable failed --help (exit {res_help.returncode}): {res_help.stderr}"
        )
    if "BitChat" not in res_help.stdout:
        raise ValueError(f"'BitChat' not found in help: {res_help.stdout}")
    print("[+] Executable --help verified.")


def build_inno_setup(version: str, iscc_path: Path) -> Path:
    """Compile Inno Setup installer."""
    iss_file = PACKAGING_DIR / "bitchat.iss"
    if not iss_file.is_file():
        raise FileNotFoundError(f"Inno Setup script not found at {iss_file}")

    installer_basename = f"BitChat-{version}-windows-x64"
    print(f"[*] Compiling Inno Setup installer: {installer_basename}.exe")

    cmd = [
        str(iscc_path),
        f"/DMyAppVersion={version}",
        f"/DMyOutputBaseFilename={installer_basename}",
        str(iss_file),
    ]

    result = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Inno Setup compilation failed with code {result.returncode}"
        )

    installer_path = DIST_DIR / f"{installer_basename}.exe"
    if not installer_path.is_file():
        raise FileNotFoundError(f"Installer not found at {installer_path}")

    print(f"[+] Installer built successfully: {installer_path}")
    return installer_path


def generate_winget_manifests(version: str, installer_sha256: str) -> tuple[Path, Path]:
    """Generate official multi-file manifests and repository singleton manifest."""
    installer_filename = f"BitChat-{version}-windows-x64.exe"
    base_release_url = "https://github.com/Java-Mx/bitchat-python/releases/download"
    installer_url = f"{base_release_url}/v{version}/{installer_filename}"

    manifest_dir = MANIFESTS_ROOT / "j" / "Java-Mx" / "BitChat" / version
    manifest_dir.mkdir(parents=True, exist_ok=True)

    version_yaml = f"""# Created using BitChat automated packaging workflow
# yaml-language-server: $schema=https://aka.ms/winget-manifest.version.1.6.0.schema.json

PackageIdentifier: Java-Mx.BitChat
PackageVersion: {version}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.6.0
"""
    (manifest_dir / "Java-Mx.BitChat.yaml").write_text(version_yaml, encoding="utf-8")

    installer_yaml = f"""# Created using BitChat automated packaging workflow
# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.1.6.0.schema.json

PackageIdentifier: Java-Mx.BitChat
PackageVersion: {version}
InstallerLocale: en-US
InstallerType: inno
Scope: user
InstallModes:
  - interactive
  - silent
  - silentWithProgress
UpgradeBehavior: install
Commands:
  - bitchat
ReleaseDate: 2026-09-29
Installers:
  - Architecture: x64
    InstallerUrl: {installer_url}
    InstallerSha256: {installer_sha256}
ManifestType: installer
ManifestVersion: 1.6.0
"""
    (manifest_dir / "Java-Mx.BitChat.installer.yaml").write_text(
        installer_yaml, encoding="utf-8"
    )

    locale_yaml = f"""# Created using BitChat automated packaging workflow
# yaml-language-server: $schema=https://aka.ms/winget-manifest.defaultLocale.1.6.0.schema.json

PackageIdentifier: Java-Mx.BitChat
PackageVersion: {version}
PackageLocale: en-US
Publisher: Java-Mx
PublisherUrl: https://github.com/Java-Mx
PublisherSupportUrl: https://github.com/Java-Mx/bitchat-python/issues
PackageName: BitChat
PackageUrl: https://github.com/Java-Mx/bitchat-python
License: MIT
LicenseUrl: https://github.com/Java-Mx/bitchat-python/blob/main/LICENSE
Copyright: Copyright (c) BitChat Contributors
ShortDescription: Python terminal client for BitChat over Bluetooth Low Energy
Description: |-
  BitChat is a secure peer-to-peer terminal chat client operating over BLE.
  It features decentralized mesh networking, end-to-end encryption with
  Noise Protocol / X25519 / AES-GCM, and an interactive terminal UI.
Moniker: bitchat
Tags:
  - bluetooth
  - ble
  - chat
  - mesh
  - p2p
  - terminal
ReleaseNotesUrl: https://github.com/Java-Mx/bitchat-python/releases/tag/v{version}
ManifestType: defaultLocale
ManifestVersion: 1.6.0
"""
    (manifest_dir / "Java-Mx.BitChat.locale.en-US.yaml").write_text(
        locale_yaml, encoding="utf-8"
    )

    winget_pkg_dir = PACKAGING_DIR / "winget"
    winget_pkg_dir.mkdir(parents=True, exist_ok=True)
    singleton_file = winget_pkg_dir / "Java-Mx.BitChat.yaml"

    singleton_yaml = f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.singleton.1.6.0.schema.json

PackageIdentifier: Java-Mx.BitChat
PackageVersion: {version}
PackageLocale: en-US
Publisher: Java-Mx
PublisherUrl: https://github.com/Java-Mx
PublisherSupportUrl: https://github.com/Java-Mx/bitchat-python/issues
PackageName: BitChat
PackageUrl: https://github.com/Java-Mx/bitchat-python
License: MIT
LicenseUrl: https://github.com/Java-Mx/bitchat-python/blob/main/LICENSE
Copyright: Copyright (c) BitChat Contributors
ShortDescription: Python terminal client for BitChat over Bluetooth Low Energy
Description: |-
  BitChat is a secure peer-to-peer terminal chat client operating over BLE.
  It features decentralized mesh networking, end-to-end encryption with
  Noise Protocol / X25519 / AES-GCM, and an interactive terminal UI.
Moniker: bitchat
Tags:
  - bluetooth
  - ble
  - chat
  - mesh
  - p2p
  - terminal
ReleaseNotesUrl: https://github.com/Java-Mx/bitchat-python/releases/tag/v{version}
Installers:
  - Architecture: x64
    InstallerType: inno
    Scope: user
    InstallerUrl: {installer_url}
    InstallerSha256: {installer_sha256}
    UpgradeBehavior: install
ManifestType: singleton
ManifestVersion: 1.6.0
"""
    singleton_file.write_text(singleton_yaml, encoding="utf-8")

    print(f"[+] WinGet multi-file manifests written to: {manifest_dir}")
    print(f"[+] WinGet singleton manifest written to: {singleton_file}")
    return manifest_dir, singleton_file


def validate_winget_manifests(manifest_dir: Path, singleton_file: Path) -> bool:
    """Validate manifests using `winget validate` if available on the system."""
    winget_path = shutil.which("winget")
    if not winget_path:
        print("[!] `winget` command not found in PATH. Skipping validation.")
        return False

    print(f"[*] Validating manifests in {manifest_dir} with `winget validate`...")
    res_multi = subprocess.run(
        [winget_path, "validate", str(manifest_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if res_multi.returncode != 0:
        print(f"[x] Multi-file validation failed:\n{res_multi.stderr}")
        return False
    print("[+] Multi-file manifest validation passed!")

    print(f"[*] Validating singleton manifest {singleton_file}...")
    res_single = subprocess.run(
        [winget_path, "validate", "--manifest", str(singleton_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    if res_single.returncode != 0:
        print(f"[x] Singleton validation failed:\n{res_single.stderr}")
        return False
    print("[+] Singleton manifest validation passed!")

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="BitChat Windows & WinGet Packager")
    parser.add_argument(
        "--skip-pyinstaller", action="store_true", help="Skip PyInstaller build"
    )
    parser.add_argument(
        "--skip-installer", action="store_true", help="Skip Inno Setup build"
    )
    parser.add_argument(
        "--skip-winget", action="store_true", help="Skip WinGet manifest generation"
    )
    args = parser.parse_args()

    version = get_authoritative_version()
    print(f"=== Building BitChat v{version} Windows Distributable ===")

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 1. PyInstaller
    if not args.skip_pyinstaller:
        spec_file = PACKAGING_DIR / "bitchat.spec"
        exe_path = build_pyinstaller(spec_file)
        verify_executable(exe_path, version)
    else:
        exe_path = DIST_DIR / "bitchat" / "bitchat.exe"
        if exe_path.is_file():
            verify_executable(exe_path, version)
        else:
            print(f"[!] Warning: {exe_path} not found.")

    # 2. Inno Setup
    installer_path = DIST_DIR / f"BitChat-{version}-windows-x64.exe"
    if not args.skip_installer:
        iscc_path = locate_iscc()
        if not iscc_path:
            raise FileNotFoundError(
                "Inno Setup Compiler (ISCC.exe) not found. "
                "Install Inno Setup 6 (e.g. `winget install JRSoftware.InnoSetup`)."
            )
        installer_path = build_inno_setup(version, iscc_path)

    # 3. Checksum
    if installer_path.is_file():
        sha256_hash = calculate_sha256(installer_path)
        sha256_file = DIST_DIR / f"{installer_path.name}.sha256"
        sha256_file.write_text(
            f"{sha256_hash} *{installer_path.name}\n", encoding="utf-8"
        )
        print(f"[+] Installer SHA-256: {sha256_hash}")
        print(f"[+] Checksum file written: {sha256_file}")

        # 4. WinGet manifests
        if not args.skip_winget:
            multi_dir, single_file = generate_winget_manifests(version, sha256_hash)
            validate_winget_manifests(multi_dir, single_file)
    else:
        print(f"[!] Installer {installer_path} missing. Skipping SHA/WinGet.")

    print(f"=== Build finished successfully for BitChat v{version} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
