"""Regression tests for local identity persistence across application launches."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

import pytest

from bitchat.app.application import Application
from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import ConfigurationError
from bitchat.storage.config import FileConfigStorage

if TYPE_CHECKING:
    from pathlib import Path


def _storage(tmp_path: Path) -> FileConfigStorage:
    return FileConfigStorage(
        config_path=tmp_path / "config.json",
        identity_path=tmp_path / "identity.json",
    )


def _launch(tmp_path: Path) -> Application:
    """Simulate one application launch against the on-disk storage."""
    app = Application(storage=_storage(tmp_path))
    app._ensure_coordinator()
    return app


def test_first_launch_creates_and_persists_identity(tmp_path: Path) -> None:
    identity_file = tmp_path / "identity.json"
    assert not identity_file.exists()

    app = _launch(tmp_path)

    assert identity_file.exists()
    assert app.coordinator is not None
    persisted = _storage(tmp_path).load_identity()
    assert persisted is not None
    assert persisted.x25519_private == app.coordinator.local_identity.x25519_private
    assert persisted.peer_id == app.coordinator.local_identity.peer_id


def test_second_launch_reloads_same_identity(tmp_path: Path) -> None:
    first = _launch(tmp_path)
    second = _launch(tmp_path)

    assert first.coordinator is not None
    assert second.coordinator is not None
    first_id = first.coordinator.local_identity
    second_id = second.coordinator.local_identity
    assert second_id.x25519_private == first_id.x25519_private
    assert second_id.ed25519_private == first_id.ed25519_private
    assert second_id.peer_id_hex == first_id.peer_id_hex
    assert second_id.fingerprint == first_id.fingerprint


def test_displayed_values_match_persisted_public_key(tmp_path: Path) -> None:
    app = _launch(tmp_path)
    assert app.coordinator is not None
    identity = app.coordinator.local_identity

    persisted = _storage(tmp_path).load_identity()
    assert persisted is not None
    digest = hashlib.sha256(persisted.x25519_public).digest()
    assert identity.fingerprint == digest.hex()
    assert identity.peer_id_hex == digest[:8].hex()
    # The BLE manager must advertise the same peer ID as the session identity.
    assert app.ble_manager is not None
    assert app.ble_manager.sender_id == identity.peer_id


def test_independently_generated_identities_differ() -> None:
    a = LocalIdentity.generate()
    b = LocalIdentity.generate()
    assert a.x25519_private != b.x25519_private
    assert a.fingerprint != b.fingerprint
    assert a.peer_id != b.peer_id


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        "{}",
        json.dumps({"x25519_private": "00" * 31, "ed25519_private": "00" * 32}),
        json.dumps({"x25519_private": "00" * 32, "ed25519_private": "00" * 31}),
        json.dumps({"x25519_private": "zz" * 32, "ed25519_private": "00" * 32}),
        json.dumps({"x25519_private": 5, "ed25519_private": "00" * 32}),
        json.dumps({"x25519_private": "00" * 32}),
    ],
)
def test_invalid_identity_is_never_silently_replaced(
    tmp_path: Path, payload: str
) -> None:
    identity_file = tmp_path / "identity.json"
    identity_file.write_text(payload, encoding="utf-8")
    before = identity_file.read_bytes()

    with pytest.raises(ConfigurationError):
        _launch(tmp_path)

    # The unreadable file must be left exactly as found for manual recovery.
    assert identity_file.read_bytes() == before


def test_invalid_identity_error_does_not_leak_key_material(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "ab" * 31  # 31-byte (invalid) key: rejected after hex decoding
    identity_file = tmp_path / "identity.json"
    identity_file.write_text(
        json.dumps({"x25519_private": secret, "ed25519_private": "cd" * 32}),
        encoding="utf-8",
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(ConfigurationError) as exc:
        _storage(tmp_path).load_identity()

    rendered = str(exc.value) + repr(exc.value.__cause__) + caplog.text
    assert secret not in rendered
    assert "cd" * 32 not in rendered
