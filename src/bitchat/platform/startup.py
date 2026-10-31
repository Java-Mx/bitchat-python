"""Per-user Windows startup integration and single-instance execution guard.

Provides non-administrative per-user startup shortcut registration in the Windows
Startup folder (%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup)
and a per-user named mutex so duplicate BitChat instances are not launched at sign-in.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType

STARTUP_SHORTCUT_NAME = "BitChat.lnk"
APP_MUTEX_NAME = "Local\\BitChatAppRunningMutex"
APP_REG_KEY = r"Software\Java-Mx\BitChat"
ERROR_ALREADY_EXISTS = 183


def get_startup_dir() -> Path:
    """Return the per-user Windows Startup folder path.

    Honors BITCHAT_STARTUP_DIR if set (used for isolated testing).
    """
    override = os.environ.get("BITCHAT_STARTUP_DIR")
    if override:
        return Path(override)

    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"

    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def get_startup_shortcut_path(startup_dir: Path | None = None) -> Path:
    """Return the full path to the per-user BitChat Startup shortcut (.lnk)."""
    target_dir = startup_dir if startup_dir is not None else get_startup_dir()
    return target_dir / STARTUP_SHORTCUT_NAME


def is_startup_enabled(startup_dir: Path | None = None) -> bool:
    """Return True if the per-user BitChat startup shortcut is currently registered."""
    return get_startup_shortcut_path(startup_dir).is_file()


def resolve_executable_path(executable_path: Path | None = None) -> Path:
    """Determine the target BitChat executable path for startup registration."""
    if executable_path is not None:
        return executable_path.resolve()

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()

    which_bitchat = shutil.which("bitchat")
    if which_bitchat:
        return Path(which_bitchat).resolve()

    return Path(sys.executable).resolve()


def enable_startup(
    executable_path: Path | None = None,
    startup_dir: Path | None = None,
    arguments: str = "--startup-launch",
) -> Path:
    """Create or update the per-user Windows startup shortcut for BitChat.

    Launches after the user signs in to Windows (not before login as a service)
    and does not require administrator privileges.
    """
    shortcut_path = get_startup_shortcut_path(startup_dir)
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    target_exe = resolve_executable_path(executable_path)
    working_dir = target_exe.parent

    if sys.platform == "win32":
        bundled_ico = working_dir / "assets" / "bitchat.ico"
        icon_loc = str(bundled_ico) if bundled_ico.is_file() else f"{target_exe},0"
        ps_script = (
            "$ws = New-Object -ComObject WScript.Shell; "
            "$sc = $ws.CreateShortcut($env:BITCHAT_LNK_PATH); "
            "$sc.TargetPath = $env:BITCHAT_TARGET_EXE; "
            "$sc.Arguments = $env:BITCHAT_ARGS; "
            "$sc.WorkingDirectory = $env:BITCHAT_WORKDIR; "
            "$sc.IconLocation = $env:BITCHAT_ICON_LOC; "
            "$sc.Description = 'Start BitChat after Windows user sign-in'; "
            "$sc.Save()"
        )
        env = os.environ.copy()
        env["BITCHAT_LNK_PATH"] = str(shortcut_path)
        env["BITCHAT_TARGET_EXE"] = str(target_exe)
        env["BITCHAT_ARGS"] = arguments
        env["BITCHAT_WORKDIR"] = str(working_dir)
        env["BITCHAT_ICON_LOC"] = icon_loc

        pwsh = shutil.which("powershell") or shutil.which("pwsh")
        if pwsh:
            res = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps_script,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if res.returncode == 0 and shortcut_path.is_file():
                _sync_registry_startup_flag(startup_dir, enabled=True)
                return shortcut_path

    # Fallback deterministic shortcut descriptor if COM/PowerShell is unavailable
    fallback_content = (
        f"[InternetShortcut]\n"
        f"TargetPath={target_exe}\n"
        f"Arguments={arguments}\n"
        f"WorkingDirectory={working_dir}\n"
    )
    shortcut_path.write_text(fallback_content, encoding="utf-8")
    _sync_registry_startup_flag(startup_dir, enabled=True)
    return shortcut_path


def _sync_registry_startup_flag(startup_dir: Path | None, *, enabled: bool) -> None:
    """Keep HKCU\\Software\\Java-Mx\\BitChat StartupEnabled in sync on Windows."""
    if (
        sys.platform != "win32"
        or startup_dir is not None
        or os.environ.get("BITCHAT_STARTUP_DIR")
    ):
        return
    with contextlib.suppress(Exception):
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            APP_REG_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key, "StartupEnabled", 0, winreg.REG_DWORD, 1 if enabled else 0
            )


def disable_startup(startup_dir: Path | None = None) -> bool:
    """Remove the per-user BitChat startup shortcut if present.

    Returns True if a shortcut was removed, or False if startup was already disabled.
    """
    shortcut_path = get_startup_shortcut_path(startup_dir)
    if shortcut_path.exists():
        shortcut_path.unlink()
        _sync_registry_startup_flag(startup_dir, enabled=False)
        return True
    _sync_registry_startup_flag(startup_dir, enabled=False)
    return False


def format_startup_status(startup_dir: Path | None = None) -> str:
    """Return a human-readable summary of the per-user Windows startup state."""
    shortcut_path = get_startup_shortcut_path(startup_dir)
    enabled = shortcut_path.is_file()
    state_str = "Enabled (launches after user sign-in)" if enabled else "Disabled"
    return (
        f"BitChat Windows Startup Status: {state_str}\n"
        f"  Scope:         Current User (no administrator privileges required)\n"
        f"  Shortcut Path: {shortcut_path}"
    )


class SingleInstanceGuard:
    """Per-user Windows named mutex guard preventing duplicate startup instances."""

    def __init__(self, mutex_name: str = APP_MUTEX_NAME) -> None:
        self.mutex_name = mutex_name
        self._handle: int | None = None
        self.already_running: bool = False

    def acquire(self) -> bool:
        """Acquire the per-user named mutex.

        Returns True if this process is the primary instance, or False if another
        instance already holds the mutex.
        """
        if sys.platform != "win32":
            self.already_running = False
            return True

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_bool,
                ctypes.c_wchar_p,
            ]
            kernel32.CreateMutexW.restype = ctypes.c_void_p

            ctypes.set_last_error(0)
            handle = kernel32.CreateMutexW(None, False, self.mutex_name)
            last_err = ctypes.get_last_error()
            if handle:
                self._handle = int(handle)
                self.already_running = last_err == ERROR_ALREADY_EXISTS
                return not self.already_running
        except Exception:
            self.already_running = False
        return True

    def release(self) -> None:
        """Close the mutex handle when the process exits."""
        if self._handle is not None and sys.platform == "win32":
            with contextlib.suppress(Exception):
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
                kernel32.CloseHandle.restype = ctypes.c_bool
                kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None
            self.already_running = False

    def __enter__(self) -> SingleInstanceGuard:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.release()
