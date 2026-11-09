# Contributing to BitChat

Thank you for your interest in contributing to **BitChat**! This guide covers setting up the hybrid Python + Rust development environment, running quality checks, and submitting pull requests.

> **Security Vulnerabilities:** Do **not** report security vulnerabilities in public issues or pull requests. Please follow [`SECURITY.md`](SECURITY.md) and report privately via [GitHub Security Advisories](https://github.com/Java-Mx/bitchat-python/security/advisories/new).

---

## 1. Development Environment Setup

- **Python**: `3.10+` (`3.12` recommended)
- **Rust**: Stable Rust toolchain (`rustup`, `cargo`, `clippy`, `rustfmt`)
- **Package Manager**: [uv](https://github.com/astral-sh/uv)

### Clone & Synchronize

Fork [https://github.com/Java-Mx/bitchat-python](https://github.com/Java-Mx/bitchat-python) on GitHub, then clone your fork (or the upstream repository):

```bash
git clone https://github.com/Java-Mx/bitchat-python.git
cd bitchat-python
uv sync --all-groups
uv run --no-sync maturin develop --release
```

---

## 2. Branching & Development Workflow

1. Create a descriptive branch from `main`:
   - `feature/<name>` — New functionality
   - `bugfix/<name>` — Bug fixes
   - `docs/<name>` — Documentation improvements
   - `protocol/<name>` — Wire protocol or mesh routing changes
   - `security/<name>` — Non-sensitive security hardening
2. Implement your changes following the layered architecture in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
3. If you modify protocol framing, fragmentation, reassembly, TCP stream framing, or mesh deduplication/rate-limiting, update **both** the Rust implementation (`rust/bitchat-core/src/`) and the pure-Python reference fallback (`src/bitchat/`), and verify parity with `tests/unit/test_native_core.py`.

---

## 3. Required Quality Checks Before Opening a PR

All pull requests must pass both the Rust and Python check suites with zero warnings or errors:

```bash
# 1. Rust checks
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --no-default-features -- -D warnings
cargo test --workspace --no-default-features

# 2. Rebuild native extension if Rust code changed
uv run --no-sync maturin develop --release

# 3. Python lint, format, type check, and test suite
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pyright
uv run --no-sync pytest -q
```

---

## 4. Commit Conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — New features
- `fix:` — Bug fixes
- `perf:` — Performance optimizations
- `docs:` — Documentation updates
- `test:` — Test additions or fixes
- `refactor:` — Code refactoring without behavior changes
- `build:` / `ci:` / `chore:` — Build system, CI workflows, or maintenance

---

## 5. Pull Request Checklist

1. All Python (`pytest`, `ruff`, `pyright`) and Rust (`cargo test`, `cargo clippy`, `cargo fmt`) checks pass.
2. Differential equivalence tests (`tests/unit/test_native_core.py`) pass when touching protocol, framing, or mesh code.
3. Official documentation under `docs/` and root Markdown files is updated to match any behavioral, CLI, config, or protocol changes, and `tests/unit/test_documentation.py` passes.
4. Community interactions adhere to [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
