# Development Guide

## Environment Setup
- **Python version**: 3.12+
- **Package manager**: uv

The Windows PowerShell and Linux commands are the same. From the repository root,
create or synchronize the environment with:
```bash
uv sync --all-groups
```
Project and development dependencies are defined only in `pyproject.toml`; `uv.lock`
pins the resolved environment. Use `uv add` / `uv remove` for dependency changes and
`uv lock` to refresh the lockfile. Do not maintain a second requirements file.

## Running Tests
Run the checks through uv so they use the synchronized project environment (these
commands work in both PowerShell and a Linux shell):
```bash
uv run pytest
uv run pytest -v
uv run pytest tests/protocol/  # Protocol binary packet layer tests
uv run pytest tests/unit/      # Application core unit tests
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

## Code Quality Tools
To apply Ruff formatting:
```bash
uv run ruff format .
```
Build the package with:
```bash
uv build
```

## Running the CLI
```bash
uv run bitchat
```

## Development Workflow
1. Create a branch:
   - `feature/<name>`
   - `bugfix/<name>`
   - `docs/<name>`
   - `protocol/<name>`
   - `security/<name>`
2. Implement your changes.
3. Test, format, lint, and type-check.
4. Open a Pull Request.

On Windows, run these commands from PowerShell; on Linux, run them from a shell.
Bluetooth hardware checks still require a supported adapter and are not replaced by
the platform-mocked test suite.

## Pull Request Expectations
- All tests and checks must pass.
- Commit messages must follow conventional commits.
- Documentation and changelog must be updated.
