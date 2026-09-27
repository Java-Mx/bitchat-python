"""Unit tests for BitChat storage implementations."""

import getpass
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from bitchat.exceptions import ConfigurationError
from bitchat.storage import config as storage_module
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

    def test_identity_file_is_restricted_before_private_keys_are_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Identity file and temp file are owner-only before key material is written."""
        from bitchat.crypto.identity import LocalIdentity

        if os.name != "posix":
            pytest.skip("POSIX file modes are unavailable")

        id_file = tmp_path / "identity.json"
        storage = FileConfigStorage(identity_path=id_file)
        original_dump = storage_module.json.dump

        def assert_restricted_dump(data: Any, file_obj: Any, **kwargs: Any) -> None:
            temporary_files = list(tmp_path.glob(".identity.json.*.tmp"))
            assert len(temporary_files) == 1
            assert stat.S_IMODE(temporary_files[0].stat().st_mode) == 0o600
            original_dump(data, file_obj, **kwargs)

        monkeypatch.setattr(storage_module.json, "dump", assert_restricted_dump)
        storage.save_identity(LocalIdentity.generate())

        assert stat.S_IMODE(id_file.stat().st_mode) == 0o600
        assert list(tmp_path.glob(".identity.json.*.tmp")) == []

    def test_legacy_identity_file_loads_and_is_restricted(self, tmp_path: Path) -> None:
        """Existing plaintext JSON identity files remain readable and are hardened."""
        from bitchat.crypto.identity import LocalIdentity

        identity = LocalIdentity.generate()
        id_file = tmp_path / "identity.json"
        id_file.write_text(
            json.dumps(
                {
                    "x25519_private": identity.x25519_private.hex(),
                    "ed25519_private": identity.ed25519_private.hex(),
                    "fingerprint": identity.fingerprint,
                    "peer_id": identity.peer_id.hex(),
                }
            ),
            encoding="utf-8",
        )
        if os.name == "posix":
            id_file.chmod(0o644)

        loaded = FileConfigStorage(identity_path=id_file).load_identity()

        assert loaded is not None
        assert loaded.peer_id == identity.peer_id
        assert loaded.x25519_private == identity.x25519_private
        assert loaded.ed25519_private == identity.ed25519_private
        if os.name == "posix":
            assert stat.S_IMODE(id_file.stat().st_mode) == 0o600

    def test_failed_identity_write_preserves_file_and_cleans_temporary_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed atomic write leaves the old identity and no temp file."""
        from bitchat.crypto.identity import LocalIdentity

        id_file = tmp_path / "identity.json"
        storage = FileConfigStorage(identity_path=id_file)
        storage.save_identity(LocalIdentity.generate())
        previous_contents = id_file.read_bytes()

        def fail_dump(*args: Any, **kwargs: Any) -> None:
            raise OSError("simulated write failure")

        monkeypatch.setattr(storage_module.json, "dump", fail_dump)
        with pytest.raises(ConfigurationError, match="simulated write failure"):
            storage.save_identity(LocalIdentity.generate())

        assert id_file.read_bytes() == previous_contents
        assert list(tmp_path.glob(".identity.json.*.tmp")) == []

    def test_failed_atomic_replace_preserves_file_and_cleans_temporary_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed replace does not damage the existing identity file."""
        from bitchat.crypto.identity import LocalIdentity

        id_file = tmp_path / "identity.json"
        storage = FileConfigStorage(identity_path=id_file)
        storage.save_identity(LocalIdentity.generate())
        previous_contents = id_file.read_bytes()

        def fail_replace(_source: Path, _target: Path) -> None:
            raise OSError("simulated replace failure")

        monkeypatch.setattr(Path, "replace", fail_replace)
        with pytest.raises(ConfigurationError, match="simulated replace failure"):
            storage.save_identity(LocalIdentity.generate())

        assert id_file.read_bytes() == previous_contents
        assert list(tmp_path.glob(".identity.json.*.tmp")) == []

    def test_identity_repr_str_and_logging_do_not_expose_private_keys(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Normal identity representations and logging omit private key bytes."""
        import logging

        from bitchat.crypto.identity import LocalIdentity

        identity = LocalIdentity.generate()
        private_values = (
            identity.x25519_private.hex(),
            identity.ed25519_private.hex(),
        )
        with caplog.at_level(logging.INFO):
            logging.getLogger("bitchat.storage.test").info(
                "identity=%s repr=%r", identity, identity
            )

        for private_value in private_values:
            assert private_value not in repr(identity)
            assert private_value not in str(identity)
            assert private_value not in caplog.text
        assert "x25519_private" not in caplog.text
        assert "ed25519_private" not in caplog.text

    @pytest.mark.skipif(os.name != "nt", reason="Windows ACLs are only available there")
    def test_windows_identity_acl_is_current_user_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Windows ACL protection is applied to the empty temp file before writing."""
        from bitchat.crypto.identity import LocalIdentity

        original_restrict = storage_module._restrict_windows_file_acl

        def verify_empty_then_restrict(path: Path) -> None:
            assert path.stat().st_size == 0
            original_restrict(path)

        monkeypatch.setattr(
            storage_module, "_restrict_windows_file_acl", verify_empty_then_restrict
        )
        id_file = tmp_path / "identity.json"
        identity = LocalIdentity.generate()
        FileConfigStorage(identity_path=id_file).save_identity(identity)

        def assert_current_user_acl(path: Path) -> None:
            result = subprocess.run(
                ["icacls", str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            acl_entries = [
                line.strip()
                for line in result.stdout.splitlines()
                if ":(" in line and ")" in line
            ]
            assert len(acl_entries) == 1
            assert getpass.getuser().casefold() in acl_entries[0].casefold()
            assert ":(F)" in acl_entries[0]
            assert "(I)" not in acl_entries[0]

        assert_current_user_acl(id_file)

        legacy_file = tmp_path / "legacy_identity.json"
        legacy_file.write_text(
            json.dumps(
                {
                    "x25519_private": identity.x25519_private.hex(),
                    "ed25519_private": identity.ed25519_private.hex(),
                    "fingerprint": identity.fingerprint,
                    "peer_id": identity.peer_id.hex(),
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            storage_module, "_restrict_windows_file_acl", original_restrict
        )
        loaded = FileConfigStorage(identity_path=legacy_file).load_identity()
        assert loaded is not None
        assert loaded.peer_id == identity.peer_id
        assert_current_user_acl(legacy_file)

    @pytest.mark.skipif(os.name != "nt", reason="Windows ACLs are only available there")
    def test_windows_acl_failure_preserves_identity_and_cleans_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An ACL failure aborts persistence without leaving private-key data."""
        from bitchat.crypto.identity import LocalIdentity

        id_file = tmp_path / "identity.json"
        storage = FileConfigStorage(identity_path=id_file)
        storage.save_identity(LocalIdentity.generate())
        previous_contents = id_file.read_bytes()

        def fail_acl(_path: Path) -> None:
            raise OSError("simulated ACL failure")

        monkeypatch.setattr(storage_module, "_restrict_windows_file_acl", fail_acl)
        with pytest.raises(ConfigurationError, match="simulated ACL failure"):
            storage.save_identity(LocalIdentity.generate())

        assert id_file.read_bytes() == previous_contents
        assert list(tmp_path.glob(".identity.json.*.tmp")) == []

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

    def test_keybinding_defaults_and_validation(self) -> None:
        """AppConfig initializes with default keybindings and validates entries."""
        config = AppConfig()
        assert config.keybindings["help"] == "f1"
        assert config.keybindings["edit_theme"] == "f2"
        assert config.keybindings["settings"] == "f3"
        assert config.keybindings["clear_chat"] == "ctrl+l"
        assert config.keybindings["quit"] == "ctrl+q"
        assert config.keybindings["scroll_up"] == "pageup"
        assert config.keybindings["scroll_down"] == "pagedown"

    def test_keybinding_defensive_parsing_and_conflict_resolution(self) -> None:
        """Malicious/corrupt keybinding data safely falls back to defaults."""
        from bitchat.storage.config import DEFAULT_KEYBINDINGS

        # 1. keybindings is null or invalid type
        assert (
            AppConfig.from_dict({"keybindings": None}).keybindings
            == DEFAULT_KEYBINDINGS
        )
        assert (
            AppConfig.from_dict({"keybindings": "invalid"}).keybindings
            == DEFAULT_KEYBINDINGS
        )
        assert (
            AppConfig.from_dict({"keybindings": 12345}).keybindings
            == DEFAULT_KEYBINDINGS
        )

        # 2. non-string value for an action
        bad_val = AppConfig.from_dict({"keybindings": {"help": 123456}})
        assert bad_val.keybindings["help"] == "f1"

        # 3. unknown action in mapping is safely ignored
        unknown = AppConfig.from_dict(
            {"keybindings": {"unknown_action": "f1", "help": "f4"}}
        )
        assert "unknown_action" not in unknown.keybindings
        assert unknown.keybindings["help"] == "f4"

        # 4. conflicting keys (same key for two actions) fall back to default
        conflict = AppConfig.from_dict(
            {"keybindings": {"help": "f1", "settings": "f1"}}
        )
        assert conflict.keybindings["help"] == "f1"
        # settings conflicts with help, so settings falls back to default f3
        assert conflict.keybindings["settings"] == "f3"

    def test_defensive_boolean_parsing(self) -> None:
        """String boolean representations do not evaluate unsafely."""
        assert (
            AppConfig.from_dict({"show_timestamps": "false"}).show_timestamps is False
        )
        assert AppConfig.from_dict({"show_timestamps": "0"}).show_timestamps is False
        assert AppConfig.from_dict({"show_timestamps": "no"}).show_timestamps is False
        assert AppConfig.from_dict({"show_timestamps": "off"}).show_timestamps is False
        assert AppConfig.from_dict({"show_timestamps": "true"}).show_timestamps is True
        assert AppConfig.from_dict({"show_timestamps": "1"}).show_timestamps is True
        assert AppConfig.from_dict({"debug": "yes"}).debug is True

    def test_file_storage_atomic_write_guarantee(self, tmp_path: Path) -> None:
        """Atomic write ensures files are replaced without temp artifacts."""
        cfg_file = tmp_path / "atomic_config.json"
        storage = FileConfigStorage(config_path=cfg_file)

        config = AppConfig(nickname="AtomicNode")
        storage.save_config(config)

        assert cfg_file.exists()
        # Verify no stray .tmp files left in the directory
        tmp_files = list(tmp_path.glob("*.tmp*"))
        assert len(tmp_files) == 0
