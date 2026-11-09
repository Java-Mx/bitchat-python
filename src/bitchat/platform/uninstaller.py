"""Comprehensive cross-platform uninstaller for BitChat (Windows & Linux).

Supports discovering and cleanly removing:
- Standalone Windows installations (Inno Setup / PyInstaller bundles, registry keys)
- Python pip / uv / pipx / wheel installations and console-script launchers
  (including ``Python3XX\\Scripts\\bitchat.exe`` across all discovered Python installs)
- Desktop shortcuts, Start Menu folders, and startup registrations
- BitChat-owned PATH entries (without corrupting or removing shared PATH directories)
- Optional complete removal of user data, identity keys, caches, and logs
"""

from __future__ import annotations

import contextlib
import ctypes
import glob
import os
import shutil
import subprocess
import sys
import sysconfig
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_DATA_DIR: Path = Path.home() / ".bitchat"

WINDOWS_APP_IDS: tuple[str, ...] = (
    "{B17CHA70-B1EC-4E87-99B7-4DA78D0B7001}",
    "{D3B7A8C1-9F42-4E6A-8B15-2C7E9A4D6F01}",
)
WINDOWS_UNINSTALL_REG_KEYS: tuple[str, ...] = tuple(
    f"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{app_id}_is1"
    for app_id in WINDOWS_APP_IDS
)
WINDOWS_APP_METADATA_REG_KEY = r"Software\Java-Mx\BitChat"
WINDOWS_RUN_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_USER_ENV_KEY = r"Environment"
WINDOWS_SYS_ENV_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"

LAUNCHER_FILENAMES_WINDOWS: tuple[str, ...] = (
    "bitchat.exe",
    "bitchat-script.py",
    "bitchat.cmd",
    "bitchat.bat",
    "bitchat.ps1",
)
LAUNCHER_FILENAMES_POSIX: tuple[str, ...] = ("bitchat",)


@dataclass
class DiscoveredInstallation:
    """Summary of all BitChat installation artifacts discovered on the host."""

    standalone_dirs: list[Path] = field(default_factory=list)
    launcher_files: list[Path] = field(default_factory=list)
    package_metadata_dirs: list[Path] = field(default_factory=list)
    package_module_paths: list[Path] = field(default_factory=list)
    shortcut_paths: list[Path] = field(default_factory=list)
    startup_entries: list[str] = field(default_factory=list)
    registry_keys: list[str] = field(default_factory=list)
    bitchat_path_entries: list[str] = field(default_factory=list)
    user_data_dirs: list[Path] = field(default_factory=list)

    @property
    def has_application_artifacts(self) -> bool:
        """Return True if any application binary, launcher, or registration exists."""
        return bool(
            self.standalone_dirs
            or self.launcher_files
            or self.package_metadata_dirs
            or self.package_module_paths
            or self.shortcut_paths
            or self.startup_entries
            or self.registry_keys
            or self.bitchat_path_entries
        )


@dataclass
class UninstallReport:
    """Structured result of an uninstallation or dry-run operation."""

    dry_run: bool = False
    remove_user_data: bool = False
    stopped_pids: list[int] = field(default_factory=list)
    removed_files: list[str] = field(default_factory=list)
    removed_dirs: list[str] = field(default_factory=list)
    removed_shortcuts: list[str] = field(default_factory=list)
    removed_registry_keys: list[str] = field(default_factory=list)
    removed_path_entries: list[str] = field(default_factory=list)
    removed_user_data: list[str] = field(default_factory=list)
    preserved_user_data: list[str] = field(default_factory=list)
    deferred_reboot_deletions: list[str] = field(default_factory=list)
    remaining_commands_on_path: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        """Return True if uninstall completed with no errors and no stale launchers."""
        return not self.errors and not self.remaining_commands_on_path


def _norm_win_path(p: str | Path) -> str:
    """Normalize a path for case-insensitive Windows comparison."""
    s = str(p).strip().strip('"')
    if not s:
        return ""
    s = os.path.expandvars(s).replace("/", "\\")
    while len(s) > 3 and s.endswith("\\"):
        s = s[:-1]
    return s.lower()


def _is_git_source_checkout(path: Path) -> bool:
    """Return True if ``path`` resides inside a developer Git/source checkout."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    for parent in (resolved, *resolved.parents):
        if (parent / ".git").exists() and (parent / "pyproject.toml").exists():
            return True
    return False


def _is_bitchat_owned_install_dir(path_str: str) -> bool:
    """Return True ONLY if ``path_str`` is a dedicated BitChat application directory.

    Shared directories such as ``Python314\\Scripts``, ``C:\\Windows\\System32``,
    ``/usr/local/bin``, or ``~/.local/bin`` MUST return False so they are never
    removed from ``PATH``.
    """
    norm = _norm_win_path(path_str)
    if not norm:
        return False
    parts = [seg for seg in norm.replace("/", "\\").split("\\") if seg]
    if not parts:
        return False
    leaf = parts[-1]
    # Dedicated BitChat install directory names:
    if leaf == "bitchat":
        # Exclude shared Python Scripts/site-packages or user data folders if needed,
        # though removing a PATH entry pointing directly to a bitchat folder is safe.
        return not ("site-packages" in parts or "dist-packages" in parts)
    return False


def _is_shared_scripts_or_system_dir(path: Path) -> bool:
    """Return True if ``path`` is a shared directory (like Python Scripts)."""
    norm = _norm_win_path(path)
    parts = [seg for seg in norm.split("\\") if seg]
    if not parts:
        return True
    leaf = parts[-1]
    if leaf in {
        "scripts",
        "bin",
        "system32",
        "windows",
        "program files",
        "program files (x86)",
        "programs",
    }:
        return True
    return not _is_bitchat_owned_install_dir(str(path))


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    """Deduplicate Path objects while preserving order."""
    seen: set[str] = set()
    result: list[Path] = []
    for p in paths:
        key = _norm_win_path(p) if sys.platform == "win32" else str(p)
        if key and key not in seen:
            seen.add(key)
            result.append(p)
    return result


def discover_python_scripts_dirs(
    extra_roots: list[Path] | None = None,
) -> list[Path]:
    """Locate all Python ``Scripts`` / ``bin`` directories on the system.

    Specifically scans:
    - Current Python interpreter's scripts dir (`sysconfig.get_path('scripts')`)
    - ``%LOCALAPPDATA%\\Programs\\Python\\Python*\\Scripts`` (e.g. Python314\\Scripts)
    - ``%APPDATA%\\Python\\Python*\\Scripts``
    - ``C:\\Python*\\Scripts`` and ``%ProgramFiles%\\Python*\\Scripts``
    - ``%USERPROFILE%\\.local\\bin`` and ``%LOCALAPPDATA%\\uv\\tools\\bitchat\\Scripts``
    - Directories currently listed in ``PATH``
    """
    candidates: list[Path] = []

    if extra_roots:
        candidates.extend(extra_roots)

    try:
        sc_scripts = sysconfig.get_path("scripts")
        if sc_scripts:
            candidates.append(Path(sc_scripts))
    except Exception:
        pass

    exe_dir = Path(sys.executable).parent
    candidates.append(exe_dir)
    candidates.append(exe_dir / "Scripts")
    candidates.append(exe_dir / "bin")

    home = Path.home()
    candidates.append(home / ".local" / "bin")

    if sys.platform == "win32":
        local_appdata = Path(
            os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        )
        appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        program_files_x86 = Path(
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        )

        # Standard per-user and system Python installations (Python312..Python314)
        glob_patterns = [
            str(local_appdata / "Programs" / "Python" / "Python*" / "Scripts"),
            str(appdata / "Python" / "Python*" / "Scripts"),
            str(program_files / "Python*" / "Scripts"),
            str(program_files_x86 / "Python*" / "Scripts"),
            r"C:\Python*\Scripts",
            str(local_appdata / "uv" / "tools" / "bitchat" / "Scripts"),
            str(appdata / "uv" / "tools" / "bitchat" / "Scripts"),
            str(home / ".local" / "pipx" / "venvs" / "bitchat" / "Scripts"),
            str(local_appdata / "pipx" / "pipx" / "venvs" / "bitchat" / "Scripts"),
        ]
        for pattern in glob_patterns:
            for matched in glob.glob(pattern):
                candidates.append(Path(matched))

        # Also inspect Windows Registry for installed Python Core InstallPaths
        try:
            import winreg

            for root_hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for reg_subkey in (
                    r"Software\Python\PythonCore",
                    r"Software\WOW6432Node\Python\PythonCore",
                ):
                    try:
                        with winreg.OpenKey(root_hive, reg_subkey) as core_key:
                            num_subkeys, _, _ = winreg.QueryInfoKey(core_key)
                            for i in range(num_subkeys):
                                ver_name = winreg.EnumKey(core_key, i)
                                try:
                                    with winreg.OpenKey(
                                        core_key, f"{ver_name}\\InstallPath"
                                    ) as ip_key:
                                        install_path, _ = winreg.QueryValueEx(
                                            ip_key, ""
                                        )
                                        if install_path:
                                            candidates.append(
                                                Path(str(install_path)) / "Scripts"
                                            )
                                except OSError:
                                    continue
                    except OSError:
                        continue
        except ImportError:
            pass
    else:
        candidates.extend(
            [
                Path("/usr/local/bin"),
                Path("/usr/bin"),
                home / ".local" / "share" / "uv" / "tools" / "bitchat" / "bin",
                home / ".local" / "pipx" / "venvs" / "bitchat" / "bin",
            ]
        )

    # Include directories from current PATH
    raw_path = os.environ.get("PATH", "")
    for entry in raw_path.split(os.pathsep):
        cleaned = entry.strip().strip('"')
        if cleaned:
            candidates.append(Path(cleaned))

    return _dedupe_paths([p for p in candidates if p.exists() and p.is_dir()])


def discover_site_packages_dirs(
    extra_roots: list[Path] | None = None,
) -> list[Path]:
    """Locate Python ``site-packages`` directories across Python installations."""
    candidates: list[Path] = []
    if extra_roots:
        candidates.extend(extra_roots)

    try:
        purelib = sysconfig.get_path("purelib")
        if purelib:
            candidates.append(Path(purelib))
        platlib = sysconfig.get_path("platlib")
        if platlib:
            candidates.append(Path(platlib))
    except Exception:
        pass

    home = Path.home()
    if sys.platform == "win32":
        local_appdata = Path(
            os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        )
        appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        for pattern in (
            str(
                local_appdata
                / "Programs"
                / "Python"
                / "Python*"
                / "Lib"
                / "site-packages"
            ),
            str(appdata / "Python" / "Python*" / "site-packages"),
            str(program_files / "Python*" / "Lib" / "site-packages"),
            r"C:\Python*\Lib\site-packages",
        ):
            for matched in glob.glob(pattern):
                candidates.append(Path(matched))
    else:
        for pattern in (
            str(home / ".local" / "lib" / "python*" / "site-packages"),
            "/usr/local/lib/python*/dist-packages",
            "/usr/local/lib/python*/site-packages",
        ):
            for matched in glob.glob(pattern):
                candidates.append(Path(matched))

    return _dedupe_paths([p for p in candidates if p.exists() and p.is_dir()])


def discover_installations(
    *,
    extra_scripts_dirs: list[Path] | None = None,
    extra_site_packages_dirs: list[Path] | None = None,
    extra_standalone_dirs: list[Path] | None = None,
    extra_user_data_dirs: list[Path] | None = None,
    include_system_paths: bool = True,
) -> DiscoveredInstallation:
    """Discover all BitChat installation artifacts on the machine."""
    info = DiscoveredInstallation()
    home = Path.home()

    # 1. Standalone installation directories
    standalone_candidates: list[Path] = []
    if extra_standalone_dirs:
        standalone_candidates.extend(extra_standalone_dirs)

    if include_system_paths:
        if sys.platform == "win32":
            local_appdata = Path(
                os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
            )
            program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            program_files_x86 = Path(
                os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
            )
            standalone_candidates.extend(
                [
                    local_appdata / "Programs" / "BitChat",
                    program_files / "BitChat",
                    program_files_x86 / "BitChat",
                ]
            )
            # Check Uninstall Registry and Java-Mx\BitChat metadata for InstallLocation
            try:
                import winreg

                for hive_name, hive in (
                    ("HKCU", winreg.HKEY_CURRENT_USER),
                    ("HKLM", winreg.HKEY_LOCAL_MACHINE),
                ):
                    for reg_subkey in (
                        *WINDOWS_UNINSTALL_REG_KEYS,
                        WINDOWS_APP_METADATA_REG_KEY,
                    ):
                        try:
                            with winreg.OpenKey(hive, reg_subkey) as ukey:
                                info.registry_keys.append(f"{hive_name}\\{reg_subkey}")
                                for val_name in (
                                    "InstallLocation",
                                    "Inno Setup: App Path",
                                    "PathAddedByInstaller",
                                ):
                                    try:
                                        loc, _ = winreg.QueryValueEx(ukey, val_name)
                                        if loc:
                                            standalone_candidates.append(
                                                Path(str(loc).strip('"'))
                                            )
                                    except OSError:
                                        pass
                        except OSError:
                            pass
            except ImportError:
                pass
        else:
            standalone_candidates.append(Path("/opt/bitchat"))

    for cand in _dedupe_paths(standalone_candidates):
        if cand.exists() and cand.is_dir() and not _is_git_source_checkout(cand):
            info.standalone_dirs.append(cand)

    # 2. Console-script launchers (e.g. Python314\Scripts\bitchat.exe)
    scripts_dirs = (
        discover_python_scripts_dirs(extra_scripts_dirs)
        if include_system_paths
        else _dedupe_paths(extra_scripts_dirs or [])
    )
    launcher_names = (
        LAUNCHER_FILENAMES_WINDOWS
        if sys.platform == "win32"
        else LAUNCHER_FILENAMES_POSIX
    )
    launcher_candidates: list[Path] = []
    for sdir in scripts_dirs:
        if not sdir.exists():
            continue
        # Skip launchers inside a standalone dir (already covered by standalone_dirs)
        if any(
            _norm_win_path(sdir) == _norm_win_path(sd) for sd in info.standalone_dirs
        ):
            continue
        # Never touch files inside a git checkout unless inside its .venv
        if _is_git_source_checkout(sdir) and ".venv" not in str(sdir):
            continue
        for lname in launcher_names:
            lpath = sdir / lname
            if lpath.exists() and lpath.is_file():
                launcher_candidates.append(lpath)

    info.launcher_files = _dedupe_paths(launcher_candidates)

    # 3. Installed pip/uv distribution metadata & non-checkout site-packages
    sp_dirs = (
        discover_site_packages_dirs(extra_site_packages_dirs)
        if include_system_paths
        else _dedupe_paths(extra_site_packages_dirs or [])
    )
    meta_dirs: list[Path] = []
    mod_paths: list[Path] = []
    for sp in sp_dirs:
        if not sp.exists():
            continue
        # Do not strip the current project's own development .venv during test runs
        if _is_git_source_checkout(sp):
            continue
        for pattern in (
            "bitchat-*.dist-info",
            "bitchat-*.egg-info",
            "__editable__.bitchat-*.pth",
            "__editable___bitchat_*.py",
            "bitchat.pth",
            "_bitchat_core*.pyd",
            "_bitchat_core*.so",
        ):
            for item in sp.glob(pattern):
                if item.is_dir():
                    meta_dirs.append(item)
                else:
                    mod_paths.append(item)
        pkg_dir = sp / "bitchat"
        if (
            pkg_dir.exists()
            and pkg_dir.is_dir()
            and not _is_git_source_checkout(pkg_dir)
        ):
            mod_paths.append(pkg_dir)

    info.package_metadata_dirs = _dedupe_paths(meta_dirs)
    info.package_module_paths = _dedupe_paths(mod_paths)

    # 4. Shortcuts and startup registrations
    if include_system_paths:
        if sys.platform == "win32":
            appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
            program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
            public_dir = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))

            shortcut_candidates = [
                appdata
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "BitChat",
                program_data
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "BitChat",
                home / "Desktop" / "BitChat.lnk",
                public_dir / "Desktop" / "BitChat.lnk",
            ]
            for sc in _dedupe_paths(shortcut_candidates):
                if sc.exists():
                    info.shortcut_paths.append(sc)

            startup_lnk = (
                appdata
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Startup"
                / "BitChat.lnk"
            )
            if startup_lnk.exists():
                info.startup_entries.append(str(startup_lnk))

            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, WINDOWS_RUN_REG_KEY
                ) as rkey:
                    val, _ = winreg.QueryValueEx(rkey, "BitChat")
                    if val:
                        info.startup_entries.append(
                            f"HKCU\\{WINDOWS_RUN_REG_KEY}\\BitChat"
                        )
            except (ImportError, OSError):
                pass
        else:
            linux_shortcuts = [
                home / ".local" / "share" / "applications" / "bitchat.desktop",
                Path("/usr/share/applications/bitchat.desktop"),
                home
                / ".local"
                / "share"
                / "icons"
                / "hicolor"
                / "256x256"
                / "apps"
                / "bitchat.png",
            ]
            for sc in linux_shortcuts:
                if sc.exists():
                    info.shortcut_paths.append(sc)
            autostart = home / ".config" / "autostart" / "bitchat.desktop"
            if autostart.exists():
                info.startup_entries.append(str(autostart))

    # 5. BitChat-owned PATH entries
    if include_system_paths:
        raw_path = os.environ.get("PATH", "")
        for entry in raw_path.split(os.pathsep):
            cleaned = entry.strip().strip('"')
            if (
                cleaned
                and _is_bitchat_owned_install_dir(cleaned)
                and cleaned not in info.bitchat_path_entries
            ):
                info.bitchat_path_entries.append(cleaned)

        if sys.platform == "win32":
            for _, reg_path_val in _read_windows_registry_paths():
                for entry in reg_path_val.split(";"):
                    cleaned = entry.strip().strip('"')
                    if (
                        cleaned
                        and _is_bitchat_owned_install_dir(cleaned)
                        and cleaned not in info.bitchat_path_entries
                    ):
                        info.bitchat_path_entries.append(cleaned)

    # 6. User data & cache directories
    user_data_candidates: list[Path] = []
    if extra_user_data_dirs:
        user_data_candidates.extend(extra_user_data_dirs)
    if include_system_paths:
        user_data_candidates.append(DEFAULT_DATA_DIR)
        user_data_candidates.append(home / ".bitchat")
        if sys.platform == "win32":
            appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
            local_appdata = Path(
                os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
            )
            user_data_candidates.extend(
                [
                    appdata / "bitchat",
                    local_appdata / "bitchat",
                ]
            )
        else:
            user_data_candidates.extend(
                [
                    home / ".config" / "bitchat",
                    home / ".cache" / "bitchat",
                    home / ".local" / "share" / "bitchat",
                ]
            )

    for ud in _dedupe_paths(user_data_candidates):
        if ud.exists() and ud.is_dir() and not _is_git_source_checkout(ud):
            # Ensure we don't confuse %LOCALAPPDATA%\Programs\BitChat with user data
            if any(
                _norm_win_path(ud) == _norm_win_path(sd) for sd in info.standalone_dirs
            ):
                continue
            info.user_data_dirs.append(ud)

    return info


def _read_windows_registry_paths() -> list[tuple[str, str]]:
    """Return list of (hive_label, raw_Path_string) from HKCU/HKLM Environment keys."""
    results: list[tuple[str, str]] = []
    if sys.platform != "win32":
        return results
    try:
        import winreg

        for label, hive, subkey in (
            ("HKCU", winreg.HKEY_CURRENT_USER, WINDOWS_USER_ENV_KEY),
            ("HKLM", winreg.HKEY_LOCAL_MACHINE, WINDOWS_SYS_ENV_KEY),
        ):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, "Path")
                    if isinstance(val, str):
                        results.append((label, val))
            except OSError:
                continue
    except ImportError:
        pass
    return results


def filter_path_string(
    raw_path: str,
    dirs_to_remove: list[str | Path] | None = None,
    sep: str = ";",
) -> tuple[str, list[str]]:
    """Remove BitChat-owned directories from a ``PATH`` string safely.

    - Case-insensitive comparison on Windows
    - Strips surrounding quotes and trailing slashes before comparing
    - Preserves original order and formatting of all unrelated entries
    - Never removes shared directories (such as ``Python314\\Scripts`` or ``System32``)
    - Removes empty segments and duplicate segments of removed directories
    """
    explicit_targets: set[str] = set()
    if dirs_to_remove:
        for d in dirs_to_remove:
            norm = _norm_win_path(d)
            if norm and _is_bitchat_owned_install_dir(norm):
                explicit_targets.add(norm)

    kept: list[str] = []
    removed: list[str] = []

    for segment in raw_path.split(sep):
        stripped = segment.strip()
        if not stripped:
            continue
        norm = _norm_win_path(stripped)
        if not norm:
            continue
        if norm in explicit_targets or _is_bitchat_owned_install_dir(norm):
            removed.append(stripped.strip('"'))
        else:
            kept.append(stripped)

    return sep.join(kept), removed


def clean_windows_path_environment(
    extra_dirs_to_remove: list[str | Path] | None = None,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Remove BitChat-owned directories from process PATH and Windows Registry PATH."""
    removed_all: list[str] = []

    # 1. Clean in-process os.environ["PATH"]
    current_env_path = os.environ.get("PATH", "")
    new_env_path, env_removed = filter_path_string(
        current_env_path, extra_dirs_to_remove, sep=os.pathsep
    )
    for item in env_removed:
        if item not in removed_all:
            removed_all.append(item)
    if not dry_run and env_removed:
        os.environ["PATH"] = new_env_path

    if sys.platform != "win32":
        return removed_all

    # 2. Clean HKCU and (if writable) HKLM Registry Path
    try:
        import winreg

        modified_registry = False
        for hive, subkey in (
            (winreg.HKEY_CURRENT_USER, WINDOWS_USER_ENV_KEY),
            (winreg.HKEY_LOCAL_MACHINE, WINDOWS_SYS_ENV_KEY),
        ):
            try:
                with winreg.OpenKey(
                    hive, subkey, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
                ) as key:
                    raw_val, reg_type = winreg.QueryValueEx(key, "Path")
                    if not isinstance(raw_val, str):
                        continue
                    updated_val, reg_removed = filter_path_string(
                        raw_val, extra_dirs_to_remove, sep=";"
                    )
                    for item in reg_removed:
                        if item not in removed_all:
                            removed_all.append(item)
                    if reg_removed and not dry_run:
                        if updated_val:
                            winreg.SetValueEx(key, "Path", 0, reg_type, updated_val)
                        else:
                            try:
                                winreg.DeleteValue(key, "Path")
                            except OSError:
                                winreg.SetValueEx(key, "Path", 0, reg_type, "")
                        modified_registry = True
            except OSError:
                continue

        # Also clean Inno Setup's PathAddedByInstaller marker if present
        if not dry_run:
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for reg_subkey in (
                    *WINDOWS_UNINSTALL_REG_KEYS,
                    WINDOWS_APP_METADATA_REG_KEY,
                ):
                    try:
                        with winreg.OpenKey(
                            hive,
                            reg_subkey,
                            0,
                            winreg.KEY_SET_VALUE,
                        ) as ukey:
                            winreg.DeleteValue(ukey, "PathAddedByInstaller")
                    except OSError:
                        pass

        if modified_registry and not dry_run:
            _broadcast_windows_env_change()
    except ImportError:
        pass

    return removed_all


def _broadcast_windows_env_change() -> None:
    """Broadcast WM_SETTINGCHANGE ('Environment') so new shells pick up PATH updates."""
    if sys.platform != "win32":
        return
    try:
        hwnd_broadcast = 0xFFFF
        wm_settingchange = 0x001A
        smto_abortifhung = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast,
            wm_settingchange,
            0,
            "Environment",
            smto_abortifhung,
            2000,
            ctypes.byref(result),
        )
    except Exception:
        pass


def stop_running_bitchat_processes(*, dry_run: bool = False) -> list[int]:
    """Find and terminate running ``bitchat`` processes (excluding self)."""
    current_pid = os.getpid()
    stopped_pids: list[int] = []

    if sys.platform == "win32":
        try:
            proc = subprocess.run(
                [
                    "tasklist",
                    "/FI",
                    "IMAGENAME eq bitchat.exe",
                    "/FO",
                    "CSV",
                    "/NH",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line or "bitchat.exe" not in line.lower():
                    continue
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2 and parts[1].isdigit():
                    pid = int(parts[1])
                    if pid != current_pid:
                        stopped_pids.append(pid)
                        if not dry_run:
                            subprocess.run(
                                ["taskkill", "/F", "/T", "/PID", str(pid)],
                                capture_output=True,
                                timeout=5,
                                check=False,
                            )
        except Exception:
            pass
    else:
        try:
            proc = subprocess.run(
                ["pgrep", "-x", "bitchat"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            for line in proc.stdout.splitlines():
                if line.strip().isdigit():
                    pid = int(line.strip())
                    if pid != current_pid:
                        stopped_pids.append(pid)
                        if not dry_run:
                            with contextlib.suppress(OSError):
                                os.kill(pid, 15)
        except Exception:
            pass

    if stopped_pids and not dry_run:
        time.sleep(0.15)
    return stopped_pids


def _schedule_windows_delete_on_exit_or_reboot(target: Path) -> bool:
    """Handle a locked Windows file by renaming + background/reboot delete."""
    if sys.platform != "win32":
        return False

    target_to_delete = target
    # Windows allows renaming a currently executing .exe in the same directory!
    try:
        temp_renamed = target.with_name(f".{target.name}.{os.getpid()}.old_delete")
        if temp_renamed.exists():
            with contextlib.suppress(OSError):
                temp_renamed.unlink()
        target.rename(temp_renamed)
        target_to_delete = temp_renamed
    except OSError:
        pass

    # Spawn a detached background cmd.exe that waits ~1 second and deletes the file
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(
            subprocess, "DETACHED_PROCESS", 0x00000008
        )
        del_cmd = (
            f'ping 127.0.0.1 -n 2 > nul & del /f /q "{target_to_delete}" > nul 2>&1'
        )
        subprocess.Popen(
            ["cmd.exe", "/c", del_cmd],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except Exception:
        pass

    # Also register with MoveFileExW(..., MOVEFILE_DELAY_UNTIL_REBOOT) as OS guarantee
    try:
        movefile_delay_until_reboot = 0x00000004
        res = ctypes.windll.kernel32.MoveFileExW(
            str(target_to_delete), None, movefile_delay_until_reboot
        )
        return bool(res) or target_to_delete != target
    except Exception:
        return target_to_delete != target


def _remove_file_safe(path: Path, report: UninstallReport) -> None:
    """Remove a single file, handling permissions and Windows file locks."""
    if not path.exists() and not path.is_symlink():
        return
    if report.dry_run:
        report.removed_files.append(str(path))
        return

    try:
        with contextlib.suppress(OSError):
            os.chmod(path, 0o666)
        path.unlink()
        report.removed_files.append(str(path))
    except PermissionError as exc:
        if _schedule_windows_delete_on_exit_or_reboot(path):
            report.deferred_reboot_deletions.append(str(path))
            if not path.exists():
                report.removed_files.append(str(path))
        else:
            report.errors.append(f"Failed to remove locked file {path}: {exc}")
    except OSError as exc:
        report.errors.append(f"Failed to remove file {path}: {exc}")


def _remove_dir_safe(
    path: Path,
    report: UninstallReport,
    *,
    is_user_data: bool = False,
    is_shortcut: bool = False,
) -> None:
    """Recursively remove a directory and record the result in ``report``."""
    if not path.exists():
        return
    if _is_git_source_checkout(path):
        return

    target_list = (
        report.removed_user_data
        if is_user_data
        else (report.removed_shortcuts if is_shortcut else report.removed_dirs)
    )
    if report.dry_run:
        target_list.append(str(path))
        return

    def _onerror(func: Callable[..., object], fpath: str, _exc_info: object) -> None:
        p = Path(fpath)
        try:
            os.chmod(p, 0o777)
            func(fpath)
        except OSError:
            if p.is_file() and _schedule_windows_delete_on_exit_or_reboot(p):
                report.deferred_reboot_deletions.append(str(p))
            else:
                report.errors.append(f"Failed to remove {fpath}")

    shutil.rmtree(path, onerror=_onerror)
    if not path.exists():
        target_list.append(str(path))


def verify_remaining_bitchat_commands(
    search_paths: list[Path] | None = None,
) -> list[str]:
    """Return any ``bitchat`` executables still resolvable on PATH or search_paths."""
    remaining: list[str] = []
    launcher_names = (
        ("bitchat.exe", "bitchat.cmd", "bitchat.bat")
        if sys.platform == "win32"
        else ("bitchat",)
    )

    if search_paths is not None:
        for sp in search_paths:
            for lname in launcher_names:
                cand = sp / lname
                if cand.exists() and cand.is_file():
                    remaining.append(str(cand))
        return remaining

    resolved = shutil.which("bitchat")
    if resolved:
        resolved_path = Path(resolved)
        # Ignore the development workspace .venv if running pytest inside the git repo
        if not (
            _is_git_source_checkout(resolved_path) and ".venv" in str(resolved_path)
        ):
            remaining.append(str(resolved_path))

    return remaining


def run_uninstaller(
    *,
    remove_user_data: bool = False,
    dry_run: bool = False,
    extra_scripts_dirs: list[Path] | None = None,
    extra_site_packages_dirs: list[Path] | None = None,
    extra_standalone_dirs: list[Path] | None = None,
    extra_user_data_dirs: list[Path] | None = None,
    include_system_paths: bool = True,
) -> UninstallReport:
    """Execute a complete, idempotent BitChat uninstallation."""
    report = UninstallReport(
        dry_run=dry_run,
        remove_user_data=remove_user_data,
    )

    # 1. Stop running BitChat instances if interacting with system installation
    if include_system_paths:
        report.stopped_pids = stop_running_bitchat_processes(dry_run=dry_run)

    # 2. Discover all installation artifacts
    discovered = discover_installations(
        extra_scripts_dirs=extra_scripts_dirs,
        extra_site_packages_dirs=extra_site_packages_dirs,
        extra_standalone_dirs=extra_standalone_dirs,
        extra_user_data_dirs=extra_user_data_dirs,
        include_system_paths=include_system_paths,
    )

    # 3. Remove console-script launchers (e.g., Python314\Scripts\bitchat.exe)
    for launcher in discovered.launcher_files:
        _remove_file_safe(launcher, report)

    # 4. Remove pip/uv package metadata & installed site-packages modules
    for meta_dir in discovered.package_metadata_dirs:
        _remove_dir_safe(meta_dir, report)
    for mod_path in discovered.package_module_paths:
        if mod_path.is_dir():
            _remove_dir_safe(mod_path, report)
        else:
            _remove_file_safe(mod_path, report)

    # 5. Remove standalone installation directories
    for sdir in discovered.standalone_dirs:
        _remove_dir_safe(sdir, report)

    # 6. Remove shortcuts and startup registrations
    for sc in discovered.shortcut_paths:
        if sc.is_dir():
            _remove_dir_safe(sc, report, is_shortcut=True)
        elif sc.exists():
            if dry_run:
                report.removed_shortcuts.append(str(sc))
            else:
                try:
                    sc.unlink()
                    report.removed_shortcuts.append(str(sc))
                except OSError as exc:
                    report.errors.append(f"Failed to remove shortcut {sc}: {exc}")

    for startup_item in discovered.startup_entries:
        if startup_item.startswith("HKCU\\"):
            if dry_run:
                report.removed_registry_keys.append(startup_item)
            elif sys.platform == "win32":
                try:
                    import winreg

                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        WINDOWS_RUN_REG_KEY,
                        0,
                        winreg.KEY_SET_VALUE,
                    ) as rkey:
                        winreg.DeleteValue(rkey, "BitChat")
                        report.removed_registry_keys.append(startup_item)
                except (ImportError, OSError):
                    pass
        else:
            sp = Path(startup_item)
            if sp.exists():
                if dry_run:
                    report.removed_shortcuts.append(str(sp))
                else:
                    try:
                        sp.unlink()
                        report.removed_shortcuts.append(str(sp))
                    except OSError as exc:
                        report.errors.append(
                            f"Failed to remove startup entry {sp}: {exc}"
                        )

    # 7. Clean Windows Uninstall registry keys
    if include_system_paths and sys.platform == "win32":
        for reg_key_desc in discovered.registry_keys:
            if dry_run:
                report.removed_registry_keys.append(reg_key_desc)
                continue
            try:
                import winreg

                hive = (
                    winreg.HKEY_CURRENT_USER
                    if reg_key_desc.startswith("HKCU\\")
                    else winreg.HKEY_LOCAL_MACHINE
                )
                subkey = reg_key_desc.split("\\", 1)[1]
                winreg.DeleteKey(hive, subkey)
                report.removed_registry_keys.append(reg_key_desc)
            except (ImportError, OSError):
                pass

    # 8. Clean BitChat-owned PATH entries
    if include_system_paths:
        removed_paths = clean_windows_path_environment(
            extra_dirs_to_remove=[str(d) for d in discovered.standalone_dirs],
            dry_run=dry_run,
        )
        report.removed_path_entries.extend(removed_paths)

    # 9. Handle user data according to selected mode
    if remove_user_data:
        for udir in discovered.user_data_dirs:
            _remove_dir_safe(udir, report, is_user_data=True)
    else:
        for udir in discovered.user_data_dirs:
            if udir.exists():
                report.preserved_user_data.append(str(udir))

    # 10. Post-uninstall verification
    if not dry_run:
        if include_system_paths:
            report.remaining_commands_on_path = verify_remaining_bitchat_commands()
        elif extra_scripts_dirs:
            report.remaining_commands_on_path = verify_remaining_bitchat_commands(
                extra_scripts_dirs
            )

    return report


def format_uninstall_report(report: UninstallReport) -> str:
    """Format an ``UninstallReport`` into clear human-readable CLI output."""
    mode_label = (
        "Complete removal (application + user data)"
        if report.remove_user_data
        else "Standard uninstall (application only; user data preserved)"
    )
    prefix = "[DRY RUN] " if report.dry_run else ""
    lines = [
        f"{prefix}BitChat Uninstaller — {mode_label}",
        "-" * 64,
    ]
    if report.stopped_pids:
        pids_str = ", ".join(map(str, report.stopped_pids))
        lines.append(f"Stopped running BitChat processes (PIDs): {pids_str}")
    if report.removed_files:
        lines.append(f"Removed files ({len(report.removed_files)}):")
        for f in report.removed_files:
            lines.append(f"  - {f}")
    if report.removed_dirs:
        lines.append(f"Removed directories ({len(report.removed_dirs)}):")
        for d in report.removed_dirs:
            lines.append(f"  - {d}")
    if report.removed_shortcuts:
        lines.append(f"Removed shortcuts ({len(report.removed_shortcuts)}):")
        for s in report.removed_shortcuts:
            lines.append(f"  - {s}")
    if report.removed_registry_keys:
        lines.append(f"Removed registry entries ({len(report.removed_registry_keys)}):")
        for rk in report.removed_registry_keys:
            lines.append(f"  - {rk}")
    if report.removed_path_entries:
        lines.append(
            f"Removed BitChat PATH entries ({len(report.removed_path_entries)}):"
        )
        for pe in report.removed_path_entries:
            lines.append(f"  - {pe}")
    if report.removed_user_data:
        lines.append(
            f"Removed user data directories ({len(report.removed_user_data)}):"
        )
        for ud in report.removed_user_data:
            lines.append(f"  - {ud}")
    if report.preserved_user_data:
        lines.append(
            f"Preserved user data directories ({len(report.preserved_user_data)}):"
        )
        for pd in report.preserved_user_data:
            lines.append(f"  - {pd}")
    if report.deferred_reboot_deletions:
        lines.append(
            "Scheduled locked files for deletion on process exit / next reboot:"
        )
        for df in report.deferred_reboot_deletions:
            lines.append(f"  - {df}")
    if (
        not report.removed_files
        and not report.removed_dirs
        and not report.removed_shortcuts
        and not report.removed_registry_keys
        and not report.removed_path_entries
        and not report.removed_user_data
        and not report.deferred_reboot_deletions
    ):
        lines.append("No BitChat installation artifacts were found.")
    if report.remaining_commands_on_path:
        lines.append("WARNING — Remaining bitchat commands detected on PATH:")
        for rem in report.remaining_commands_on_path:
            lines.append(f"  ! {rem}")
    if report.errors:
        lines.append("Errors encountered:")
        for err in report.errors:
            lines.append(f"  ! {err}")
    else:
        lines.append("Status: Uninstallation completed cleanly.")
    return "\n".join(lines)
