# BitChat Release Engineering Process (`v0.3.1`)

This document describes the official release process for BitChat (`https://github.com/Java-Mx/bitchat-python`), reflecting the actual build scripts (`packaging/windows/build.py`, `packaging/linux/build.py`) and GitHub Actions workflows (`.github/workflows/ci.yml`, `.github/workflows/build.yml`, `.github/workflows/security.yml`, and `.github/workflows/release.yml`).

---

## 1. Version Synchronization Locations

BitChat uses Semantic Versioning (`MAJOR.MINOR.PATCH`, currently `0.3.1`). Every release must update the version consistently across the following files:

| File | Field / Location |
| :--- | :--- |
| `pyproject.toml` | `[project] version = "0.3.1"` |
| `src/bitchat/__init__.py` | `__version__ = "0.3.1"` |
| `Cargo.toml` | `[workspace.package] version = "0.3.1"` (inherited by `rust/bitchat-core/Cargo.toml`) |
| `Cargo.lock` & `uv.lock` | Workspace package versions synchronized via `cargo check` and `uv lock` |
| `packaging/windows/bitchat.iss` | `#define MyAppVersion "0.3.1"` |
| `packaging/windows/version_info.txt` | `filevers=(0, 3, 1, 0)`, `prodvers=(0, 3, 1, 0)`, `FileVersion`, `ProductVersion` |
| `packaging/windows/winget/Java-Mx.BitChat.yaml` | `PackageVersion: 0.3.1` and `InstallerUrl` / `InstallerSha256` |
| `packaging/linux/flatpak/io.github.java_mx.bitchat.metainfo.xml` | `<release version="0.3.1" date="YYYY-MM-DD">` |
| `packaging/linux/flatpak/io.github.java_mx.bitchat.yaml` | Flatpak manifest metadata |
| `packaging/linux/snap/snapcraft.yaml` | `version: '0.3.1'` |
| `CHANGELOG.md` | Release section header `## [0.3.1] - YYYY-MM-DD` |
| `README.md`, `docs/DOWNLOAD.md`, `docs/download/index.html` | Direct download links, asset filenames, and SHA-256 checksums |

Automated tests in `tests/unit/test_package.py`, `tests/unit/test_packaging_windows.py`, `tests/unit/test_packaging_linux.py`, and `tests/unit/test_documentation.py` verify that these version strings remain synchronized.

---

## 2. Pre-Release Validation Gates

Before creating a release commit or tag, all Rust and Python quality gates must pass locally and in CI:

### 2.1 Rust Core Checks (`rust/bitchat-core`)

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --no-default-features -- -D warnings
cargo test --workspace --no-default-features
```

### 2.2 Native Extension Build & Differential Verification

```bash
uv run --no-sync maturin develop --release
uv run --no-sync pytest tests/unit/test_native_core.py -q
```

### 2.3 Python Lint, Type Check, Test & Documentation Gates

```bash
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pyright
uv run --no-sync pytest -q
```

---

## 3. Local Packaging Scripts

### 3.1 Windows Standalone Installer & WinGet Manifest (`packaging/windows/build.py`)

Running `uv run python packaging/windows/build.py` performs a 5-stage build pipeline on Windows x64:

1. **Pre-build Validation:** Synchronizes `packaging/windows/version_info.txt` with `pyproject.toml` and verifies icon assets (`assets/icons/bitchat.ico`).
2. **PyInstaller Standalone Freeze:** Compiles `bitchat.exe` using `packaging/windows/bitchat.spec`, bundling the compiled `bitchat._bitchat_core` Rust extension, Textual TCSS stylesheets (`src/bitchat/tui/styles/app.tcss`), and WinRT BLE backends.
3. **Inno Setup Compilation (`ISCC.exe`):** Compiles `packaging/windows/bitchat.iss` into `dist/BitChat-<version>-windows-x64.exe` (supporting per-user install by default without UAC elevation, optional `--startup-launch` shortcut, safe `PATH` registration, and comprehensive uninstall cleanup).
4. **Optional Authenticode Signing:**
   - If `WINDOWS_SIGNING_CERT` (or `WINDOWS_SIGNING_THUMBPRINT`) is configured, signs both `bitchat.exe` and `BitChat-<version>-windows-x64.exe` using `signtool.exe` with SHA-256 (`fd SHA256`) and an RFC 3161 timestamp server.
   - If no signing certificate is configured (`WINDOWS_SIGNING_REQUIRED != "true"`), the build succeeds and records `"signed": false` in `dist/BitChat-<version>-windows-x64.metadata.json`. Unsigned builds **must not** be advertised as Authenticode-signed.
5. **Checksums & WinGet Manifest Generation:** Generates `dist/BitChat-<version>-windows-x64.exe.sha256` and updates `packaging/windows/winget/Java-Mx.BitChat.yaml` plus multi-file manifests in `manifests/j/Java-Mx/BitChat/<version>/`.

### 3.2 Linux Distributables (`packaging/linux/build.py`)

Running `uv run python packaging/linux/build.py --build-flatpak` on Linux x86_64 produces:

1. **Standalone Binary:** Frozen via PyInstaller (`packaging/linux/bitchat.spec`) with `bitchat._bitchat_core` bundled.
2. **Debian Package (`.deb`):** `dist/bitchat_<version>_amd64.deb` and `.sha256`, including `/usr/bin/bitchat`, desktop launcher, icons, and `postrm` cleanup hooks.
3. **AppImage:** `dist/BitChat-<version>-x86_64.AppImage` and `.sha256`.
4. **Flatpak Bundle:** `dist/BitChat-<version>-x86_64.flatpak` and `.sha256` (when `--build-flatpak` is passed and `flatpak-builder` is installed).

---

## 4. Automated GitHub Actions Release Workflow (`.github/workflows/release.yml`)

Pushing a version tag matching `v*` (e.g., `git tag -a v0.3.1 -m "Release v0.3.1" && git push origin v0.3.1`) or triggering `workflow_dispatch` on `.github/workflows/release.yml` runs three coordinated jobs:

1. **`build-linux` (`ubuntu-latest`):**
   - Sets up Python 3.12 (`uv`), stable Rust toolchain (`dtolnay/rust-toolchain@stable`), and system packages (`libdbus-1-dev`, `dpkg-dev`, `flatpak-builder`).
   - Runs `ruff`, `pyright`, and `pytest`.
   - Builds the Linux wheel (`bitchat_python-<version>-cp312-cp312-linux_x86_64.whl`) and source distribution (`bitchat_python-<version>.tar.gz`) via `uv build`.
   - Builds `.deb`, `.AppImage`, and `.flatpak` artifacts along with `.sha256` checksum files.
2. **`build-windows` (`windows-latest`):**
   - Sets up Python 3.12 (`uv`), stable Rust toolchain, and Inno Setup 6.
   - Builds the Windows wheel (`bitchat_python-<version>-cp312-cp312-win_amd64.whl`).
   - Runs Windows packaging and uninstaller unit tests.
   - Runs `packaging/windows/build.py` to produce `BitChat-<version>-windows-x64.exe` and `.sha256`.
   - Performs an end-to-end silent install smoke test (`--version`, `--help`, `--startup status`, `--uninstall --dry-run`, and `unins000.exe`).
3. **`publish` (`ubuntu-latest`):**
   - Collects all Linux and Windows artifacts, generates `.sha256` files for wheels and sdist archives, verifies that all mandatory artifacts exist, and publishes the GitHub Release via `softprops/action-gh-release@v3`.

### Official Release Asset Inventory (13 Assets for `v0.3.1`)

Every official release publishes the following 13 assets:

1. `BitChat-<version>-windows-x64.exe`
2. `BitChat-<version>-windows-x64.exe.sha256`
3. `bitchat_<version>_amd64.deb`
4. `bitchat_<version>_amd64.deb.sha256`
5. `BitChat-<version>-x86_64.AppImage`
6. `BitChat-<version>-x86_64.AppImage.sha256`
7. `BitChat-<version>-x86_64.flatpak`
8. `BitChat-<version>-x86_64.flatpak.sha256`
9. `bitchat_python-<version>-cp312-cp312-win_amd64.whl`
10. `bitchat_python-<version>-cp312-cp312-win_amd64.whl.sha256`
11. `bitchat_python-<version>-cp312-cp312-linux_x86_64.whl`
12. `bitchat_python-<version>-cp312-cp312-linux_x86_64.whl.sha256`
13. `bitchat_python-<version>.tar.gz` (plus `bitchat_python-<version>.tar.gz.sha256` and `Java-Mx.BitChat.yaml`)

---

## 5. Post-Release Verification

After `.github/workflows/release.yml` completes:

1. Verify that all release assets are attached to `https://github.com/Java-Mx/bitchat-python/releases/tag/v<version>` and that every `.sha256` file matches its corresponding binary asset.
2. Update `docs/DOWNLOAD.md` and `docs/download/index.html` if the release workflow generated a new Windows `.exe` SHA-256 hash or byte size.
3. Verify that the GitHub Release body contains the full structured release notes from `CHANGELOG.md`.
