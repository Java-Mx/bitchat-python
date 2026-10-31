import contextlib
import ctypes
import json
import os
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import ConfigurationError, InvalidKeyError

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
    contacts: dict[str, str] = field(default_factory=dict)

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
        if not isinstance(self.contacts, dict):
            self.contacts = {}
        else:
            self.contacts = {
                str(k).strip().lower(): str(v).strip().lower()
                for k, v in self.contacts.items()
                if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()
            }

    def verify_contact(self, peer_id: str, fingerprint: str) -> bool:
        """Verify peer fingerprint using Trust-On-First-Use (TOFU).

        If peer_id is not yet in contacts, trust on first use and record fingerprint.
        If peer_id is already in contacts, verify that the fingerprint matches.

        Args:
            peer_id: Hex string of the remote peer ID.
            fingerprint: Hex string of the peer's public key fingerprint.

        Returns:
            True if verification succeeds (first use or matching fingerprint),
            False if there is a fingerprint mismatch (spoofing/MITM).
        """
        if not peer_id or not fingerprint:
            return False
        clean_pid = str(peer_id).strip().lower()
        clean_fp = str(fingerprint).strip().lower()
        stored = self.contacts.get(clean_pid)
        if stored is None:
            self.contacts[clean_pid] = clean_fp
            return True
        return stored.lower() == clean_fp

    def get_contact_fingerprint(self, peer_id: str) -> str | None:
        """Return the stored fingerprint for a contact, or None."""
        return self.contacts.get(str(peer_id).strip().lower())

    def add_contact(self, peer_id: str, fingerprint: str) -> None:
        """Add or update a trusted contact's fingerprint."""
        self.contacts[str(peer_id).strip().lower()] = str(fingerprint).strip().lower()

    def remove_contact(self, peer_id: str) -> bool:
        """Remove a contact from the trusted contacts store."""
        return self.contacts.pop(str(peer_id).strip().lower(), None) is not None

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

        contacts: dict[str, str] = {}
        raw_contacts = data.get("contacts")
        if isinstance(raw_contacts, dict):
            for k, v in raw_contacts.items():
                if isinstance(v, str) and k and v:
                    contacts[str(k).strip().lower()] = str(v).strip().lower()
                elif isinstance(v, dict) and "fingerprint" in v:
                    fp = v["fingerprint"]
                    if isinstance(fp, str) and k and fp:
                        contacts[str(k).strip().lower()] = str(fp).strip().lower()

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
            contacts=contacts,
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
    def load_or_create_identity(self) -> LocalIdentity:
        """Load stored identity or atomically generate, persist, and return new one."""

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

    def load_or_create_identity(self) -> LocalIdentity:
        if self._is_closed:
            raise ConfigurationError("Cannot load identity from closed storage.")
        if self._identity is None:
            self._identity = LocalIdentity.generate()
        return self._identity

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


@contextlib.contextmanager
def _interprocess_lock(lock_path: Path, timeout: float = 10.0):
    """Cross-platform advisory file lock using msvcrt on Windows and fcntl on POSIX."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        start_time = time.time()
        locked = False
        if os.name == "nt":
            import msvcrt

            while not locked:
                try:
                    if os.fstat(lock_fd).st_size == 0:
                        os.write(lock_fd, b"\0")
                    os.lseek(lock_fd, 0, os.SEEK_SET)
                    msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                    locked = True
                except (OSError, PermissionError) as err:
                    if time.time() - start_time >= timeout:
                        raise TimeoutError(
                            f"Timed out acquiring interprocess lock on {lock_path}"
                        ) from err
                    time.sleep(0.02)
        else:
            import fcntl

            while not locked:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except (OSError, BlockingIOError) as err:
                    if time.time() - start_time >= timeout:
                        raise TimeoutError(
                            f"Timed out acquiring interprocess lock on {lock_path}"
                        ) from err
                    time.sleep(0.02)
        try:
            yield
        finally:
            if locked:
                if os.name == "nt":
                    import msvcrt

                    with contextlib.suppress(Exception):
                        os.lseek(lock_fd, 0, os.SEEK_SET)
                        msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    with contextlib.suppress(Exception):
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        with contextlib.suppress(Exception):
            os.close(lock_fd)


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

        self.identity_lock_path = self.identity_path.with_name(
            f"{self.identity_path.name}.lock"
        )
        self._is_closed = False
        self._write_lock = threading.Lock()

    def _create_corrupt_identity_backup(self) -> Path | None:
        """Create a backup of corrupted identity.json with timestamp suffix."""
        if not self.identity_path.exists():
            return None
        try:
            timestamp = int(time.time())
            backup_name = f"{self.identity_path.name}.corrupt.{timestamp}"
            backup_path = self.identity_path.parent / backup_name
            if backup_path.exists():
                timestamp = int(time.time() * 1000)
                backup_name = f"{self.identity_path.name}.corrupt.{timestamp}"
                backup_path = self.identity_path.parent / backup_name
            backup_path.write_bytes(self.identity_path.read_bytes())
            return backup_path
        except OSError:
            return None

    def _is_identity_corrupted(self) -> bool:
        """Check if existing identity.json is present and corrupted."""
        if not self.identity_path.exists():
            return False
        try:
            with open(self.identity_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return True
            x25519_hex = data.get("x25519_private")
            ed25519_hex = data.get("ed25519_private")
            if not isinstance(x25519_hex, str) or not isinstance(ed25519_hex, str):
                return True
            x25519_priv = bytes.fromhex(x25519_hex)
            ed25519_priv = bytes.fromhex(ed25519_hex)
            LocalIdentity.from_x25519_private(x25519_priv, ed25519_priv)
            return False
        except Exception:
            return True

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

    def _load_identity_unlocked(self) -> LocalIdentity | None:
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
        except (json.JSONDecodeError, ValueError, InvalidKeyError) as e:
            self._create_corrupt_identity_backup()
            raise ConfigurationError(
                f"Failed to read identity from {self.identity_path}: {e}"
            ) from e
        except ConfigurationError:
            self._create_corrupt_identity_backup()
            raise
        except OSError as e:
            raise ConfigurationError(
                f"Failed to read identity from {self.identity_path}: {e}"
            ) from e

    def _save_identity_unlocked(self, identity: LocalIdentity) -> None:
        if self._is_identity_corrupted():
            self._create_corrupt_identity_backup()
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

    def load_identity(self) -> LocalIdentity | None:
        if self._is_closed:
            raise ConfigurationError("Cannot load identity from closed storage.")
        with self._write_lock, _interprocess_lock(self.identity_lock_path):
            return self._load_identity_unlocked()

    def save_identity(self, identity: LocalIdentity) -> None:
        if self._is_closed:
            raise ConfigurationError("Cannot save identity to closed storage.")
        with self._write_lock, _interprocess_lock(self.identity_lock_path):
            self._save_identity_unlocked(identity)

    def load_or_create_identity(self) -> LocalIdentity:
        """Load stored identity or atomically create, persist, and return new one.

        Uses cross-process file locking to prevent split-brain identity generation
        when multiple instances launch concurrently on a fresh installation.
        """
        if self._is_closed:
            raise ConfigurationError("Cannot load identity from closed storage.")
        with self._write_lock, _interprocess_lock(self.identity_lock_path):
            existing = self._load_identity_unlocked()
            if existing is not None:
                return existing
            new_identity = LocalIdentity.generate()
            self._save_identity_unlocked(new_identity)
            return new_identity

    def close(self) -> None:
        self._is_closed = True
