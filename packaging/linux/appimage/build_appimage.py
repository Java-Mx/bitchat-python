#!/usr/bin/env python3
"""BitChat AppImage Packaging Builder.

Assembles BitChat.AppDir and packages the self-contained Linux application into
BitChat-<version>-x86_64.AppImage.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"
APPIMAGE_PKG_DIR = REPO_ROOT / "packaging" / "linux" / "appimage"


def get_authoritative_version() -> str:
    """Retrieve and verify version from pyproject.toml."""
    pyproject_file = REPO_ROOT / "pyproject.toml"
    if not pyproject_file.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_file}")

    with open(pyproject_file, "rb") as f:
        data = tomllib.load(f)

    version = data.get("project", {}).get("version")
    if not version:
        raise ValueError("Could not find project.version in pyproject.toml")
    return str(version)


def calculate_sha256(file_path: Path) -> str:
    """Compute uppercase SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest().upper()


def assemble_appdir(source_dir: Path) -> Path:
    """Construct BitChat.AppDir staging directory."""
    appdir = BUILD_DIR / "BitChat.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)

    usr_bin = appdir / "usr" / "bin"
    usr_lib = appdir / "usr" / "lib" / "bitchat"
    usr_share_apps = appdir / "usr" / "share" / "applications"
    usr_share_meta = appdir / "usr" / "share" / "metainfo"

    for d in (usr_bin, usr_lib, usr_share_apps, usr_share_meta):
        d.mkdir(parents=True, exist_ok=True)

    print(f"[*] Assembling AppDir from {source_dir}...")
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source bundle not found at {source_dir}")

    # Copy runtime files
    for item in source_dir.iterdir():
        dest = usr_lib / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    # Copy AppRun
    apprun_src = APPIMAGE_PKG_DIR / "AppRun"
    if not apprun_src.is_file():
        raise FileNotFoundError(f"Missing AppRun at {apprun_src}")
    shutil.copy2(apprun_src, appdir / "AppRun")
    with contextlib.suppress(Exception):
        (appdir / "AppRun").chmod(0o755)

    # Launcher wrapper in usr/bin/bitchat
    usr_bin_bitchat = usr_bin / "bitchat"
    launcher_code = """#!/bin/sh
exec "$(dirname "$0")/../lib/bitchat/bitchat" "$@"
"""
    usr_bin_bitchat.write_text(launcher_code, encoding="utf-8")
    with contextlib.suppress(Exception):
        usr_bin_bitchat.chmod(0o755)

    # Desktop files
    desktop_src = APPIMAGE_PKG_DIR / "bitchat.desktop"
    if desktop_src.is_file():
        shutil.copy2(desktop_src, appdir / "bitchat.desktop")
        shutil.copy2(desktop_src, usr_share_apps / "bitchat.desktop")

    # Metainfo
    metainfo_src = (
        REPO_ROOT
        / "packaging"
        / "linux"
        / "flatpak"
        / "io.github.java_mx.bitchat.metainfo.xml"
    )
    if metainfo_src.is_file():
        shutil.copy2(metainfo_src, usr_share_meta / metainfo_src.name)

    return appdir


def create_standalone_appimage_bundle(
    appdir: Path, output_file: Path, version: str
) -> None:
    """Create a self-executing universal AppImage bundle."""
    # Build compressed tar payload of AppDir contents
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        for root, dirs, files in os.walk(appdir):
            for d in dirs:
                dir_path = Path(root) / d
                rel_d = dir_path.relative_to(appdir)
                ti = tar.gettarinfo(str(dir_path), arcname=rel_d.as_posix())
                ti.uid = 0
                ti.gid = 0
                ti.mode = 0o755
                tar.addfile(ti)

            for file in files:
                file_path = Path(root) / file
                rel_file = file_path.relative_to(appdir)
                ti = tar.gettarinfo(str(file_path), arcname=rel_file.as_posix())
                ti.uid = 0
                ti.gid = 0
                if "bin" in rel_file.parts or file in ("AppRun", "bitchat"):
                    ti.mode = 0o755
                else:
                    ti.mode = 0o644
                with open(file_path, "rb") as fp:
                    tar.addfile(ti, fp)

    payload = buf.getvalue()

    # POSIX shell self-extracting runtime header
    header = f"""#!/bin/sh
# BitChat Universal Portable Self-Contained AppImage Runtime
# Version: {version}
set -e

# Identify runtime cache directory using executable hash to prevent stale caching
EXE_HASH=$(md5sum "$0" 2>/dev/null | cut -d' ' -f1 || true)
if [ -z "${{EXE_HASH}}" ]; then
    EXE_HASH=$(cksum "$0" 2>/dev/null | cut -d' ' -f1 || echo "default")
fi
CACHEDIR="${{HOME:-/tmp}}/.cache/bitchat/appimage/{version}_${{EXE_HASH}}"

if [ ! -f "${{CACHEDIR}}/.extracted" ] || [ ! -x "${{CACHEDIR}}/AppRun" ]; then
    mkdir -p "${{CACHEDIR}}"
    PAYLOAD_LINE=$(awk '/^__APPIMAGE_PAYLOAD_BELOW__/ {{print NR + 1; exit 0; }}' "$0")
    tail -n +"${{PAYLOAD_LINE}}" "$0" | tar -xz -C "${{CACHEDIR}}"
    chmod -R +x "${{CACHEDIR}}/usr/bin" 2>/dev/null || true
    chmod +x "${{CACHEDIR}}/AppRun" 2>/dev/null || true
    chmod +x "${{CACHEDIR}}/usr/lib/bitchat/bitchat" 2>/dev/null || true
    touch "${{CACHEDIR}}/.extracted"
fi

exec "${{CACHEDIR}}/AppRun" "$@"
exit 1
__APPIMAGE_PAYLOAD_BELOW__
""".encode("ascii")

    with open(output_file, "wb") as f:
        f.write(header)
        f.write(payload)

    with contextlib.suppress(Exception):
        output_file.chmod(0o755)


def build_appimage_package(source_dir: Path, output_dir: Path | None = None) -> Path:
    """Build BitChat AppImage."""
    version = get_authoritative_version()
    out_dir = output_dir or DIST_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    appdir = assemble_appdir(source_dir)
    appimage_filename = f"BitChat-{version}-x86_64.AppImage"
    output_path = out_dir / appimage_filename

    if output_path.exists():
        output_path.unlink()

    appimagetool = shutil.which("appimagetool")
    if appimagetool:
        print(f"[*] Building {appimage_filename} using system appimagetool...")
        env = os.environ.copy()
        env["ARCH"] = "x86_64"
        res = subprocess.run(
            [appimagetool, str(appdir), str(output_path)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            print(
                f"[!] appimagetool failed: {res.stderr}. "
                "Using portable bundle creator..."
            )
            create_standalone_appimage_bundle(appdir, output_path, version)
    else:
        print(f"[*] Packaging {appimage_filename} with portable runtime bundle...")
        create_standalone_appimage_bundle(appdir, output_path, version)

    if not output_path.is_file():
        raise FileNotFoundError(f"AppImage was not created at {output_path}")

    with contextlib.suppress(Exception):
        output_path.chmod(0o755)

    sha = calculate_sha256(output_path)
    sha_file = out_dir / f"{appimage_filename}.sha256"
    sha_file.write_text(f"{sha} *{appimage_filename}\n", encoding="utf-8")

    print(f"[+] AppImage built successfully: {output_path} (SHA-256: {sha})")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="BitChat AppImage Builder")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DIST_DIR / "bitchat",
        help="Path to PyInstaller runtime directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DIST_DIR,
        help="Path to output directory for AppImage",
    )
    args = parser.parse_args()

    appimage_path = build_appimage_package(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
    )
    print(f"Build complete: {appimage_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
