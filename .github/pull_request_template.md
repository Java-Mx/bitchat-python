## Summary

<!-- Provide a high-level explanation of the motivation and context for these changes. -->

## Changes

<!-- Detail the specific changes introduced in this PR. -->
- 

## Testing

<!-- Describe the tests implemented or run to verify your changes, including test environment details. -->

## Protocol Impact

<!-- Describe any impact on the BitChat BLE protocol (framing, packets, handshakes, TLV encodings). State "None" if unaffected. -->

## Security Impact

<!-- Detail any security considerations, cryptographic alterations, or sensitive data handling changes. State "None" if unaffected. -->

## Compatibility Impact

<!-- Explain compatibility with previous bitchat-python versions and other BitChat clients (e.g., Rust reference implementation). -->

## Documentation

<!-- Note any updates to README, docs, inline docstrings, or specifications. -->

## Checklist
- [ ] Python tests pass (`uv run --no-sync pytest`)
- [ ] Rust tests pass (`cargo test --workspace --no-default-features`)
- [ ] Rust formatting & clippy pass (`cargo fmt --all -- --check` & `cargo clippy --workspace --all-targets --no-default-features -- -D warnings`)
- [ ] Python/Rust differential equivalence tests pass (`uv run --no-sync pytest tests/unit/test_native_core.py`)
- [ ] Python formatting & linting pass (`uv run --no-sync ruff format --check .` & `uv run --no-sync ruff check .`)
- [ ] Static type checking passes (`uv run --no-sync pyright`)
- [ ] Documentation updated and documentation checks pass (`uv run --no-sync pytest tests/unit/test_documentation.py`)
- [ ] Security implications reviewed (if applicable)
- [ ] Protocol compatibility verified (if applicable)
- [ ] `CHANGELOG.md` updated (if applicable)
