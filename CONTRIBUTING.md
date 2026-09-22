# Contributing to BitChat Python

We love your input! We want to make contributing to this project as easy and transparent as possible.

## Development Environment Setup
- **Python**: 3.12+
- **Package Manager**: [uv](https://github.com/astral-sh/uv)

## Repository Setup
```bash
git clone https://github.com/your-username/bitchat-python.git
cd bitchat-python
uv sync --all-groups
```

## Development Workflow
1. **Branch Naming**:
   - `feature/<name>` for new features
   - `bugfix/<name>` for bug fixes
   - `docs/<name>` for documentation updates
   - `protocol/<name>` for protocol implementation
   - `security/<name>` for security/crypto updates
2. Implement your changes.
3. Test, format, lint, and type-check your code.

## Testing and Quality Checks
Ensure all the following checks pass before submitting a PR:
- **Testing**: `uv run pytest`
- **Formatting**: `uv run ruff format .`
- **Linting**: `uv run ruff check .`
- **Type checking**: `uv run pyright`

## Commit Conventions
We use [Conventional Commits](https://www.conventionalcommits.org/). Prefix your commits with:
- `feat:` for new features
- `fix:` for bug fixes
- `docs:` for documentation changes
- `test:` for adding or fixing tests
- `chore:` for maintenance tasks
- `ci:` for continuous integration changes
- `build:` for build system changes
- `refactor:` for code refactoring

## Pull Request Process
1. Ensure all tests pass, code is formatted, linted, and type-checked.
2. Ensure documentation is updated for your changes.
3. Update the changelog if applicable.
4. Protocol-change requirements: Any change affecting protocol, packet format, crypto, BLE, or interop must include corresponding tests and documentation.
5. Interoperability-test requirements: Protocol changes must be validated against the reference implementation.
