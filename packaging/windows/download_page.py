# ruff: noqa: E501
"""Generator for the official BitChat Windows Download Page and Distribution Guide.

Uses official BitChat branding assets (`bitchat-wordmark-dark.png`, `bitchat-symbol-dark.png`,
`bitchat-icon-32.svg`, `bitchat-icon-48.svg`) and truthful build/signature metadata.
"""

from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ASSETS_SRC_DIR = Path(__file__).resolve().parent / "assets"
DOWNLOAD_PAGE_DIR = REPO_ROOT / "docs" / "download"
DOWNLOAD_MD_PATH = REPO_ROOT / "docs" / "DOWNLOAD.md"


def format_file_size(size_bytes: int) -> str:
    """Format byte size into human-readable MB and exact byte count."""
    mb = size_bytes / (1024 * 1024)
    return f"{mb:.2f} MB ({size_bytes:,} bytes)"


def generate_download_experience(
    version: str,
    installer_filename: str,
    installer_sha256: str,
    installer_size_bytes: int,
    release_date: str,
    signature_valid: bool = False,
    signer_subject: str = "",
    timestamp_subject: str = "",
    output_html_dir: Path | None = None,
    output_md_path: Path | None = None,
) -> tuple[Path, Path]:
    """Generate `docs/download/index.html` and `docs/DOWNLOAD.md`."""
    html_dir = output_html_dir or DOWNLOAD_PAGE_DIR
    md_path = output_md_path or DOWNLOAD_MD_PATH
    html_assets_dir = html_dir / "assets"
    html_assets_dir.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    # Copy official BitChat branding assets for the download page
    for asset_name in (
        "Bitchat-Icon-Framed.svg",
        "bitchat.ico",
        "bitchat-icon-16.png",
        "bitchat-icon-32.svg",
        "bitchat-icon-48.svg",
        "bitchat-symbol-dark.png",
        "bitchat-symbol-light.png",
        "bitchat-wordmark-dark.png",
        "bitchat-wordmark-light.png",
    ):
        src = ASSETS_SRC_DIR / asset_name
        if src.is_file():
            shutil.copy2(src, html_assets_dir / asset_name)

    size_display = format_file_size(installer_size_bytes)
    release_url = (
        f"https://github.com/Java-Mx/bitchat-python/releases/download/"
        f"v{version}/{installer_filename}"
    )
    releases_page_url = "https://github.com/Java-Mx/bitchat-python/releases"
    terms_url = "https://github.com/Java-Mx/bitchat-python/blob/main/TERMS_OF_USE.md"
    privacy_url = (
        "https://github.com/Java-Mx/bitchat-python/blob/main/PRIVACY_POLICY.md"
    )
    security_url = "https://github.com/Java-Mx/bitchat-python/blob/main/SECURITY.md"
    changelog_url = "https://github.com/Java-Mx/bitchat-python/blob/main/CHANGELOG.md"

    if signature_valid:
        sig_badge_html = (
            '<span class="badge badge-verified">Authenticode Verified</span>'
        )
        sig_status_text = (
            f"Valid Authenticode Signature (Publisher: {signer_subject or 'Java-Mx'}, "
            f"Timestamp: {timestamp_subject or 'Present'})"
        )
    else:
        sig_badge_html = (
            '<span class="badge badge-unsigned">'
            "Unsigned Open-Source Build (Verify via SHA-256)"
            "</span>"
        )
        sig_status_text = (
            "NotSigned — No commercial code-signing certificate configured yet. "
            "Do not treat as a Microsoft-verified publisher until a real certificate "
            "signature is verified. Always verify the SHA-256 checksum below."
        )

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Download BitChat {version} for Windows (x64) — Java-Mx</title>
  <link rel="icon" type="image/svg+xml" href="assets/Bitchat-Icon-Framed.svg" />
  <link rel="alternate icon" type="image/x-icon" href="assets/bitchat.ico" />
  <style>
    :root {{
      --bg-primary: #071826;
      --bg-panel: #0c2235;
      --bg-card: #102a42;
      --border: #1e4263;
      --accent: #22d3ee;
      --accent-hover: #67e8f9;
      --text-main: #f0f6fc;
      --text-muted: #94a3b8;
      --warn-bg: #2c2212;
      --warn-border: #d97706;
      --ok-bg: #0f2922;
      --ok-border: #10b981;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background-color: var(--bg-primary);
      color: var(--text-main);
      line-height: 1.6;
    }}
    .container {{
      max-width: 980px;
      margin: 0 auto;
      padding: 2rem 1.5rem 4rem;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 1rem;
      padding-bottom: 1.5rem;
      border-bottom: 1px solid var(--border);
    }}
    .brand-wordmark {{
      height: 46px;
      width: auto;
      display: block;
    }}
    .nav-links a {{
      color: var(--text-muted);
      text-decoration: none;
      margin-left: 1.25rem;
      font-size: 0.95rem;
    }}
    .nav-links a:hover {{
      color: var(--accent);
    }}
    .hero {{
      margin-top: 2rem;
      background: var(--bg-panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 2rem;
    }}
    .hero-top {{
      display: flex;
      align-items: center;
      gap: 1.5rem;
      flex-wrap: wrap;
    }}
    .hero-symbol {{
      width: 64px;
      height: auto;
    }}
    h1 {{
      margin: 0 0 0.35rem 0;
      font-size: 1.85rem;
    }}
    .subtitle {{
      margin: 0;
      color: var(--text-muted);
      font-size: 1.05rem;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 1rem;
      margin: 1.5rem 0;
    }}
    .meta-item {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.85rem 1rem;
    }}
    .meta-label {{
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
    }}
    .meta-value {{
      font-weight: 600;
      margin-top: 0.2rem;
      word-break: break-word;
    }}
    .checksum-box {{
      background: #040f19;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.9rem 1rem;
      font-family: Consolas, "Courier New", monospace;
      font-size: 0.88rem;
      overflow-x: auto;
      margin-bottom: 1.25rem;
    }}
    .legal-consent {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.15rem;
      margin-bottom: 1.25rem;
    }}
    .legal-consent label {{
      display: flex;
      align-items: flex-start;
      gap: 0.65rem;
      margin-bottom: 0.6rem;
      cursor: pointer;
    }}
    .legal-note {{
      font-size: 0.85rem;
      color: var(--text-muted);
      margin: 0.5rem 0 0 0;
    }}
    .btn-primary {{
      display: inline-block;
      background: var(--accent);
      color: #041019;
      font-weight: 700;
      text-decoration: none;
      padding: 0.85rem 1.6rem;
      border-radius: 8px;
      border: none;
      font-size: 1rem;
      cursor: pointer;
    }}
    .btn-primary:hover {{
      background: var(--accent-hover);
    }}
    .btn-primary.disabled {{
      opacity: 0.45;
      pointer-events: none;
    }}
    .badge {{
      display: inline-block;
      padding: 0.2rem 0.6rem;
      border-radius: 6px;
      font-size: 0.82rem;
      font-weight: 600;
    }}
    .badge-unsigned {{
      background: var(--warn-bg);
      border: 1px solid var(--warn-border);
      color: #fbbf24;
    }}
    .badge-verified {{
      background: var(--ok-bg);
      border: 1px solid var(--ok-border);
      color: #34d399;
    }}
    section {{
      margin-top: 2.25rem;
      background: var(--bg-panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem 1.75rem;
    }}
    h2 {{
      margin-top: 0;
      font-size: 1.3rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.5rem;
    }}
    pre {{
      background: #040f19;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.9rem 1rem;
      overflow-x: auto;
      font-family: Consolas, "Courier New", monospace;
      font-size: 0.88rem;
    }}
    a {{ color: var(--accent); }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <img src="assets/bitchat-wordmark-dark.png" alt="BitChat" class="brand-wordmark" />
      <nav class="nav-links">
        <a href="https://github.com/Java-Mx/bitchat-python">GitHub Repository</a>
        <a href="{releases_page_url}">All Releases</a>
        <a href="{terms_url}">Terms of Use</a>
        <a href="{privacy_url}">Privacy Policy</a>
        <a href="{security_url}">Security</a>
      </nav>
    </header>

    <div class="hero">
      <div class="hero-top">
        <img src="assets/bitchat-symbol-dark.png" alt="BitChat Symbol" class="hero-symbol" />
        <div>
          <h1>Download BitChat for Windows (x64)</h1>
          <p class="subtitle">
            Private peer-to-peer encrypted terminal messaging over Bluetooth Low Energy (BLE) and LAN.
            No servers, no accounts, and no manual Python installation required.
          </p>
        </div>
      </div>

      <div class="meta-grid">
        <div class="meta-item">
          <div class="meta-label">Version</div>
          <div class="meta-value">{version}</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">Publisher</div>
          <div class="meta-value">Java-Mx</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">Architecture &amp; OS</div>
          <div class="meta-value">Windows 10 (1809+) / Windows 11 (x64)</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">Installer Size</div>
          <div class="meta-value">{size_display}</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">Release Date</div>
          <div class="meta-value">{release_date}</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">Digital Signature Status</div>
          <div class="meta-value">{sig_badge_html}</div>
        </div>
      </div>

      <div class="checksum-box">
        <strong>Official Installer Filename:</strong> {installer_filename}<br />
        <strong>SHA-256 Checksum:</strong> {installer_sha256}<br />
        <strong>Signature Details:</strong> {sig_status_text}
      </div>

      <div class="legal-consent">
        <label>
          <input type="checkbox" id="accept-terms" />
          <span>
            I have read and agree to the
            <a href="{terms_url}" target="_blank" rel="noopener noreferrer">BitChat Terms of Use</a>
            (Draft — pending publisher/legal review).
          </span>
        </label>
        <label>
          <input type="checkbox" id="ack-privacy" />
          <span>
            I have read the
            <a href="{privacy_url}" target="_blank" rel="noopener noreferrer">BitChat Privacy Policy</a>
            (Draft — zero telemetry, no accounts, local-only keys).
          </span>
        </label>
        <p class="legal-note">
          <strong>Privacy Guarantee:</strong> Downloading BitChat requires no email address, no account registration,
          and no tracking or marketing consent. Acknowledging the Privacy Policy is informational only.
        </p>
      </div>

      <div>
        <a id="download-btn" class="btn-primary" href="{release_url}">
          Download {installer_filename} ({size_display})
        </a>
        <p class="legal-note">
          Official source: <a href="{releases_page_url}">GitHub Releases (Java-Mx/bitchat-python)</a>
        </p>
      </div>
    </div>

    <section>
      <h2>System Requirements</h2>
      <ul>
        <li><strong>Operating System:</strong> Windows 10 (version 1809 / build 17763 or newer) or Windows 11 (64-bit x64).</li>
        <li><strong>Transports:</strong> Bluetooth 4.0+ BLE adapter with Windows WinRT support, and/or Wi-Fi / Ethernet Local Area Network (LAN).</li>
        <li><strong>Disk Space:</strong> ~80 MB free disk space.</li>
        <li><strong>Privileges:</strong> Standard user account (installs to <code>%LOCALAPPDATA%\\Programs\\BitChat</code> by default; no Administrator rights required).</li>
        <li><strong>Runtime:</strong> Self-contained (Python, Textual, Bleak, WinRT, and Cryptography are bundled).</li>
      </ul>
    </section>

    <section>
      <h2>Installation &amp; Verification Instructions</h2>
      <p><strong>1. Verify the SHA-256 Checksum in PowerShell:</strong></p>
      <pre>Get-FileHash .\\{installer_filename} -Algorithm SHA256
# Expected Hash: {installer_sha256}</pre>
      <p><strong>2. Check Authenticode Signature Status:</strong></p>
      <pre>Get-AuthenticodeSignature .\\{installer_filename}</pre>
      <p><strong>3. Run the Installer (Interactive or WinGet):</strong></p>
      <pre># Run the downloaded installer wizard:
.\\{installer_filename}

# Or install via Windows Package Manager (WinGet):
winget install Java-Mx.BitChat</pre>
      <p><strong>4. Launch BitChat from a new PowerShell window:</strong></p>
      <pre>bitchat
bitchat --version
bitchat --help
bitchat --configure</pre>
    </section>

    <section>
      <h2>Security, Code Signing &amp; Windows SmartScreen</h2>
      <ul>
        <li><strong>Authenticode vs. SmartScreen Reputation:</strong> An Authenticode digital signature verifies publisher identity and guarantees that the binary has not been modified since signing. Windows Defender SmartScreen additionally evaluates download reputation across Windows users; even newly signed installers may display a SmartScreen prompt until reputation is established.</li>
        <li><strong>Current Signing Status:</strong> {sig_status_text}</li>
        <li><strong>Never Disable Security Protections:</strong> Do not disable Windows Defender or SmartScreen in system settings. Instead, verify the SHA-256 hash above against the official GitHub Release checksum file (<code>{installer_filename}.sha256</code>).</li>
      </ul>
    </section>

    <section>
      <h2>Changelog &amp; Troubleshooting</h2>
      <ul>
        <li><strong>v{version} Highlights:</strong> Self-contained Windows x64 installer 2.0 with official BitChat branding, Terms of Use &amp; Privacy Policy wizard screens, user-scope default installation, safe PATH management, optional per-user Windows sign-in startup, and identity-preserving upgrades/uninstallation. Full history in <a href="{changelog_url}">CHANGELOG.md</a>.</li>
        <li><strong><code>bitchat</code> not recognized after install:</strong> Close and reopen your PowerShell or Command Prompt window so the updated user <code>PATH</code> takes effect.</li>
        <li><strong>Manage Windows Startup at any time:</strong> Run <code>bitchat --startup status</code>, <code>bitchat --startup enable</code>, or <code>bitchat --startup disable</code>, or re-run the installer.</li>
        <li><strong>BLE GATT Status 3 on Windows:</strong> Some Windows Bluetooth drivers restrict GATT peripheral hosting; BitChat keeps BLE Central scanning active and offers one-click fallback to LAN transport.</li>
      </ul>
    </section>
  </div>

  <script>
    (function () {{
      var terms = document.getElementById('accept-terms');
      var privacy = document.getElementById('ack-privacy');
      var btn = document.getElementById('download-btn');
      if (!terms || !privacy || !btn) return;
      function syncState() {{
        if (terms.checked && privacy.checked) {{
          btn.classList.remove('disabled');
          btn.removeAttribute('aria-disabled');
        }} else {{
          btn.classList.add('disabled');
          btn.setAttribute('aria-disabled', 'true');
        }}
      }}
      terms.addEventListener('change', syncState);
      privacy.addEventListener('change', syncState);
      syncState();
    }})();
  </script>
</body>
</html>
"""
    html_file = html_dir / "index.html"
    html_file.write_text(html_content, encoding="utf-8")

    md_content = f"""# Download BitChat for Windows (x64)

<p align="center">
  <img src="download/assets/bitchat-wordmark-dark.png" alt="BitChat" width="280" />
</p>

## Official Windows Release Package

| Field | Value |
|---|---|
| **Application** | BitChat (`Java-Mx.BitChat`) |
| **Version** | `{version}` |
| **Publisher** | `Java-Mx` |
| **Platform / Architecture** | Windows 10 (1809+) & Windows 11 (`x64`) |
| **Installer Filename** | `{installer_filename}` |
| **Installer File Size** | {size_display} |
| **Release Date** | `{release_date}` |
| **SHA-256 Checksum** | `{installer_sha256}` |
| **Digital Signature Status** | {sig_status_text} |
| **Official Download URL** | [{release_url}]({release_url}) |
| **All Releases** | [GitHub Releases]({releases_page_url}) |

---

## Legal Notices & Pre-Download Review

Before downloading or installing BitChat, please review:

1. **[BitChat Terms of Use](../TERMS_OF_USE.md)** *(Draft — pending publisher/legal review)*
2. **[BitChat Privacy Policy](../PRIVACY_POLICY.md)** *(Draft — audited zero-telemetry, no accounts, local-only identity keys)*
3. **[MIT License](../LICENSE)** and **[Security Policy](../SECURITY.md)**

> **Privacy Commitment:** No personal information, email address, account creation, tracking, or marketing consent is required to download or use BitChat. Acknowledging the Privacy Policy during download or installation is informational only and never authorizes optional data collection.

---

## System Requirements

- **Operating System:** Windows 10 version 1809 (build 17763) or later, or Windows 11 (x64).
- **Hardware / Network:** Bluetooth 4.0+ Low Energy (BLE) adapter with Windows WinRT support, and/or Wi-Fi or Ethernet Local Area Network (LAN).
- **Disk Space:** At least 80 MB of free disk space.
- **Permissions:** Standard user account (installs to `%LOCALAPPDATA%\\Programs\\BitChat` by default; no Administrator privileges required).
- **Dependencies:** None (Python 3 runtime, Textual TUI, Bleak WinRT stack, and Cryptography are fully bundled).

---

## Checksum & Signature Verification

After downloading `{installer_filename}`, verify its integrity in PowerShell before running Setup:

```powershell
# 1. Verify SHA-256 Checksum
Get-FileHash .\\{installer_filename} -Algorithm SHA256
# Expected: {installer_sha256}

# 2. Inspect Authenticode Signature
Get-AuthenticodeSignature .\\{installer_filename} | Format-List *
```

---

## Installation, Startup, Upgrade & Uninstallation

### Interactive Setup Wizard
Run `{installer_filename}` to step through the 7-screen setup wizard:
1. **Welcome** — BitChat branding, version `{version}`, and publisher (`Java-Mx`).
2. **Terms of Use** — Scrollable Terms of Use with required acceptance checkbox.
3. **Privacy Policy** — Scrollable Privacy Policy with required acknowledgment checkbox.
4. **Installation Location** — Defaults to `%LOCALAPPDATA%\\Programs\\BitChat` with permission, disk-space, and conflict validation.
5. **Installation Options** — Configure Desktop shortcut (enabled), Start Menu shortcut (enabled), user `PATH` integration (enabled), Launch after installation (enabled), Start with Windows after sign-in (disabled by default), and Windows Installed Apps uninstaller entry (enabled).
6. **Installation Progress** — Real-time extraction progress and automatic rollback on interruption.
7. **Completion** — Summary of installed version, path, `PATH` status, startup configuration, and immediate launch option.

### Command-Line & WinGet Usage
```powershell
# Launch interactive TUI
bitchat --tui

# Launch headless CLI mode
bitchat --cli

# Inspect version, help, and hardware diagnostics
bitchat --version
bitchat --help
bitchat --configure

# Check or toggle per-user Windows sign-in startup
bitchat --startup status
bitchat --startup enable
bitchat --startup disable
```

### Troubleshooting
- **`bitchat` command not recognized:** Reopen your PowerShell or Command Prompt window after installation so the updated user `PATH` environment variable is loaded.
- **Windows Defender SmartScreen:** See [`docs/platform/WINDOWS.md`](platform/WINDOWS.md) for the distinction between Authenticode signature validity, publisher identity, and SmartScreen download reputation. Never disable Windows Defender or SmartScreen; always verify the SHA-256 checksum above.
"""
    md_path.write_text(md_content, encoding="utf-8")
    return html_file, md_path
