import contextlib
import ctypes
import json
import os
import tempfile
from abc import ABC, abstractmethod
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import ConfigurationError

VALID_DENSITIES: frozenset[str] = frozenset({"comfortable", "compact"})
VALID_ACCENTS: frozenset[str] = frozenset({"blue", "cyan", "emerald", "purple"})
VALID_TRANSPORTS: frozenset[str] = frozenset({"bluetooth", "lan"})

DEFAULT_KEYBINDINGS: dict[str, str] = {
    "help": "f1",
    "edit_theme": "f2",
    "settings": "f3",
    "clear_chat": "ctrl+l",
    "quit": "ctrl+q",
    "scroll_up": "pageup",
    "scroll_down": "pagedown",
}
KEYBINDING_ACTIONS: frozenset[str] = frozenset(DEFAULT_KEYBINDINGS.keys())


def _parse_bool(val: Any, default: bool) -> bool:
    """Defensively parse a boolean value without unsafe casting."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off"):
            return False
    return default


def _validate_and_normalize_keybindings(kb: Any) -> dict[str, str]:
    """Validate, normalize, and resolve keybindings against defaults and conflicts."""
    if not isinstance(kb, dict):
        return DEFAULT_KEYBINDINGS.copy()

    cleaned: dict[str, str] = {}
    used_keys: dict[str, str] = {}

    for action in DEFAULT_KEYBINDINGS:
        raw_key = kb.get(action)
        if not isinstance(raw_key, str) or not raw_key.strip():
            cleaned[action] = DEFAULT_KEYBINDINGS[action]
        else:
            k = raw_key.strip().lower()
            if k in used_keys:
                # Key conflict between actions - fall back to default
                cleaned[action] = DEFAULT_KEYBINDINGS[action]
            else:
                cleaned[action] = k
        used_keys[cleaned[action]] = action

    return cleaned


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
    transport: str = "bluetooth"
    max_hops: int = 3
    inter_fragment_delay_ms: int = 20
    keybindings: dict[str, str] = field(
        default_factory=lambda: DEFAULT_KEYBINDINGS.copy()
    )

    def __post_init__(self) -> None:
        if self.density not in VALID_DENSITIES:
            self.density = "comfortable"
        if self.accent not in VALID_ACCENTS:
            self.accent = "blue"
        if self.transport not in VALID_TRANSPORTS:
            self.transport = "bluetooth"
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
        self.show_timestamps = _parse_bool(self.show_timestamps, True)
        self.debug = _parse_bool(self.debug, False)
        self.keybindings = _validate_and_normalize_keybindings(self.keybindings)

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
        debug = _parse_bool(data.get("debug"), False)

        density_val = data.get("density")
        density = (
            str(density_val).lower() if isinstance(density_val, str) else "comfortable"
        )
        if density not in VALID_DENSITIES:
            density = "comfortable"

        show_timestamps = _parse_bool(data.get("show_timestamps"), True)

        accent_val = data.get("accent")
        accent = str(accent_val).lower() if isinstance(accent_val, str) else "blue"
        if accent not in VALID_ACCENTS:
            accent = "blue"

        transport_val = data.get("transport")
        transport = (
            str(transport_val).lower()
            if isinstance(transport_val, str)
            else "bluetooth"
        )
        if transport not in VALID_TRANSPORTS:
            transport = "bluetooth"

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

        keybindings = _validate_and_normalize_keybindings(data.get("keybindings"))

        return cls(
            nickname=nickname,
            debug=debug,
            density=density,
            show_timestamps=show_timestamps,
            accent=accent,
            transport=transport,
            max_hops=max_hops,
            inter_fragment_delay_ms=inter_fragment_delay_ms,
            keybindings=keybindings,
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


def _atomic_write_json(
    target_path: Path,
    data: dict[str, Any],
    chmod_mode: int | None = None,
    restrict_to_current_user: bool = False,
) -> None:
    """Persist JSON atomically, applying requested permissions before writing."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=target_path.parent,
    )
    temp_file = Path(temp_name)
    try:
        if chmod_mode is not None and os.name == "posix":
            os.fchmod(fd, chmod_mode)
        if restrict_to_current_user and os.name == "nt":
            _restrict_windows_file_acl(temp_file)

        file_obj = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        with file_obj as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temp_file.replace(target_path)
    finally:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            temp_file.unlink()


def _restrict_windows_file_acl(path: Path) -> None:
    """Set a protected DACL granting full access only to the current user."""
    if os.name != "nt":
        raise OSError("Windows ACL protection is available only on Windows")

    token_query = 0x0008
    token_user_information = 1
    acl_revision = 2
    file_all_access = 0x001F01FF
    security_information = 0x00000001 | 0x00000004 | 0x80000000

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", wintypes.LPVOID), ("attributes", wintypes.DWORD)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = [wintypes.LPVOID]
    advapi32.GetLengthSid.restype = wintypes.DWORD
    advapi32.CopySid.argtypes = [
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    advapi32.CopySid.restype = wintypes.BOOL
    advapi32.InitializeAcl.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    advapi32.InitializeAcl.restype = wintypes.BOOL
    advapi32.AddAccessAllowedAceEx.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    advapi32.AddAccessAllowedAceEx.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        required_size = wintypes.DWORD()
        if advapi32.GetTokenInformation(
            token,
            token_user_information,
            None,
            0,
            ctypes.byref(required_size),
        ):
            raise OSError("Windows returned an empty token-user buffer size")
        if not required_size.value:
            raise ctypes.WinError(ctypes.get_last_error())
        user_buffer = ctypes.create_string_buffer(required_size.value)
        if not advapi32.GetTokenInformation(
            token,
            token_user_information,
            user_buffer,
            required_size,
            ctypes.byref(required_size),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        token_user = ctypes.cast(user_buffer, ctypes.POINTER(SidAndAttributes)).contents
        sid_size = advapi32.GetLengthSid(token_user.sid)
        if not sid_size:
            raise ctypes.WinError(ctypes.get_last_error())
        sid_buffer = ctypes.create_string_buffer(sid_size)
        if not advapi32.CopySid(sid_size, sid_buffer, token_user.sid):
            raise ctypes.WinError(ctypes.get_last_error())

        acl_size = 16 + sid_size
        acl_buffer = ctypes.create_string_buffer(acl_size)
        if not advapi32.InitializeAcl(acl_buffer, acl_size, acl_revision):
            raise ctypes.WinError(ctypes.get_last_error())
        if not advapi32.AddAccessAllowedAceEx(
            acl_buffer, acl_revision, 0, file_all_access, sid_buffer
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        result = advapi32.SetNamedSecurityInfoW(
            str(path),
            1,
            security_information,
            sid_buffer,
            None,
            acl_buffer,
            None,
        )
        if result:
            raise ctypes.WinError(result)
    finally:
        if not kernel32.CloseHandle(token):
            raise ctypes.WinError(ctypes.get_last_error())


def _restrict_existing_identity_file(path: Path) -> None:
    """Tighten access to legacy identity files before reading private keys."""
    if os.name == "posix":
        os.chmod(path, 0o600)
    elif os.name == "nt":
        _restrict_windows_file_acl(path)


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
            _atomic_write_json(self.config_path, config.to_dict())
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
            _restrict_existing_identity_file(self.identity_path)
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
            payload = {
                "x25519_private": identity.x25519_private.hex(),
                "ed25519_private": identity.ed25519_private.hex(),
                "fingerprint": identity.fingerprint,
                "peer_id": identity.peer_id.hex(),
            }
            _atomic_write_json(
                self.identity_path,
                payload,
                chmod_mode=0o600,
                restrict_to_current_user=True,
            )
        except OSError as e:
            raise ConfigurationError(
                f"Failed to write identity to {self.identity_path}: {e}"
            ) from e

    def close(self) -> None:
        self._is_closed = True
