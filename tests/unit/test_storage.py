"""Unit tests for BitChat storage implementations."""

from pathlib import Path

import pytest

from bitchat.exceptions import ConfigurationError
from bitchat.storage.config import AppConfig, FileConfigStorage, InMemoryStorage


class TestStorage:
    """Tests for StorageInterface implementations."""

    def test_in_memory_storage_load_save(self) -> None:
        """InMemoryStorage accurately persists and retrieves config."""
        storage = InMemoryStorage(AppConfig(nickname="Tester", debug=True))
        cfg = storage.load_config()
        assert cfg.nickname == "Tester"
        assert cfg.debug is True

        storage.save_config(AppConfig(nickname="NewNick", debug=False))
        updated = storage.load_config()
        assert updated.nickname == "NewNick"
        assert updated.debug is False

    def test_in_memory_storage_closed_operations_raise(self) -> None:
        """Operating on closed InMemoryStorage raises ConfigurationError."""
        storage = InMemoryStorage()
        storage.close()
        with pytest.raises(ConfigurationError):
            storage.load_config()
        with pytest.raises(ConfigurationError):
            storage.save_config(AppConfig())

    def test_file_storage_roundtrip(self, tmp_path: Path) -> None:
        """FileConfigStorage serializes and deserializes JSON config."""
        config_file = tmp_path / "subdir" / "config.json"
        storage = FileConfigStorage(config_path=config_file)

        # Default when file does not exist
        default_cfg = storage.load_config()
        assert default_cfg.nickname == "Anonymous"

        # Save new configuration
        storage.save_config(AppConfig(nickname="FileUser", debug=True))
        assert config_file.exists()

        # Reload configuration
        reloaded_storage = FileConfigStorage(config_path=config_file)
        loaded = reloaded_storage.load_config()
        assert loaded.nickname == "FileUser"
        assert loaded.debug is True

    def test_file_storage_corrupted_file_raises(self, tmp_path: Path) -> None:
        """Invalid JSON file raises ConfigurationError."""
        config_file = tmp_path / "corrupt.json"
        config_file.write_text("not json content", encoding="utf-8")

        storage = FileConfigStorage(config_path=config_file)
        with pytest.raises(ConfigurationError, match="Failed to read configuration"):
            storage.load_config()

    def test_file_storage_closed_operations_raise(self, tmp_path: Path) -> None:
        """Operating on closed FileConfigStorage raises ConfigurationError."""
        storage = FileConfigStorage(config_path=tmp_path / "cfg.json")
        storage.close()
        with pytest.raises(ConfigurationError):
            storage.load_config()
        with pytest.raises(ConfigurationError):
            storage.save_config(AppConfig())
        with pytest.raises(ConfigurationError):
            storage.load_identity()

    def test_in_memory_identity_load_save(self) -> None:
        """InMemoryStorage persists and retrieves LocalIdentity."""
        from bitchat.crypto.identity import LocalIdentity

        storage = InMemoryStorage()
        assert storage.load_identity() is None

        identity = LocalIdentity.generate()
        storage.save_identity(identity)
        loaded = storage.load_identity()
        assert loaded is not None
        assert loaded.peer_id == identity.peer_id
        assert loaded.fingerprint == identity.fingerprint
        assert loaded.x25519_private == identity.x25519_private
        assert loaded.ed25519_private == identity.ed25519_private

    def test_file_identity_roundtrip(self, tmp_path: Path) -> None:
        """FileConfigStorage serializes and deserializes identity."""
        from bitchat.crypto.identity import LocalIdentity

        id_file = tmp_path / "keys" / "identity.json"
        storage = FileConfigStorage(
            config_path=tmp_path / "cfg.json",
            identity_path=id_file,
        )

        assert storage.load_identity() is None

        identity = LocalIdentity.generate()
        storage.save_identity(identity)
        assert id_file.exists()

        reloaded = FileConfigStorage(
            config_path=tmp_path / "cfg.json",
            identity_path=id_file,
        )
        loaded = reloaded.load_identity()
        assert loaded is not None
        assert loaded.peer_id == identity.peer_id
        assert loaded.fingerprint == identity.fingerprint
        assert loaded.x25519_private == identity.x25519_private
        assert loaded.ed25519_private == identity.ed25519_private

    def test_file_identity_corrupted_raises(self, tmp_path: Path) -> None:
        """Corrupted identity JSON raises ConfigurationError."""
        id_file = tmp_path / "bad_identity.json"
        id_file.write_text(
            '{"x25519_private": "invalid_hex!", "ed25519_private": "invalid_hex!"}',
            encoding="utf-8",
        )

        storage = FileConfigStorage(
            config_path=tmp_path / "cfg.json",
            identity_path=id_file,
        )
        with pytest.raises(ConfigurationError, match="Failed to read identity"):
            storage.load_identity()

    def test_app_config_defaults_and_validation(self) -> None:
        """AppConfig enforces default values and bounds clamping."""
        cfg = AppConfig()
        assert cfg.density == "comfortable"
        assert cfg.show_timestamps is True
        assert cfg.accent == "blue"
        assert cfg.max_hops == 3
        assert cfg.inter_fragment_delay_ms == 20

        # Normalization and bounds enforcement
        clamped = AppConfig(
            density="unknown-mode",
            accent="neon-yellow",
            max_hops=999,
            inter_fragment_delay_ms=9999,
            nickname="   ",
        )
        assert clamped.density == "comfortable"
        assert clamped.accent == "blue"
        assert clamped.max_hops == 7
        assert clamped.inter_fragment_delay_ms == 500
        assert clamped.nickname == "Anonymous"

    def test_app_config_defensive_deserialization(self) -> None:
        """AppConfig.from_dict sanitizes malformed data without raising."""
        # Non-dict
        assert AppConfig.from_dict("not-a-dict") == AppConfig()  # type: ignore[arg-type]

        # Corrupted fields with wrong types
        bad_data = {
            "nickname": None,
            "density": 12345,
            "show_timestamps": None,
            "accent": ["invalid"],
            "max_hops": "invalid-int",
            "inter_fragment_delay_ms": None,
        }
        safe_cfg = AppConfig.from_dict(bad_data)
        assert safe_cfg.nickname == "Anonymous"
        assert safe_cfg.density == "comfortable"
        assert safe_cfg.show_timestamps is True
        assert safe_cfg.accent == "blue"
        assert safe_cfg.max_hops == 3
        assert safe_cfg.inter_fragment_delay_ms == 20

        # Valid custom dictionary
        custom_data = {
            "nickname": "CustomNode",
            "density": "compact",
            "show_timestamps": False,
            "accent": "emerald",
            "max_hops": 5,
            "inter_fragment_delay_ms": 50,
        }
        parsed = AppConfig.from_dict(custom_data)
        assert parsed.nickname == "CustomNode"
        assert parsed.density == "compact"
        assert parsed.show_timestamps is False
        assert parsed.accent == "emerald"
        assert parsed.max_hops == 5
        assert parsed.inter_fragment_delay_ms == 50

    def test_file_storage_complete_appearance_roundtrip(self, tmp_path: Path) -> None:
        """FileConfigStorage accurately preserves appearance and node configuration."""
        cfg_file = tmp_path / "custom_config.json"
        storage = FileConfigStorage(config_path=cfg_file)

        initial = AppConfig(
            nickname="TestPilot",
            density="compact",
            show_timestamps=False,
            accent="purple",
            max_hops=4,
            inter_fragment_delay_ms=35,
        )
        storage.save_config(initial)

        reloaded_storage = FileConfigStorage(config_path=cfg_file)
        loaded = reloaded_storage.load_config()
        assert loaded.nickname == "TestPilot"
        assert loaded.density == "compact"
        assert loaded.show_timestamps is False
        assert loaded.accent == "purple"
        assert loaded.max_hops == 4
        assert loaded.inter_fragment_delay_ms == 35
