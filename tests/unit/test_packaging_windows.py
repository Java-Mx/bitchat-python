"""Tests for Windows packaging, assets, startup, signing, and WinGet manifests."""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bitchat.__main__ import main
from bitchat.platform.startup import (
    SingleInstanceGuard,
    disable_startup,
    enable_startup,
    format_startup_status,
    get_startup_dir,
    get_startup_shortcut_path,
    is_startup_enabled,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_SCRIPT_PATH = REPO_ROOT / "packaging" / "windows" / "build.py"
ASSETS_SCRIPT_PATH = REPO_ROOT / "packaging" / "windows" / "assets.py"
DOWNLOAD_SCRIPT_PATH = REPO_ROOT / "packaging" / "windows" / "download_page.py"

_spec = importlib.util.spec_from_file_location("windows_build", BUILD_SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
windows_build = importlib.util.module_from_spec(_spec)
sys.modules["windows_build"] = windows_build
_spec.loader.exec_module(windows_build)

_assets_spec = importlib.util.spec_from_file_location(
    "windows_assets", ASSETS_SCRIPT_PATH
)
assert _assets_spec is not None and _assets_spec.loader is not None
windows_assets = importlib.util.module_from_spec(_assets_spec)
sys.modules["windows_assets"] = windows_assets
_assets_spec.loader.exec_module(windows_assets)

_dl_spec = importlib.util.spec_from_file_location(
    "windows_download_page", DOWNLOAD_SCRIPT_PATH
)
assert _dl_spec is not None and _dl_spec.loader is not None
windows_download_page = importlib.util.module_from_spec(_dl_spec)
sys.modules["windows_download_page"] = windows_download_page
_dl_spec.loader.exec_module(windows_download_page)

calculate_sha256 = windows_build.calculate_sha256
generate_winget_manifests = windows_build.generate_winget_manifests
get_authoritative_version = windows_build.get_authoritative_version
has_signing_credentials = windows_build.has_signing_credentials
is_signing_required = windows_build.is_signing_required
locate_iscc = windows_build.locate_iscc
verify_authenticode_signature = windows_build.verify_authenticode_signature


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


def test_official_windows_assets_and_version_info(tmp_path: Path) -> None:
    """Official branding assets generate valid ICO, BMP, and VSVersionInfo artifacts."""
    version = get_authoritative_version()
    committed_assets_dir = REPO_ROOT / "packaging" / "windows" / "assets"

    # Copy official source PNG/SVGs from committed assets dir to tmp_path/assets
    temp_assets = tmp_path / "assets"
    temp_assets.mkdir(parents=True, exist_ok=True)
    for asset_name in windows_assets.OFFICIAL_ASSET_FILES:
        src = committed_assets_dir / asset_name
        assert src.is_file(), (
            f"Official asset {src} must exist in packaging/windows/assets"
        )
        shutil.copy2(src, temp_assets / asset_name)

    ico_path = temp_assets / "bitchat.ico"
    large_bmp = temp_assets / "wizard-large.bmp"
    small_bmp = temp_assets / "wizard-small.bmp"
    ver_info = tmp_path / "version_info.txt"

    windows_assets.generate_ico(ico_path)
    windows_assets.generate_wizard_large_bmp(large_bmp)
    windows_assets.generate_wizard_small_bmp(small_bmp)
    windows_assets.generate_version_info(version, ver_info)

    assert ico_path.is_file()
    ico_bytes = ico_path.read_bytes()
    reserved, ico_type, count = struct.unpack("<HHH", ico_bytes[:6])
    assert reserved == 0
    assert ico_type == 1
    assert count == 7

    expected_sizes = [16, 24, 32, 48, 64, 128, 256]
    actual_sizes: list[tuple[int, int]] = []
    for idx in range(count):
        off = 6 + idx * 16
        w, h, _, _, planes, bpp, byte_len, data_off = struct.unpack(
            "<BBBBHHII", ico_bytes[off : off + 16]
        )
        real_w = 256 if w == 0 else w
        real_h = 256 if h == 0 else h
        assert planes == 1
        assert bpp == 32
        assert byte_len > 0
        assert data_off + byte_len <= len(ico_bytes)
        actual_sizes.append((real_w, real_h))
    assert actual_sizes == [(s, s) for s in expected_sizes]

    assert large_bmp.is_file()
    large_bytes = large_bmp.read_bytes()
    assert large_bytes[:2] == b"BM"
    width, height = struct.unpack("<ii", large_bytes[18:26])
    assert (width, height) == (164, 314)

    assert small_bmp.is_file()
    small_bytes = small_bmp.read_bytes()
    assert small_bytes[:2] == b"BM"
    s_width, s_height = struct.unpack("<ii", small_bytes[18:26])
    assert (s_width, s_height) == (55, 55)

    assert ver_info.is_file()
    ver_text = ver_info.read_text(encoding="utf-8")
    assert "VSVersionInfo(" in ver_text
    assert "StringStruct('CompanyName', 'Java-Mx')" in ver_text
    assert "StringStruct('ProductName', 'BitChat')" in ver_text
    assert f"StringStruct('ProductVersion', '{version}')" in ver_text


def test_legal_documents_and_inno_setup_script() -> None:
    """Terms of Use, Privacy Policy, and Inno Setup 2.0 script match requirements."""
    terms_md = REPO_ROOT / "TERMS_OF_USE.md"
    privacy_md = REPO_ROOT / "PRIVACY_POLICY.md"
    terms_txt = REPO_ROOT / "packaging" / "windows" / "legal" / "TERMS_OF_USE.txt"
    privacy_txt = REPO_ROOT / "packaging" / "windows" / "legal" / "PRIVACY_POLICY.txt"
    iss_file = REPO_ROOT / "packaging" / "windows" / "bitchat.iss"

    for path in (terms_md, privacy_md, terms_txt, privacy_txt, iss_file):
        assert path.is_file(), f"Required file {path} is missing"

    assert "DRAFT" in terms_md.read_text(encoding="utf-8")
    assert "DRAFT" in privacy_md.read_text(encoding="utf-8")
    assert "identity.json" in privacy_md.read_text(encoding="utf-8")

    iss_content = iss_file.read_text(encoding="utf-8")
    assert "Bitchat-Icon-Framed.svg" in iss_content
    assert 'IconFilename: "{app}\\assets\\bitchat.ico"' in iss_content
    assert "TermsCheckBox" in iss_content
    assert "PrivacyCheckBox" in iss_content
    assert "I have read and agree to the BitChat Terms of Use." in iss_content
    assert "I have read the BitChat Privacy Policy." in iss_content
    assert "ValidateDestinationDir" in iss_content
    assert "StopRunningBitChatInDir" in iss_content
    assert 'Name: "startupicon"' in iss_content
    assert 'Name: "uninstallentry"' in iss_content
    assert "/REMOVEUSERDATA" in iss_content


def test_download_page_generation(tmp_path: Path) -> None:
    """Download HTML and Markdown docs generate with accurate SHA-256 and metadata."""
    version = get_authoritative_version()
    sample_sha = "B" * 64
    installer_filename = f"BitChat-{version}-windows-x64.exe"
    html_path, md_path = windows_download_page.generate_download_experience(
        version=version,
        installer_filename=installer_filename,
        installer_sha256=sample_sha,
        installer_size_bytes=20_500_000,
        release_date="2026-10-30",
        signature_valid=False,
        signer_subject="",
        timestamp_subject="",
        output_html_dir=tmp_path / "docs" / "download",
        output_md_path=tmp_path / "docs" / "DOWNLOAD.md",
    )
    assert html_path.is_file()
    assert md_path.is_file()

    html_content = html_path.read_text(encoding="utf-8")
    assert f"BitChat-{version}-windows-x64.exe" in html_content
    assert sample_sha in html_content
    assert "winget install Java-Mx.BitChat" in html_content
    assert "Get-FileHash" in html_content
    assert "Get-AuthenticodeSignature" in html_content

    md_content = md_path.read_text(encoding="utf-8")
    assert f"BitChat-{version}-windows-x64.exe" in md_content
    assert sample_sha in md_content


def test_signing_helpers_and_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Signing helpers detect credentials and verify Authenticode signature status."""
    monkeypatch.delenv("WINDOWS_SIGNING_CERT", raising=False)
    monkeypatch.delenv("WINDOWS_SIGNING_CERT_PATH", raising=False)
    monkeypatch.delenv("WINDOWS_SIGNING_THUMBPRINT", raising=False)
    monkeypatch.delenv("WINDOWS_SIGNING_REQUIRED", raising=False)

    assert has_signing_credentials() is False
    assert is_signing_required() is False

    monkeypatch.setenv("WINDOWS_SIGNING_REQUIRED", "true")
    assert is_signing_required() is True

    if sys.platform == "win32":
        unsigned_file = tmp_path / "unsigned_sample.exe"
        unsigned_file.write_bytes(b"MZ" + b"\x00" * 128)
        sig_info = verify_authenticode_signature(unsigned_file, require_valid=False)
        assert sig_info.status != "Valid"

        with pytest.raises(RuntimeError, match="Authenticode"):
            verify_authenticode_signature(unsigned_file, require_valid=True)


def test_startup_management_and_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Per-user Windows startup shortcut helpers and CLI commands work cleanly."""
    startup_dir = tmp_path / "Startup"
    monkeypatch.setenv("BITCHAT_STARTUP_DIR", str(startup_dir))

    assert get_startup_dir() == startup_dir
    shortcut_path = get_startup_shortcut_path()
    assert shortcut_path == startup_dir / "BitChat.lnk"
    assert is_startup_enabled() is False
    assert "disabled" in format_startup_status().lower()

    with patch.object(sys, "argv", ["bitchat", "--startup", "status"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "disabled" in captured.out.lower()

    if sys.platform == "win32":
        target_exe = Path(sys.executable).resolve()
        created = enable_startup(executable_path=target_exe)
        assert created.is_file()
        assert is_startup_enabled() is True
        assert "enabled" in format_startup_status().lower()

        removed = disable_startup()
        assert removed is True
        assert is_startup_enabled() is False
        assert disable_startup() is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex test")
def test_single_instance_guard_prevents_duplicates() -> None:
    """SingleInstanceGuard detects an already-running instance via Windows mutex."""
    mutex_name = "Local\\BitChatTestSingleInstanceMutex_Unit"
    with SingleInstanceGuard(mutex_name=mutex_name) as first_guard:
        assert first_guard.already_running is False
        with SingleInstanceGuard(mutex_name=mutex_name) as second_guard:
            assert second_guard.already_running is True


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


def test_committed_manifests_consistency() -> None:
    """Committed WinGet manifests strictly match authoritative project version."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    version = get_authoritative_version()

    manifest_dir = repo_root / "manifests" / "j" / "Java-Mx" / "BitChat" / version
    singleton_file = (
        repo_root / "packaging" / "windows" / "winget" / "Java-Mx.BitChat.yaml"
    )

    assert manifest_dir.is_dir(), f"Committed manifest dir {manifest_dir} must exist"
    assert singleton_file.is_file(), f"Committed singleton {singleton_file} must exist"

    version_file = manifest_dir / "Java-Mx.BitChat.yaml"
    installer_file = manifest_dir / "Java-Mx.BitChat.installer.yaml"
    locale_file = manifest_dir / "Java-Mx.BitChat.locale.en-US.yaml"

    assert version_file.is_file()
    assert installer_file.is_file()
    assert locale_file.is_file()

    v_content = version_file.read_text(encoding="utf-8")
    assert f"PackageVersion: {version}" in v_content
    assert "PackageIdentifier: Java-Mx.BitChat" in v_content

    i_content = installer_file.read_text(encoding="utf-8")
    assert f"PackageVersion: {version}" in i_content
    assert "PackageIdentifier: Java-Mx.BitChat" in i_content
    assert f"BitChat-{version}-windows-x64.exe" in i_content
    assert "InstallerType: inno" in i_content

    l_content = locale_file.read_text(encoding="utf-8")
    assert f"PackageVersion: {version}" in l_content
    assert "PackageIdentifier: Java-Mx.BitChat" in l_content

    s_content = singleton_file.read_text(encoding="utf-8")
    assert f"PackageVersion: {version}" in s_content
    assert "PackageIdentifier: Java-Mx.BitChat" in s_content
    assert f"BitChat-{version}-windows-x64.exe" in s_content
