"""Automated validation suite for the BitChat official website."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WEBSITE_DIR = REPO_ROOT / "website"


class SimpleHTMLValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.images: list[str] = []
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "a" and "href" in attr_dict:
            href = attr_dict["href"]
            if href:
                self.links.append(href)
        elif tag == "img" and "src" in attr_dict:
            src = attr_dict["src"]
            if src:
                self.images.append(src)
        elif tag == "script" and "src" in attr_dict:
            src = attr_dict["src"]
            if src:
                self.scripts.append(src)
        elif (
            tag == "link"
            and attr_dict.get("rel") == "stylesheet"
            and "href" in attr_dict
        ):
            href = attr_dict["href"]
            if href:
                self.stylesheets.append(href)


REQUIRED_PAGES = [
    "index.html",
    "downloads.html",
    "docs.html",
    "security.html",
    "privacy.html",
    "terms.html",
    "about.html",
    "roadmap.html",
    "404.html",
]

REQUIRED_ASSETS = [
    "robots.txt",
    "sitemap.xml",
    "assets/css/style.css",
    "assets/js/main.js",
    "assets/js/downloads.js",
    "assets/data/releases.json",
    "assets/img/brand/bitchat-icon-32.svg",
    "assets/img/brand/Bitchat-Icon-Framed.svg",
    "assets/img/brand/bitchat.ico",
    "assets/img/diagrams/architecture.svg",
    "assets/img/diagrams/noise-flow.svg",
    "assets/img/screenshots/06_lan_active_chat.svg",
    "assets/img/screenshots/04_peers_screen.svg",
    "assets/img/screenshots/22_telemetry_screen.svg",
    "assets/img/screenshots/01_home_screen.svg",
    "assets/img/screenshots/21_commands_help.svg",
]


def test_required_website_files_exist():
    """Verify that all core website HTML pages and static assets exist."""
    assert WEBSITE_DIR.is_dir(), f"Website directory missing at {WEBSITE_DIR}"

    for page in REQUIRED_PAGES:
        page_path = WEBSITE_DIR / page
        assert page_path.is_file(), f"Required HTML page missing: {page}"
        content = page_path.read_text(encoding="utf-8")
        assert len(content) > 200, f"Page {page} content is suspiciously short"

    for asset in REQUIRED_ASSETS:
        asset_path = WEBSITE_DIR / asset
        assert asset_path.is_file(), f"Required asset missing: {asset}"


def test_html_parsing_and_internal_references():
    """Parse every HTML file and verify all local references resolve to files on disk."""
    for page in REQUIRED_PAGES:
        page_path = WEBSITE_DIR / page
        content = page_path.read_text(encoding="utf-8")

        validator = SimpleHTMLValidator()
        validator.feed(content)

        # Check stylesheets
        for css in validator.stylesheets:
            if not css.startswith(("http://", "https://", "//")):
                css_file = (WEBSITE_DIR / css.split("?")[0]).resolve()
                assert css_file.is_file(), (
                    f"In {page}: CSS reference '{css}' does not exist on disk"
                )

        # Check scripts
        for js in validator.scripts:
            if not js.startswith(("http://", "https://", "//")):
                js_file = (WEBSITE_DIR / js.split("?")[0]).resolve()
                assert js_file.is_file(), (
                    f"In {page}: JS reference '{js}' does not exist on disk"
                )

        # Check images
        for img in validator.images:
            if not img.startswith(("http://", "https://", "data:", "//")):
                img_file = (WEBSITE_DIR / img.split("?")[0]).resolve()
                assert img_file.is_file(), (
                    f"In {page}: Image reference '{img}' does not exist on disk"
                )

        # Check internal links
        for link in validator.links:
            parsed = urlparse(link)
            if not parsed.scheme and not link.startswith(("#", "mailto:", "tel:")):
                path_part = parsed.path
                if path_part:
                    target_file = (WEBSITE_DIR / path_part).resolve()
                    assert target_file.is_file() or target_file.is_dir(), (
                        f"In {page}: Broken internal link '{link}' (target {target_file} not found)"
                    )


def test_releases_json_schema_and_checksum_consistency():
    """Verify that releases.json contains accurate v0.3.1 data and SHA-256 hashes."""
    data_path = WEBSITE_DIR / "assets" / "data" / "releases.json"
    assert data_path.is_file()

    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data["version"] == "0.3.1"
    assert data["release_tag"] == "v0.3.1"
    assert len(data["packages"]) >= 7

    # Ensure windows installer checksum matches the official hash
    win_pkg = next(p for p in data["packages"] if p["id"] == "win-exe")
    assert win_pkg["filename"] == "BitChat-0.3.1-windows-x64.exe"
    assert (
        win_pkg["sha256"]
        == "2A2D68F5B7B975620AF7197030A6DD068C8A0D096AEEECFC69F5DBB3FA84A75A"
    )
    assert win_pkg["size_bytes"] == 18165765


def test_sitemap_xml_validity():
    """Verify sitemap.xml is valid XML and contains all primary pages."""
    sitemap_path = WEBSITE_DIR / "sitemap.xml"
    assert sitemap_path.is_file()

    tree = ET.parse(sitemap_path)
    root = tree.getroot()

    urls: list[str] = [
        elem.text
        for elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        if elem.text is not None
    ]
    assert len(urls) >= 7

    expected_pages = [
        "downloads.html",
        "docs.html",
        "security.html",
        "roadmap.html",
        "about.html",
        "privacy.html",
        "terms.html",
    ]
    for expected in expected_pages:
        assert any(expected in u for u in urls), (
            f"Page {expected} missing in sitemap.xml"
        )


def test_no_placeholders_in_html():
    """Ensure no developer placeholders, fake numbers, or lorem ipsum remain in any page."""
    forbidden = ["LOREM IPSUM", "TODO:", "PLACEHOLDER_TEXT", "FIXME", "[INSERT "]

    for page in REQUIRED_PAGES:
        content = (WEBSITE_DIR / page).read_text(encoding="utf-8").upper()
        for phrase in forbidden:
            assert phrase not in content, (
                f"Found forbidden placeholder '{phrase}' in {page}"
            )
