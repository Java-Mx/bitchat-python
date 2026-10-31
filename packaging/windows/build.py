#!/usr/bin/env python3
"""BitChat Windows Distributable, Code Signing & WinGet Packaging Builder.

Automates the complete Windows packaging workflow:
1. Version verification (pyproject.toml vs src/bitchat/__init__.py)
2. Official BitChat branding asset & Windows version resource preparation
3. PyInstaller freeze of BitChat into a self-contained runtime directory
4. Executable verification (--version, --help, --configure, --startup status)
5. Optional Authenticode signing of application binary (bitchat.exe)
6. Inno Setup 6 installer compilation (BitChat-<version>-windows-x64.exe)
7. Optional Authenticode signing & verification of installer binary
8. SHA-256 hash generation & download page metadata update
9. WinGet manifest generation (multi-file and singleton) & schema validation
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"
PACKAGING_DIR = REPO_ROOT / "packaging" / "windows"
MANIFESTS_ROOT = REPO_ROOT / "manifests"
DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"


@dataclass(frozen=True)
class SignatureReport:
    """Structured result of Windows Authenticode signature verification."""

    file_path: str
    status: str
    status_message: str
    subject: str
    issuer: str
    thumbprint: str
    timestamp_subject: str
    is_valid: bool
    is_timestamped: bool
    sha256: str


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


def locate_iscc() -> Path | None:
    """Find Inno Setup Compiler (ISCC.exe) across common Windows locations."""
    iscc_path = shutil.which("iscc") or shutil.which("ISCC.exe")
    if iscc_path:
        return Path(iscc_path)

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


def locate_signtool() -> Path | None:
    """Find Windows SDK signtool.exe across PATH and Windows Kits directories."""
    st = shutil.which("signtool") or shutil.which("signtool.exe")
    if st:
        return Path(st)

    kits_root = (
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
        / "Windows Kits"
        / "10"
        / "bin"
    )
    if kits_root.is_dir():
        matches = sorted(kits_root.glob("**/x64/signtool.exe"), reverse=True)
        for match in matches:
            if match.is_file():
                return match
    return None


def has_signing_credentials() -> bool:
    """Return True if Authenticode signing credentials are configured in env."""
    return bool(
        os.environ.get("WINDOWS_SIGNING_CERT", "").strip()
        or os.environ.get("WINDOWS_SIGNING_CERT_PATH", "").strip()
        or os.environ.get("WINDOWS_SIGNING_THUMBPRINT", "").strip()
    )


def is_signing_required(cli_flag: bool = False) -> bool:
    """Return True if a valid Authenticode signature is mandatory for this build."""
    if cli_flag:
        return True
    env_val = os.environ.get("WINDOWS_SIGNING_REQUIRED", "").strip().lower()
    return env_val in ("1", "true", "yes", "on")


def calculate_sha256(file_path: Path) -> str:
    """Compute uppercase SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest().upper()


def sign_binary(
    target_path: Path,
    timestamp_url: str | None = None,
    signtool_path: Path | None = None,
) -> None:
    """Sign a Windows executable using signtool.exe with SHA-256 and RFC3161."""
    if not target_path.is_file():
        raise FileNotFoundError(f"Cannot sign missing binary: {target_path}")

    st_exe = signtool_path or locate_signtool()
    if not st_exe:
        raise FileNotFoundError(
            "signtool.exe not found on PATH or in Windows Kits. "
            "Install Windows 10/11 SDK to perform Authenticode code signing."
        )

    ts_url = (
        timestamp_url
        or os.environ.get("WINDOWS_TIMESTAMP_URL", "").strip()
        or DEFAULT_TIMESTAMP_URL
    )
    cert_b64 = os.environ.get("WINDOWS_SIGNING_CERT", "").strip()
    cert_path_env = os.environ.get("WINDOWS_SIGNING_CERT_PATH", "").strip()
    cert_pass = os.environ.get("WINDOWS_SIGNING_PASSWORD", "")
    cert_thumbprint = os.environ.get("WINDOWS_SIGNING_THUMBPRINT", "").strip()

    temp_pfx: Path | None = None
    try:
        cmd: list[str] = [
            str(st_exe),
            "sign",
            "/fd",
            "sha256",
            "/td",
            "sha256",
            "/tr",
            ts_url,
            "/d",
            "BitChat",
            "/du",
            "https://github.com/Java-Mx/bitchat-python",
        ]

        if cert_b64:
            pfx_bytes = base64.b64decode(cert_b64)
            fd, temp_name = tempfile.mkstemp(prefix="bitchat_sign_", suffix=".pfx")
            os.close(fd)
            temp_pfx = Path(temp_name)
            temp_pfx.write_bytes(pfx_bytes)
            cmd.extend(["/f", str(temp_pfx)])
            if cert_pass:
                cmd.extend(["/p", cert_pass])
        elif cert_path_env:
            pfx_file = Path(cert_path_env)
            if not pfx_file.is_file():
                raise FileNotFoundError(
                    f"Signing certificate file not found: {pfx_file}"
                )
            cmd.extend(["/f", str(pfx_file)])
            if cert_pass:
                cmd.extend(["/p", cert_pass])
        elif cert_thumbprint:
            cmd.extend(["/sha1", cert_thumbprint])
        else:
            raise RuntimeError(
                "No signing credentials configured (set WINDOWS_SIGNING_CERT, "
                "WINDOWS_SIGNING_CERT_PATH, or WINDOWS_SIGNING_THUMBPRINT)."
            )

        cmd.append(str(target_path))
        print(
            f"[*] Signing binary with Authenticode + timestamp ({ts_url}): "
            f"{target_path.name}"
        )
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if res.returncode != 0:
            err_msg = res.stderr.strip() or res.stdout.strip()
            raise RuntimeError(
                f"Authenticode signing failed for {target_path.name} "
                f"(exit {res.returncode}): {err_msg}"
            )
        print(f"[+] Successfully signed {target_path.name}")
    finally:
        if temp_pfx is not None and temp_pfx.exists():
            with contextlib.suppress(Exception):
                temp_pfx.write_bytes(b"\x00" * 64)
                temp_pfx.unlink()


def verify_authenticode_signature(
    target_path: Path,
    expected_publisher: str | None = None,
    require_valid: bool = False,
) -> SignatureReport:
    """Verify Authenticode signature, publisher, and timestamp via PowerShell."""
    if not target_path.is_file():
        raise FileNotFoundError(f"File to verify does not exist: {target_path}")

    sha256_hash = calculate_sha256(target_path)

    if sys.platform != "win32":
        report = SignatureReport(
            file_path=str(target_path),
            status="UnsupportedPlatform",
            status_message="Get-AuthenticodeSignature requires Windows",
            subject="",
            issuer="",
            thumbprint="",
            timestamp_subject="",
            is_valid=False,
            is_timestamped=False,
            sha256=sha256_hash,
        )
        if require_valid:
            raise RuntimeError("Authenticode verification requires Windows.")
        return report

    pwsh = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
    ps_cmd = (
        "$sig = Get-AuthenticodeSignature -LiteralPath $env:BITCHAT_VERIFY_TARGET; "
        "$sc = $sig.SignerCertificate; "
        "$tc = $sig.TimeStamperCertificate; "
        "$obj = [ordered]@{ "
        "  status = [string]$sig.Status; "
        "  status_message = [string]$sig.StatusMessage; "
        "  subject = if ($sc) { [string]$sc.Subject } else { '' }; "
        "  issuer = if ($sc) { [string]$sc.Issuer } else { '' }; "
        "  thumbprint = if ($sc) { [string]$sc.Thumbprint } else { '' }; "
        "  timestamp_subject = if ($tc) { [string]$tc.Subject } else { '' } "
        "}; "
        "$obj | ConvertTo-Json -Compress"
    )
    env = os.environ.copy()
    env["BITCHAT_VERIFY_TARGET"] = str(target_path.resolve())

    res = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"Get-AuthenticodeSignature failed (exit {res.returncode}): {res.stderr}"
        )

    data = json.loads(res.stdout.strip())
    status = str(data.get("status", "Unknown"))
    status_message = str(data.get("status_message", ""))
    subject = str(data.get("subject", ""))
    issuer = str(data.get("issuer", ""))
    thumbprint = str(data.get("thumbprint", ""))
    timestamp_subject = str(data.get("timestamp_subject", ""))

    is_valid = status == "Valid"
    is_timestamped = bool(timestamp_subject)

    report = SignatureReport(
        file_path=str(target_path),
        status=status,
        status_message=status_message,
        subject=subject,
        issuer=issuer,
        thumbprint=thumbprint,
        timestamp_subject=timestamp_subject,
        is_valid=is_valid,
        is_timestamped=is_timestamped,
        sha256=sha256_hash,
    )

    pub_expected = (
        expected_publisher
        or os.environ.get("WINDOWS_SIGNING_PUBLISHER", "").strip()
        or None
    )

    if require_valid:
        if not report.is_valid:
            raise RuntimeError(
                f"Authenticode signature verification FAILED for {target_path.name}: "
                f"Status='{report.status}' ({report.status_message})"
            )
        if not report.is_timestamped:
            raise RuntimeError(
                f"Authenticode signature on {target_path.name} is missing a "
                "counter-signature timestamp (TimeStamperCertificate is null)."
            )
        if pub_expected and pub_expected.lower() not in report.subject.lower():
            raise RuntimeError(
                f"Publisher identity mismatch on {target_path.name}: "
                f"expected '{pub_expected}' in Subject '{report.subject}'"
            )

    return report


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
    """Verify compiled binary executes --version, --help, and --startup status."""
    print(f"[*] Verifying compiled executable: {exe_path}")

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

    res_startup = subprocess.run(
        [str(exe_path), "--startup", "status"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if res_startup.returncode != 0:
        raise RuntimeError(
            f"Executable failed --startup status (exit {res_startup.returncode}): "
            f"{res_startup.stderr}"
        )
    if "BitChat Windows Startup Status" not in res_startup.stdout:
        raise ValueError(f"Unexpected --startup status output: {res_startup.stdout}")
    print("[+] Executable --startup status verified.")


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


def generate_winget_manifests(
    version: str, installer_sha256: str, release_date: str | None = None
) -> tuple[Path, Path]:
    """Generate official multi-file manifests and repository singleton manifest."""
    installer_filename = f"BitChat-{version}-windows-x64.exe"
    base_release_url = "https://github.com/Java-Mx/bitchat-python/releases/download"
    installer_url = f"{base_release_url}/v{version}/{installer_filename}"
    rel_date = release_date or datetime.date.today().isoformat()

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
ReleaseDate: {rel_date}
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

    short_description = (
        "Python terminal client for the BitChat protocol over Bluetooth Low Energy"
    )
    description = (
        "BitChat is a secure peer-to-peer terminal chat client operating over "
        "Bluetooth Low Energy (BLE).\n"
        "  It features decentralized mesh networking, end-to-end encryption with "
        "Noise Protocol / X25519 / AES-GCM,\n"
        "  and an interactive terminal user interface built with Textual."
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
ShortDescription: {short_description}
Description: |-
  {description}
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
ShortDescription: {short_description}
Description: |-
  {description}
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
    parser.add_argument(
        "--sign",
        action="store_true",
        help="Sign binaries with Authenticode (requires signing credentials)",
    )
    parser.add_argument(
        "--require-signature",
        action="store_true",
        help="Fail build if Authenticode signature is missing or invalid",
    )
    args = parser.parse_args()

    version = get_authoritative_version()
    print(f"=== Building BitChat v{version} Windows Distributable ===")

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 0. Ensure official BitChat assets and Windows version resource exist
    if str(PACKAGING_DIR) not in sys.path:
        sys.path.insert(0, str(PACKAGING_DIR))
    import assets as win_assets
    import download_page as win_download

    win_assets.ensure_windows_assets(version)

    must_sign = is_signing_required(args.require_signature) or args.sign
    creds_available = has_signing_credentials()

    if must_sign and not creds_available:
        raise RuntimeError(
            "Authenticode signing is required (--require-signature / "
            "WINDOWS_SIGNING_REQUIRED=true), but no signing credentials were "
            "provided in WINDOWS_SIGNING_CERT, WINDOWS_SIGNING_CERT_PATH, or "
            "WINDOWS_SIGNING_THUMBPRINT."
        )

    # 1. PyInstaller
    exe_path = DIST_DIR / "bitchat" / "bitchat.exe"
    if not args.skip_pyinstaller:
        spec_file = PACKAGING_DIR / "bitchat.spec"
        exe_path = build_pyinstaller(spec_file)
        verify_executable(exe_path, version)
    else:
        if exe_path.is_file():
            verify_executable(exe_path, version)
        else:
            print(f"[!] Warning: {exe_path} not found.")

    # 1b. Sign application executable before bundling into installer
    if exe_path.is_file() and creds_available and not args.skip_installer:
        sign_binary(exe_path)
        verify_authenticode_signature(exe_path, require_valid=True)

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

    # 3. Sign & Verify Installer + Checksum + WinGet + Download Page
    if installer_path.is_file():
        if creds_available:
            sign_binary(installer_path)
            sig_report = verify_authenticode_signature(
                installer_path, require_valid=True
            )
            print(
                f"[+] Verified Authenticode Signature on {installer_path.name}:\n"
                f"    Status:    {sig_report.status}\n"
                f"    Publisher: {sig_report.subject}\n"
                f"    Timestamp: {sig_report.timestamp_subject}"
            )
        else:
            sig_report = verify_authenticode_signature(
                installer_path, require_valid=must_sign
            )
            print(
                f"[!] Authenticode Signing Status: {sig_report.status} "
                "(No signing certificate configured; installer cannot yet be "
                "presented as a Verified Publisher)."
            )

        sha256_hash = calculate_sha256(installer_path)
        sha256_file = DIST_DIR / f"{installer_path.name}.sha256"
        sha256_file.write_text(
            f"{sha256_hash} *{installer_path.name}\n", encoding="utf-8"
        )
        print(f"[+] Installer SHA-256: {sha256_hash}")
        print(f"[+] Checksum file written: {sha256_file}")

        metadata_file = DIST_DIR / f"{installer_path.stem}.metadata.json"
        release_date = datetime.date.today().isoformat()
        metadata_payload = {
            "version": version,
            "installer_filename": installer_path.name,
            "installer_size_bytes": installer_path.stat().st_size,
            "installer_sha256": sha256_hash,
            "release_date": release_date,
            "signature": asdict(sig_report),
        }
        metadata_file.write_text(
            json.dumps(metadata_payload, indent=2) + "\n", encoding="utf-8"
        )

        # 4. WinGet manifests & Download page
        if not args.skip_winget:
            multi_dir, single_file = generate_winget_manifests(
                version, sha256_hash, release_date=release_date
            )
            validate_winget_manifests(multi_dir, single_file)
            html_page, md_page = win_download.generate_download_experience(
                version=version,
                installer_filename=installer_path.name,
                installer_sha256=sha256_hash,
                installer_size_bytes=installer_path.stat().st_size,
                release_date=release_date,
                signature_valid=sig_report.is_valid,
                signer_subject=sig_report.subject,
                timestamp_subject=sig_report.timestamp_subject,
            )
            print(f"[+] Download experience updated: {html_page} & {md_page}")
    else:
        print(f"[!] Installer {installer_path} missing. Skipping SHA/WinGet.")

    print(f"=== Build finished successfully for BitChat v{version} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
