"""Storage abstraction and configuration management."""

import json
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import ConfigurationError

VALID_DENSITIES: frozenset[str] = frozenset({"comfortable", "compact"})
VALID_ACCENTS: frozenset[str] = frozenset({"blue", "cyan", "emerald", "purple"})


@dataclass
class AppConfig:
    """Application configuration.

    Stores non-sensitive configuration and appearance settings. Passwords and sensitive
    credentials must never be stored here in plaintext.
    """

    nickname: str = "Anonymous"
    debug: bool = False
    density: str = "comfortable"
    show_timestamps: bool = True
    accent: str = "blue"
    max_hops: int = 3
    inter_fragment_delay_ms: int = 20

    def __post_init__(self) -> None:
        if self.density not in VALID_DENSITIES:
            self.density = "comfortable"
        if self.accent not in VALID_ACCENTS:
            self.accent = "blue"
        try:
            self.max_hops = max(1, min(7, int(self.max_hops)))
        except (ValueError, TypeError):
            self.max_hops = 3
        try:
            self.inter_fragment_delay_ms = max(
                5, min(500, int(self.inter_fragment_delay_ms))
            )
        except (ValueError, TypeError):
            self.inter_fragment_delay_ms = 20
        if not isinstance(self.nickname, str) or not self.nickname.strip():
            self.nickname = "Anonymous"
        else:
            self.nickname = self.nickname.strip()[:32]
        self.show_timestamps = bool(self.show_timestamps)
        self.debug = bool(self.debug)

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        """Instantiate configuration from a dictionary with defensive validation."""
        if not isinstance(data, dict):
            return cls()

        nick_val = data.get("nickname")
        nickname = (
            str(nick_val).strip()[:32]
            if isinstance(nick_val, str) and nick_val.strip()
            else "Anonymous"
        )
        debug = bool(data.get("debug", False))

        density_val = data.get("density")
        density = (
            str(density_val).lower() if isinstance(density_val, str) else "comfortable"
        )
        if density not in VALID_DENSITIES:
            density = "comfortable"

        show_ts_val = data.get("show_timestamps")
        show_timestamps = bool(show_ts_val) if show_ts_val is not None else True

        accent_val = data.get("accent")
        accent = str(accent_val).lower() if isinstance(accent_val, str) else "blue"
        if accent not in VALID_ACCENTS:
            accent = "blue"

        try:
            hops = int(data.get("max_hops", 3))
            max_hops = max(1, min(7, hops))
        except (ValueError, TypeError):
            max_hops = 3

        try:
            delay = int(data.get("inter_fragment_delay_ms", 20))
            inter_fragment_delay_ms = max(5, min(500, delay))
        except (ValueError, TypeError):
            inter_fragment_delay_ms = 20

        return cls(
            nickname=nickname,
            debug=debug,
            density=density,
            show_timestamps=show_timestamps,
            accent=accent,
            max_hops=max_hops,
            inter_fragment_delay_ms=inter_fragment_delay_ms,
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
