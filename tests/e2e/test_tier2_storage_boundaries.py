"""Tier 2: Boundary & Corner Cases — Storage & Persistence Boundaries."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import ConfigurationError
from bitchat.storage.config import (
    FileConfigStorage,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_load_corrupted_json_identity_raises_configuration_error(
    tmp_path: Path,
) -> None:
    """Validate invalid/corrupted JSON in identity.json raises ConfigurationError."""
    id_file = tmp_path / "identity.json"
    cfg_file = tmp_path / "config.json"
    id_file.write_text("{this is corrupted invalid JSON!!", encoding="utf-8")

    storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
    with pytest.raises(ConfigurationError, match="Failed to read identity"):
        storage.load_identity()


def test_load_identity_with_missing_key_fields_raises_configuration_error(
    tmp_path: Path,
) -> None:
    """Validate identity JSON missing private keys raises ConfigurationError."""
    id_file = tmp_path / "identity.json"
    cfg_file = tmp_path / "config.json"
    # JSON with peer_id but missing private keys
    id_file.write_text(json.dumps({"peer_id": "0102030405060708"}), encoding="utf-8")

    storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
    with pytest.raises(ConfigurationError, match="Missing private keys"):
        storage.load_identity()


def test_load_identity_with_invalid_hex_raises_configuration_error(
    tmp_path: Path,
) -> None:
    """Validate identity JSON containing non-hex characters raises ConfigurationError."""
    id_file = tmp_path / "identity.json"
    cfg_file = tmp_path / "config.json"
    id_file.write_text(
        json.dumps(
            {
                "x25519_private": "NOT_A_VALID_HEX_STRING_ZZZZZ",
                "ed25519_private": "NOT_A_VALID_HEX_STRING_ZZZZZ",
            }
        ),
        encoding="utf-8",
    )

    storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
    with pytest.raises(ConfigurationError, match="Failed to read identity"):
        storage.load_identity()


def test_closed_storage_load_identity_raises_configuration_error(
    tmp_path: Path,
) -> None:
    """Validate reading identity from closed storage raises ConfigurationError."""
    cfg_file = tmp_path / "config.json"
    id_file = tmp_path / "identity.json"
    storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
    storage.close()

    with pytest.raises(ConfigurationError, match="closed storage"):
        storage.load_identity()


def test_closed_storage_save_identity_raises_configuration_error(
    tmp_path: Path,
) -> None:
    """Validate saving identity to closed storage raises ConfigurationError."""
    cfg_file = tmp_path / "config.json"
    id_file = tmp_path / "identity.json"
    storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
    storage.close()

    identity = LocalIdentity.generate()
    with pytest.raises(ConfigurationError, match="closed storage"):
        storage.save_identity(identity)


def test_load_corrupted_config_json_raises_configuration_error(tmp_path: Path) -> None:
    """Validate corrupted config.json raises ConfigurationError."""
    cfg_file = tmp_path / "config.json"
    id_file = tmp_path / "identity.json"
    cfg_file.write_text("MALFORMED_CONFIG_JSON_CONTENT{{{", encoding="utf-8")

    storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
    with pytest.raises(ConfigurationError, match="Failed to read configuration"):
        storage.load_config()
