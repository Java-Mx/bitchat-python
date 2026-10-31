"""Tier 1: Feature Coverage — Storage, Atomic Persistence & AppConfig."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from bitchat.crypto.identity import LocalIdentity
from bitchat.storage.config import (
    AppConfig,
    FileConfigStorage,
    InMemoryStorage,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_in_memory_storage_save_load_identity() -> None:
    """Validate in-memory identity storage roundtrip preserves all keys and fingerprints."""
    storage = InMemoryStorage()
    assert storage.load_identity() is None

    identity = LocalIdentity.generate()
    storage.save_identity(identity)
    assert storage.load_identity() is not None

    loaded = storage.load_identity()
    assert loaded is not None
    assert loaded.fingerprint == identity.fingerprint
    assert loaded.peer_id == identity.peer_id
    assert loaded.x25519_public == identity.x25519_public
    assert loaded.x25519_private == identity.x25519_private
    assert loaded.ed25519_public == identity.ed25519_public
    assert loaded.ed25519_private == identity.ed25519_private


def test_file_config_storage_save_load_identity(tmp_path: Path) -> None:
    """Validate FileConfigStorage writes identity.json to disk and restores identical keys."""
    cfg_file = tmp_path / "config.json"
    id_file = tmp_path / "identity.json"
    storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
    assert storage.load_identity() is None

    identity = LocalIdentity.generate()
    storage.save_identity(identity)
    assert storage.load_identity() is not None

    # Verify file actually exists on filesystem
    assert id_file.exists()

    # Load from clean storage instance pointing to same file
    storage2 = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
    loaded = storage2.load_identity()
    assert loaded is not None

    assert loaded.fingerprint == identity.fingerprint
    assert loaded.peer_id == identity.peer_id
    assert loaded.x25519_public == identity.x25519_public
    assert loaded.ed25519_public == identity.ed25519_public


def test_file_config_storage_save_load_app_config(tmp_path: Path) -> None:
    """Validate AppConfig serialization and disk persistence."""
    cfg_file = tmp_path / "config.json"
    id_file = tmp_path / "identity.json"
    storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)

    config = AppConfig(
        nickname="CyberNode",
        debug=True,
        density="compact",
        accent="emerald",
        transport="lan",
        max_hops=5,
    )
    storage.save_config(config)

    assert cfg_file.exists()

    storage2 = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
    loaded = storage2.load_config()

    assert loaded.nickname == "CyberNode"
    assert loaded.debug is True
    assert loaded.density == "compact"
    assert loaded.accent == "emerald"
    assert loaded.transport == "lan"
    assert loaded.max_hops == 5


def test_app_config_validation_and_defaults() -> None:
    """Validate that invalid config properties fall back to safe default values."""
    config = AppConfig(
        density="invalid_density",
        accent="invalid_color",
        transport="carrier_pigeon",
        max_hops=999,  # Must be clamped
    )

    assert config.density == "comfortable"
    assert config.accent == "blue"
    assert config.transport == "bluetooth"
    assert config.max_hops == 7  # Clamped to max 7


def test_storage_identity_presence_check(tmp_path: Path) -> None:
    """Validate load_identity returns None when file is absent and LocalIdentity when present."""
    cfg_file = tmp_path / "config.json"
    id_file = tmp_path / "identity.json"
    storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
    assert storage.load_identity() is None

    identity = LocalIdentity.generate()
    storage.save_identity(identity)
    assert storage.load_identity() is not None


def test_atomic_write_creates_valid_json(tmp_path: Path) -> None:
    """Validate atomic file write produces fully parseable, uncorrupted JSON."""
    cfg_file = tmp_path / "config.json"
    id_file = tmp_path / "identity.json"
    storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
    identity = LocalIdentity.generate()
    storage.save_identity(identity)

    with open(id_file, encoding="utf-8") as f:
        data = json.load(f)

    assert "x25519_private" in data
    assert "ed25519_private" in data
    assert "peer_id" in data
    assert "fingerprint" in data
