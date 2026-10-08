#!/usr/bin/env python3
"""BitChat Linux Native .deb Package Builder.

Packages the self-contained PyInstaller build of BitChat into a compliant Debian/Ubuntu
package (.deb) supporting `sudo apt install ./<package>.deb` or `sudo dpkg -i`.
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
DEB_PKG_DIR = REPO_ROOT / "packaging" / "linux" / "deb"


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


def _format_ar_header(name: str, size: int, mode: int = 0o100644) -> bytes:
    """Create a 60-byte standard POSIX/Debian ar file member header."""
    # name: 16 chars, mtime: 12 chars, uid: 6 chars, gid: 6 chars
    # mode: 8 chars octal, size: 10 chars, trailer: `\n
    hdr = f"{name:<16}{0:<12}{0:<6}{0:<6}{oct(mode)[2:]:>8}{size:<10}`\n"
    return hdr.encode("ascii")


def create_deb_pure_python(staging_dir: Path, output_deb_path: Path) -> None:
    """Construct a valid .deb archive in pure Python without requiring dpkg-deb."""
    debian_dir = staging_dir / "DEBIAN"
    usr_dir = staging_dir / "usr"

    # 1. debian-binary
    debian_binary_bytes = b"2.0\n"

    # 2. control.tar.gz
    control_buf = io.BytesIO()
    with tarfile.open(
        fileobj=control_buf, mode="w:gz", format=tarfile.PAX_FORMAT
    ) as tar:
        for f in sorted(debian_dir.iterdir()):
            ti = tar.gettarinfo(str(f), arcname=f"./{f.name}")
            ti.uid = 0
            ti.gid = 0
            ti.uname = "root"
            ti.gname = "root"
            ti.mtime = 0
            if f.name in ("postinst", "prerm", "postrm", "preinst"):
                ti.mode = 0o755
            else:
                ti.mode = 0o644
            if f.is_file():
                with open(f, "rb") as fp:
                    tar.addfile(ti, fp)
    control_bytes = control_buf.getvalue()

    # 3. data.tar.gz
    data_buf = io.BytesIO()
    with tarfile.open(fileobj=data_buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        for root, _dirs, files in os.walk(usr_dir):
            rel_root = Path(root).relative_to(staging_dir)
            # Add directory entry
            ti_dir = tar.gettarinfo(root, arcname=f"./{rel_root.as_posix()}")
            ti_dir.uid = 0
            ti_dir.gid = 0
            ti_dir.uname = "root"
            ti_dir.gname = "root"
            ti_dir.mtime = 0
            ti_dir.mode = 0o755
            tar.addfile(ti_dir)

            for file in sorted(files):
                file_path = Path(root) / file
                rel_file = file_path.relative_to(staging_dir)
                ti = tar.gettarinfo(str(file_path), arcname=f"./{rel_file.as_posix()}")
                ti.uid = 0
                ti.gid = 0
                ti.uname = "root"
                ti.gname = "root"
                ti.mtime = 0
                if file in ("bitchat",) or "bin" in rel_file.parts:
                    ti.mode = 0o755
                else:
                    ti.mode = 0o644
                with open(file_path, "rb") as fp:
                    tar.addfile(ti, fp)
    data_bytes = data_buf.getvalue()

    # Write ar archive: !<arch>\n + headers + members
    with open(output_deb_path, "wb") as deb:
        deb.write(b"!<arch>\n")

        # Member 1: debian-binary
        deb.write(_format_ar_header("debian-binary", len(debian_binary_bytes)))
        deb.write(debian_binary_bytes)
        if len(debian_binary_bytes) % 2 != 0:
            deb.write(b"\n")

        # Member 2: control.tar.gz
        deb.write(_format_ar_header("control.tar.gz", len(control_bytes)))
        deb.write(control_bytes)
        if len(control_bytes) % 2 != 0:
            deb.write(b"\n")

        # Member 3: data.tar.gz
        deb.write(_format_ar_header("data.tar.gz", len(data_bytes)))
        deb.write(data_bytes)
        if len(data_bytes) % 2 != 0:
            deb.write(b"\n")


def build_deb_package(
    source_dir: Path, output_dir: Path | None = None, force_pure_python: bool = False
) -> Path:
    """Assemble staging filesystem and build .deb package."""
    version = get_authoritative_version()
    out_dir = output_dir or DIST_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    staging_dir = BUILD_DIR / "deb_staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    debian_dir = staging_dir / "DEBIAN"
    usr_bin_dir = staging_dir / "usr" / "bin"
    usr_lib_dir = staging_dir / "usr" / "lib" / "bitchat"
    usr_apps_dir = staging_dir / "usr" / "share" / "applications"
    usr_doc_dir = staging_dir / "usr" / "share" / "doc" / "bitchat"

    for d in (debian_dir, usr_bin_dir, usr_lib_dir, usr_apps_dir, usr_doc_dir):
        d.mkdir(parents=True, exist_ok=True)

    print(f"[*] Copying runtime files from {source_dir} to {usr_lib_dir}...")
    if not source_dir.is_dir():
        raise FileNotFoundError(
            f"PyInstaller source bundle directory not found at {source_dir}"
        )

    # Copy PyInstaller bundle into usr/lib/bitchat/
    for item in source_dir.iterdir():
        dest = usr_lib_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    # Launcher script in /usr/bin/bitchat
    launcher_path = usr_bin_dir / "bitchat"
    launcher_script = """#!/bin/sh
exec /usr/lib/bitchat/bitchat "$@"
"""
    launcher_path.write_text(launcher_script, encoding="utf-8")
    with contextlib.suppress(Exception):
        launcher_path.chmod(0o755)

    # Desktop entry in /usr/share/applications/bitchat.desktop
    desktop_src = DEB_PKG_DIR / "bitchat.desktop"
    if desktop_src.is_file():
        shutil.copy2(desktop_src, usr_apps_dir / "bitchat.desktop")

    # Copyright documentation in /usr/share/doc/bitchat/copyright
    license_src = REPO_ROOT / "LICENSE"
    if license_src.is_file():
        shutil.copy2(license_src, usr_doc_dir / "copyright")

    # Calculate Installed-Size in KiB
    total_bytes = sum(f.stat().st_size for f in staging_dir.rglob("*") if f.is_file())
    installed_size_kb = max(1, total_bytes // 1024)

    # Generate DEBIAN/control
    control_template_file = DEB_PKG_DIR / "control.template"
    if not control_template_file.is_file():
        raise FileNotFoundError(f"Missing control.template at {control_template_file}")

    template_content = control_template_file.read_text(encoding="utf-8")
    control_content = template_content.format(
        version=version,
        installed_size_kb=installed_size_kb,
    )
    (debian_dir / "control").write_text(control_content, encoding="utf-8")

    # Copy postinst and prerm scripts
    postinst_src = DEB_PKG_DIR / "postinst"
    if postinst_src.is_file():
        dest = debian_dir / "postinst"
        shutil.copy2(postinst_src, dest)
        with contextlib.suppress(Exception):
            dest.chmod(0o755)

    prerm_src = DEB_PKG_DIR / "prerm"
    if prerm_src.is_file():
        dest = debian_dir / "prerm"
        shutil.copy2(prerm_src, dest)
        with contextlib.suppress(Exception):
            dest.chmod(0o755)

    deb_filename = f"bitchat_{version}_amd64.deb"
    output_deb = out_dir / deb_filename
    if output_deb.exists():
        output_deb.unlink()

    # Build using dpkg-deb if available, else pure Python
    dpkg_deb = shutil.which("dpkg-deb")
    if dpkg_deb and not force_pure_python:
        print(f"[*] Building {deb_filename} using system dpkg-deb...")
        res = subprocess.run(
            [
                dpkg_deb,
                "--build",
                "--root-owner-group",
                str(staging_dir),
                str(output_deb),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            print(
                f"[!] dpkg-deb failed: {res.stderr}. "
                "Falling back to pure Python builder..."
            )
            create_deb_pure_python(staging_dir, output_deb)
    else:
        print(f"[*] Building {deb_filename} using pure Python ar/tar packaging...")
        create_deb_pure_python(staging_dir, output_deb)

    if not output_deb.is_file():
        raise FileNotFoundError(f"Debian package was not created at {output_deb}")

    sha = calculate_sha256(output_deb)
    sha_file = out_dir / f"{deb_filename}.sha256"
    sha_file.write_text(f"{sha} *{deb_filename}\n", encoding="utf-8")

    print(f"[+] .deb package built successfully: {output_deb} (SHA-256: {sha})")
    return output_deb


def main() -> int:
    parser = argparse.ArgumentParser(description="BitChat Linux .deb Package Builder")
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
        help="Path to output directory for .deb package",
    )
    parser.add_argument(
        "--pure-python",
        action="store_true",
        help="Force pure-Python .deb generation even if dpkg-deb is available",
    )
    args = parser.parse_args()

    deb_path = build_deb_package(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
        force_pure_python=args.pure_python,
    )
    print(f"Build complete: {deb_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
