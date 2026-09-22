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
