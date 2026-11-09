"""Automated documentation integrity, link, version, and constant consistency tests."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import bitchat
from bitchat.network.discovery import DEFAULT_DISCOVERY_PORT
from bitchat.network.server import DEFAULT_LAN_PORT
from bitchat.protocol.constants import (
    BITCHAT_CHARACTERISTIC_UUID,
    BITCHAT_SERVICE_UUID,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED_MARKDOWN_FILES: tuple[str, ...] = (
    "README.md",
    "CHANGELOG.md",
    "PRIVACY_POLICY.md",
    "TERMS_OF_USE.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "SUPPORT.md",
    "Screenshot.md",
    "docs/INDEX.md",
    "docs/ARCHITECTURE.md",
    "docs/DEVELOPMENT.md",
    "docs/DOWNLOAD.md",
    "docs/REQUIREMENTS.md",
    "docs/RELEASE_PROCESS.md",
    "docs/ROADMAP.md",
    "docs/UNINSTALLATION.md",
    "docs/platform/WINDOWS.md",
    "docs/platform/LINUX.md",
    "docs/platform/MACOS.md",
    "docs/protocol/OVERVIEW.md",
    "docs/protocol/PACKET_FORMAT.md",
    "docs/protocol/MESSAGE_TYPES.md",
    "docs/protocol/FRAGMENTATION.md",
    "docs/protocol/ROUTING.md",
    "docs/protocol/COMPATIBILITY.md",
    "docs/security/CRYPTOGRAPHY.md",
    "docs/security/NOISE.md",
    "docs/security/THREAT_MODEL.md",
    "docs/security/DATA_HANDLING.md",
    "packaging/linux/flatpak/README.md",
    "packaging/linux/snap/README.md",
    "nim/README.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
    ".github/ISSUE_TEMPLATE/interoperability_issue.md",
    ".github/ISSUE_TEMPLATE/protocol_issue.md",
    ".github/pull_request_template.md",
)

FENCED_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _strip_code_blocks(markdown_text: str) -> str:
    """Remove fenced code blocks before scanning for Markdown links."""
    return FENCED_CODE_BLOCK_RE.sub("", markdown_text)


def test_required_official_documentation_files_exist() -> None:
    """All official root, docs/, legal, and GitHub template files must exist."""
    for rel_path in REQUIRED_MARKDOWN_FILES:
        full_path = REPO_ROOT / rel_path
        assert full_path.is_file(), f"Missing required documentation file: {rel_path}"

    assert (REPO_ROOT / "LICENSE").is_file()
    assert (REPO_ROOT / "packaging/windows/legal/PRIVACY_POLICY.txt").is_file()
    assert (REPO_ROOT / "packaging/windows/legal/TERMS_OF_USE.txt").is_file()


def test_all_markdown_relative_links_resolve() -> None:
    """Every internal relative link in every Markdown file must resolve on disk."""
    broken_links: list[str] = []
    file_scheme_links: list[str] = []

    for rel_path in REQUIRED_MARKDOWN_FILES:
        md_file = REPO_ROOT / rel_path
        text = _strip_code_blocks(md_file.read_text(encoding="utf-8"))
        for match in MARKDOWN_LINK_RE.finditer(text):
            raw_target = match.group(1).strip()
            if not raw_target or raw_target.startswith("#"):
                continue
            # Strip optional title attribute: (path "title")
            target = raw_target.split()[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("file://"):
                file_scheme_links.append(f"{rel_path} -> {target}")
                continue

            path_part = target.split("#", 1)[0]
            if not path_part:
                continue

            resolved = (md_file.parent / path_part).resolve()
            if not resolved.exists():
                broken_links.append(f"{rel_path} -> {target} (expected at {resolved})")

    assert not file_scheme_links, (
        f"Hardcoded file:// links found in repository docs: {file_scheme_links}"
    )
    assert not broken_links, f"Broken relative Markdown links found: {broken_links}"


def test_no_placeholder_text_or_obsolete_claims() -> None:
    """Documentation must not contain unfilled placeholders or obsolete claims."""
    coc_text = (REPO_ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
    assert "[INSERT CONTACT METHOD]" not in coc_text

    contrib_text = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "your-username" not in contrib_text

    readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "does not use Rust code or the Rust runtime" not in readme_text
    assert "_bitchat_core" in readme_text

    for doc_rel in (
        "docs/security/CRYPTOGRAPHY.md",
        "docs/security/NOISE.md",
        "docs/protocol/OVERVIEW.md",
    ):
        content = (REPO_ROOT / doc_rel).read_text(encoding="utf-8")
        assert "state.json" not in content, (
            f"Obsolete state.json reference found in {doc_rel}"
        )


def test_legal_and_security_policy_invariants() -> None:
    """Privacy Policy, Terms of Use, and Security Policy meet legal/audit invariants."""
    privacy_md = (REPO_ROOT / "PRIVACY_POLICY.md").read_text(encoding="utf-8")
    privacy_txt = (REPO_ROOT / "packaging/windows/legal/PRIVACY_POLICY.txt").read_text(
        encoding="utf-8"
    )
    terms_md = (REPO_ROOT / "TERMS_OF_USE.md").read_text(encoding="utf-8")
    terms_txt = (REPO_ROOT / "packaging/windows/legal/TERMS_OF_USE.txt").read_text(
        encoding="utf-8"
    )
    security_md = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")

    # Visible DRAFT notice required
    assert "DRAFT" in privacy_md
    assert "DRAFT" in privacy_txt
    assert "DRAFT" in terms_md
    assert "DRAFT" in terms_txt

    # Terms of Use must defer to MIT License
    assert "MIT License" in terms_md
    assert "does not restrict" in terms_md

    # Obsolete Nordic UART UUID must never appear in Privacy Policy
    assert "6E400001-B5A3-F393-E0A9-E50E24DCCA9E" not in privacy_md
    assert "6E400001-B5A3-F393-E0A9-E50E24DCCA9E" not in privacy_txt

    # Security policy requirements
    assert (
        "https://github.com/Java-Mx/bitchat-python/security/advisories/new"
        in security_md
    )
    assert "independent third-party" in security_md
    assert "48 hours" not in security_md
    assert "5 business days" not in security_md


def test_version_and_protocol_constants_match_source_code() -> None:
    """Documented version numbers, BLE UUIDs, and LAN ports match code constants."""
    version = bitchat.__version__

    pyproject_data = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject_data["project"]["version"] == version

    cargo_toml = (REPO_ROOT / "Cargo.toml").read_text(encoding="utf-8")
    assert f'version = "{version}"' in cargo_toml

    # Verify Windows guide and download page match current version
    windows_md = (REPO_ROOT / "docs/platform/WINDOWS.md").read_text(encoding="utf-8")
    assert f"BitChat-{version}-windows-x64.exe" in windows_md
    assert "BitChat-0.2.0-windows-x64.exe" not in windows_md

    download_md = (REPO_ROOT / "docs/DOWNLOAD.md").read_text(encoding="utf-8")
    assert f"BitChat-{version}-windows-x64.exe" in download_md

    # Verify BLE UUIDs and LAN ports in Privacy Policy and Data Handling
    for doc_rel in ("PRIVACY_POLICY.md", "docs/security/DATA_HANDLING.md"):
        text = (REPO_ROOT / doc_rel).read_text(encoding="utf-8")
        assert BITCHAT_SERVICE_UUID in text
        assert BITCHAT_CHARACTERISTIC_UUID in text
        assert str(DEFAULT_DISCOVERY_PORT) in text
        assert str(DEFAULT_LAN_PORT) in text

    # Verify issue templates include private security reporting notice
    for tmpl_rel in (
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/ISSUE_TEMPLATE/interoperability_issue.md",
        ".github/ISSUE_TEMPLATE/protocol_issue.md",
    ):
        tmpl_text = (REPO_ROOT / tmpl_rel).read_text(encoding="utf-8")
        assert "security/advisories/new" in tmpl_text
