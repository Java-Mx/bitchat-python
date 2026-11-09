# BitChat Development Guide (`v0.3.1`)

## 1. Prerequisites & Environment Setup

- **Python**: `3.10+` (`3.12` recommended for release packaging; CI tests `3.10`, `3.11`, and `3.12`)
- **Rust Toolchain**: Stable Rust (`rustc` & `cargo` via [rustup](https://rustup.rs/), edition 2021)
- **Package Manager**: [uv](https://github.com/astral-sh/uv)
- **Native Extension Builder**: [Maturin](https://www.maturin.rs/) (installed automatically in the `uv` dev group)

From the repository root, synchronize all Python dependencies and build the editable package:

```bash
uv sync --all-groups
```

To compile and install the optimized Rust native extension (`bitchat._bitchat_core`) into your virtual environment:

```bash
uv run --no-sync maturin develop --release
```

> **Windows Note:** If rebuilding `_bitchat_core.pyd` while an existing `.pyd` is present on Windows, ensure no running `bitchat` or `python` process holds a lock on `src/bitchat/_bitchat_core.pyd`.

---

## 2. Running the Test Suite

The test suite is organized under `tests/`:

- `tests/unit/` — Unit tests for application core, TUI, storage, commands, platform detection, uninstaller, packaging, documentation, and Rust/Python differential parity (`test_native_core.py`).
- `tests/protocol/` — Binary wire encoding, decoding, padding, fragmentation, reassembly, and defensive bounds tests.
- `tests/crypto/` — `Noise_XX_25519_ChaChaPoly_SHA256`, `AES-256-GCM`, `X25519`, `Ed25519`, `HKDF`, `PBKDF2`, and `LocalIdentity` tests.
- `tests/ble/` & `tests/network/` — Simulated WinRT and BlueZ BLE transport tests, LAN UDP discovery, and TCP framing tests.
- `tests/mesh/` — Multi-hop flood routing, deduplication, and peer rate-limiting tests.
- `tests/integration/`, `tests/interoperability/`, `tests/e2e/`, `tests/stress/` — End-to-end multi-peer, interoperability vector, and adversarial stress tests.

### Python Tests

```bash
# Run full test suite
uv run --no-sync pytest

# Run specific test suites
uv run --no-sync pytest tests/unit/
uv run --no-sync pytest tests/protocol/
uv run --no-sync pytest tests/crypto/
uv run --no-sync pytest tests/ble/ tests/network/ tests/mesh/
uv run --no-sync pytest tests/unit/test_native_core.py
uv run --no-sync pytest tests/unit/test_uninstaller.py
uv run --no-sync pytest tests/unit/test_documentation.py
uv run --no-sync pytest tests/e2e/
```

### Rust Native Core Tests (`rust/bitchat-core`)

> **Important:** Because `bitchat-core` is a `cdylib` PyO3 extension crate, run `cargo test` and `cargo clippy` with `--no-default-features` (which disables the `extension-module` linker flag during standalone Rust test compilation):

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --no-default-features -- -D warnings
cargo test --workspace --no-default-features
```

---

## 3. Code Quality, Formatting & Static Analysis

```bash
# Python linting and formatting (Ruff)
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .

# Python static type checking (Pyright)
uv run --no-sync pyright

# Rust formatting
cargo fmt --all
```

---

## 4. Running BitChat Locally

```bash
# Launch interactive Textual TUI
uv run --no-sync bitchat --tui

# Launch headless CLI mode
uv run --no-sync bitchat --cli

# Run hardware and network capability diagnostics
uv run --no-sync bitchat --configure

# Preview uninstaller actions without modifying the system
uv run --no-sync bitchat --uninstall --dry-run
```

---

## 5. Differential Equivalence & Stress Verification

To run the Rust/Python differential equivalence and adversarial stress suites:

```bash
uv run --no-sync pytest tests/unit/test_native_core.py tests/stress/ -q
```

---

## 6. Building Distributable Packages

```bash
# Build Python wheel and sdist
uv build

# Build Windows standalone installer (.exe) and WinGet manifests (Windows only)
uv run python packaging/windows/build.py

# Build Linux .deb, AppImage, and Flatpak bundles (Linux only)
uv run python packaging/linux/build.py --build-flatpak
```

See [`docs/RELEASE_PROCESS.md`](RELEASE_PROCESS.md) for the complete release engineering workflow.
