"""Storage abstraction and configuration management."""

import json
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import ConfigurationError


@dataclass
class AppConfig:
    """Application configuration.

    Stores minimal non-sensitive configuration settings. Passwords and sensitive
    credentials must never be stored here in plaintext.
    """

    nickname: str = "Anonymous"
    debug: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        """Instantiate configuration from a dictionary."""
        return cls(
            nickname=str(data.get("nickname", "Anonymous")),
            debug=bool(data.get("debug", False)),
        )


class StorageInterface(ABC):
    """Abstract interface defining storage operations.

    Establishes a clean architectural boundary between the application core
    and underlying persistence mechanisms (e.g. JSON files, SQLite).
    """

    @abstractmethod
    def load_config(self) -> AppConfig:
        """Load application configuration."""

    @abstractmethod
    def save_config(self, config: AppConfig) -> None:
        """Save application configuration."""

    @abstractmethod
    def load_identity(self) -> LocalIdentity | None:
        """Load stored local cryptographic identity, or None if not found."""

    @abstractmethod
    def save_identity(self, identity: LocalIdentity) -> None:
        """Persist local cryptographic identity securely."""

    @abstractmethod
    def close(self) -> None:
        """Release any held storage resources."""


class InMemoryStorage(StorageInterface):
    """In-memory storage implementation for tests and ephemeral sessions."""

    def __init__(
        self,
        initial_config: AppConfig | None = None,
        initial_identity: LocalIdentity | None = None,
    ) -> None:
        self._config = initial_config or AppConfig()
        self._identity: LocalIdentity | None = initial_identity
        self._is_closed = False

    def load_config(self) -> AppConfig:
        if self._is_closed:
            raise ConfigurationError("Cannot load configuration from closed storage.")
        return self._config

    def save_config(self, config: AppConfig) -> None:
        if self._is_closed:
            raise ConfigurationError("Cannot save configuration to closed storage.")
        self._config = config

    def load_identity(self) -> LocalIdentity | None:
        if self._is_closed:
            raise ConfigurationError("Cannot load identity from closed storage.")
        return self._identity

    def save_identity(self, identity: LocalIdentity) -> None:
        if self._is_closed:
            raise ConfigurationError("Cannot save identity to closed storage.")
        self._identity = identity

    def close(self) -> None:
        self._is_closed = True


class FileConfigStorage(StorageInterface):
    """File-based JSON configuration and identity storage."""

    def __init__(
        self,
        config_path: Path | str | None = None,
        identity_path: Path | str | None = None,
    ) -> None:
        if config_path is None:
            self.config_path = Path.home() / ".bitchat" / "config.json"
        else:
            self.config_path = Path(config_path)

        if identity_path is None:
            self.identity_path = self.config_path.parent / "identity.json"
        else:
            self.identity_path = Path(identity_path)

        self._is_closed = False

    def load_config(self) -> AppConfig:
        if self._is_closed:
            raise ConfigurationError("Cannot load configuration from closed storage.")
        if not self.config_path.exists():
            return AppConfig()
        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ConfigurationError(
                    f"Invalid configuration file format: {self.config_path}"
                )
            return AppConfig.from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            raise ConfigurationError(
                f"Failed to read configuration from {self.config_path}: {e}"
            ) from e

    def save_config(self, config: AppConfig) -> None:
        if self._is_closed:
            raise ConfigurationError("Cannot save configuration to closed storage.")
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, indent=2)
        except OSError as e:
            raise ConfigurationError(
                f"Failed to write configuration to {self.config_path}: {e}"
            ) from e

    def load_identity(self) -> LocalIdentity | None:
        if self._is_closed:
            raise ConfigurationError("Cannot load identity from closed storage.")
        if not self.identity_path.exists():
            return None
        try:
            with open(self.identity_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ConfigurationError(
                    f"Invalid identity file format: {self.identity_path}"
                )
            x25519_hex = data.get("x25519_private")
            ed25519_hex = data.get("ed25519_private")
            if not isinstance(x25519_hex, str) or not isinstance(ed25519_hex, str):
                raise ConfigurationError("Missing private keys in identity file.")
            x25519_priv = bytes.fromhex(x25519_hex)
            ed25519_priv = bytes.fromhex(ed25519_hex)
            return LocalIdentity.from_x25519_private(x25519_priv, ed25519_priv)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            raise ConfigurationError(
                f"Failed to read identity from {self.identity_path}: {e}"
            ) from e

    def save_identity(self, identity: LocalIdentity) -> None:
        if self._is_closed:
            raise ConfigurationError("Cannot save identity to closed storage.")
        try:
            self.identity_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "x25519_private": identity.x25519_private.hex(),
                "ed25519_private": identity.ed25519_private.hex(),
                "fingerprint": identity.fingerprint,
                "peer_id": identity.peer_id.hex(),
            }
            with open(self.identity_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            # Restrict permissions on POSIX
            if os.name == "posix":
                os.chmod(self.identity_path, 0o600)
        except OSError as e:
            raise ConfigurationError(
                f"Failed to write identity to {self.identity_path}: {e}"
            ) from e

    def close(self) -> None:
        self._is_closed = True
