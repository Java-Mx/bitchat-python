# Development Guide

## Environment Setup
- **Python version**: 3.12+
- **Package manager**: uv

To set up the environment:
```bash
uv sync --all-groups
```

## Running Tests
Run the test suite using pytest:
```bash
uv run pytest
uv run pytest -v
uv run pytest tests/unit/
```

## Code Quality Tools
Running Ruff for linting and formatting:
```bash
uv run ruff check .
uv run ruff format .
uv run ruff format --check .
```

Running Pyright for static type checking:
```bash
uv run pyright
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

## Pull Request Expectations
- All tests and checks must pass.
- Commit messages must follow conventional commits.
- Documentation and changelog must be updated.
