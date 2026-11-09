"""Comprehensive unit and lifecycle tests for the BitChat uninstaller (Windows & Linux)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bitchat.__main__ import main
from bitchat.platform.uninstaller import (
    UninstallReport,
    _remove_file_safe,
    discover_installations,
    filter_path_string,
    format_uninstall_report,
    run_uninstaller,
    verify_remaining_bitchat_commands,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _populate_standalone_install(install_dir: Path) -> Path:
    """Create a realistic standalone Windows/Linux BitChat installation tree."""
    install_dir.mkdir(parents=True, exist_ok=True)
    exe_name = "bitchat.exe" if sys.platform == "win32" else "bitchat"
    main_exe = install_dir / exe_name
    main_exe.write_bytes(b"MZ_FAKE_BITCHAT_STANDALONE_BINARY")
    internal = install_dir / "_internal"
    internal.mkdir(exist_ok=True)
    (internal / "_bitchat_core.pyd").write_bytes(b"FAKE_RUST_CORE")
    (install_dir / "unins000.exe").write_bytes(b"FAKE_INNO_UNINSTALLER")
    (install_dir / "unins000.dat").write_bytes(b"FAKE_INNO_DATA")
    return main_exe


def _populate_python_scripts_install(
    scripts_dir: Path,
    site_packages_dir: Path | None = None,
) -> Path:
    """Create a realistic Python pip/uv Scripts installation (e.g. Python314\\Scripts\\bitchat.exe)."""
    scripts_dir.mkdir(parents=True, exist_ok=True)
    launcher_name = "bitchat.exe" if sys.platform == "win32" else "bitchat"
    launcher = scripts_dir / launcher_name
    launcher.write_bytes(b"MZ_PIP_CONSOLE_SCRIPT_WRAPPER")
    if sys.platform == "win32":
        (scripts_dir / "bitchat-script.py").write_text("#!python\n", encoding="utf-8")
    # Also place unrelated tools in the shared Scripts dir to verify they are NEVER deleted
    (scripts_dir / ("pip.exe" if sys.platform == "win32" else "pip")).write_bytes(
        b"PIP"
    )
    (scripts_dir / ("pytest.exe" if sys.platform == "win32" else "pytest")).write_bytes(
        b"PYTEST"
    )

    if site_packages_dir is not None:
        site_packages_dir.mkdir(parents=True, exist_ok=True)
        dist_info = site_packages_dir / "bitchat-0.3.0.dist-info"
        dist_info.mkdir(exist_ok=True)
        (dist_info / "METADATA").write_text(
            "Name: bitchat\nVersion: 0.3.0\n", encoding="utf-8"
        )
        pkg_dir = site_packages_dir / "bitchat"
        pkg_dir.mkdir(exist_ok=True)
        (pkg_dir / "__init__.py").write_text(
            "__version__ = '0.3.0'\n", encoding="utf-8"
        )
        (site_packages_dir / "_bitchat_core.pyd").write_bytes(b"RUST_EXT")
        # Unrelated package in site-packages
        other_pkg = site_packages_dir / "textual"
        other_pkg.mkdir(exist_ok=True)
        (other_pkg / "__init__.py").write_text("", encoding="utf-8")

    return launcher


def _populate_user_data(user_data_dir: Path) -> None:
    """Create simulated ~/.bitchat user data (identity keys, peers, history, config)."""
    user_data_dir.mkdir(parents=True, exist_ok=True)
    (user_data_dir / "identity.json").write_text(
        '{"peer_id": "1122334455667788"}', encoding="utf-8"
    )
    (user_data_dir / "config.toml").write_text('nickname = "alice"\n', encoding="utf-8")
    (user_data_dir / "peers.json").write_text("{}", encoding="utf-8")
    (user_data_dir / "history.jsonl").write_text("", encoding="utf-8")


def test_scenario_1_and_2_standalone_default_and_custom_install_dir(
    tmp_path: Path,
) -> None:
    """Scenarios 1 & 2: Uninstall standalone BitChat from default and custom directories."""
    default_dir = tmp_path / "LocalAppData" / "Programs" / "BitChat"
    custom_dir = tmp_path / "CustomApps" / "BitChat"
    _populate_standalone_install(default_dir)
    _populate_standalone_install(custom_dir)

    report = run_uninstaller(
        remove_user_data=False,
        extra_standalone_dirs=[default_dir, custom_dir],
        include_system_paths=False,
    )
    assert report.succeeded
    assert not default_dir.exists()
    assert not custom_dir.exists()
    assert str(default_dir) in report.removed_dirs
    assert str(custom_dir) in report.removed_dirs


def test_scenario_3_and_7_python314_scripts_bitchat_exe_removal(tmp_path: Path) -> None:
    """Scenarios 3 & 7: Remove Python314\\Scripts\\bitchat.exe and site-packages without harming pip/pytest."""
    py314_root = (
        tmp_path
        / "Users"
        / "TestUser"
        / "AppData"
        / "Local"
        / "Programs"
        / "Python"
        / "Python314"
    )
    scripts_dir = py314_root / "Scripts"
    site_packages = py314_root / "Lib" / "site-packages"
    bitchat_exe = _populate_python_scripts_install(scripts_dir, site_packages)

    assert bitchat_exe.exists()
    assert (site_packages / "bitchat").exists()
    assert (site_packages / "bitchat-0.3.0.dist-info").exists()

    report = run_uninstaller(
        remove_user_data=False,
        extra_scripts_dirs=[scripts_dir],
        extra_site_packages_dirs=[site_packages],
        include_system_paths=False,
    )
    assert report.succeeded
    assert not bitchat_exe.exists()
    assert not (scripts_dir / "bitchat-script.py").exists()
    assert not (site_packages / "bitchat").exists()
    assert not (site_packages / "bitchat-0.3.0.dist-info").exists()
    assert not (site_packages / "_bitchat_core.pyd").exists()

    # Shared Python314\Scripts directory and unrelated tools MUST remain intact!
    assert scripts_dir.exists()
    assert (scripts_dir / ("pip.exe" if sys.platform == "win32" else "pip")).exists()
    assert (
        scripts_dir / ("pytest.exe" if sys.platform == "win32" else "pytest")
    ).exists()
    assert (site_packages / "textual" / "__init__.py").exists()
    assert verify_remaining_bitchat_commands([scripts_dir]) == []


def test_scenario_4_uv_tool_installation_removal(tmp_path: Path) -> None:
    """Scenario 4: Install and uninstall Python package via uv tools / local bin."""
    uv_bin = tmp_path / ".local" / "bin"
    uv_tool_scripts = (
        tmp_path / "AppData" / "Local" / "uv" / "tools" / "bitchat" / "Scripts"
    )
    l1 = _populate_python_scripts_install(uv_bin)
    l2 = _populate_python_scripts_install(uv_tool_scripts)

    report = run_uninstaller(
        remove_user_data=False,
        extra_scripts_dirs=[uv_bin, uv_tool_scripts],
        include_system_paths=False,
    )
    assert report.succeeded
    assert not l1.exists()
    assert not l2.exists()
    assert verify_remaining_bitchat_commands([uv_bin, uv_tool_scripts]) == []


def test_scenario_5_and_6_coexisting_standalone_and_pip_installations(
    tmp_path: Path,
) -> None:
    """Scenarios 5 & 6: Coexisting standalone .exe and Python314\\Scripts\\bitchat.exe are both removed cleanly."""
    standalone_dir = tmp_path / "Programs" / "BitChat"
    py314_scripts = tmp_path / "Programs" / "Python" / "Python314" / "Scripts"
    py312_scripts = tmp_path / "Programs" / "Python" / "Python312" / "Scripts"

    standalone_exe = _populate_standalone_install(standalone_dir)
    py314_exe = _populate_python_scripts_install(py314_scripts)
    py312_exe = _populate_python_scripts_install(py312_scripts)

    discovered = discover_installations(
        extra_standalone_dirs=[standalone_dir],
        extra_scripts_dirs=[py314_scripts, py312_scripts],
        include_system_paths=False,
    )
    assert standalone_dir in discovered.standalone_dirs
    assert py314_exe in discovered.launcher_files
    assert py312_exe in discovered.launcher_files

    report = run_uninstaller(
        remove_user_data=False,
        extra_standalone_dirs=[standalone_dir],
        extra_scripts_dirs=[py314_scripts, py312_scripts],
        include_system_paths=False,
    )
    assert report.succeeded
    assert not standalone_exe.exists()
    assert not standalone_dir.exists()
    assert not py314_exe.exists()
    assert not py312_exe.exists()
    assert (
        verify_remaining_bitchat_commands(
            [standalone_dir, py314_scripts, py312_scripts]
        )
        == []
    )


def test_scenario_8_9_10_shortcuts_and_startup_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenarios 8, 9, 10: Desktop shortcut, Start Menu folder, and Startup shortcut removal."""
    fake_home = tmp_path / "Home"
    fake_appdata = fake_home / "AppData" / "Roaming"
    fake_localappdata = fake_home / "AppData" / "Local"
    fake_public = tmp_path / "Public"
    fake_programdata = tmp_path / "ProgramData"

    desktop_lnk = fake_home / "Desktop" / "BitChat.lnk"
    desktop_lnk.parent.mkdir(parents=True, exist_ok=True)
    desktop_lnk.write_bytes(b"LNK")

    start_menu_dir = (
        fake_appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "BitChat"
    )
    start_menu_dir.mkdir(parents=True, exist_ok=True)
    (start_menu_dir / "BitChat.lnk").write_bytes(b"LNK")
    (start_menu_dir / "Uninstall BitChat.lnk").write_bytes(b"LNK")

    startup_lnk = (
        fake_appdata
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "BitChat.lnk"
    )
    startup_lnk.parent.mkdir(parents=True, exist_ok=True)
    startup_lnk.write_bytes(b"LNK")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(fake_localappdata))
    monkeypatch.setenv("PUBLIC", str(fake_public))
    monkeypatch.setenv("ProgramData", str(fake_programdata))

    if sys.platform == "win32":
        with (
            patch(
                "bitchat.platform.uninstaller.stop_running_bitchat_processes",
                return_value=[],
            ),
            patch(
                "bitchat.platform.uninstaller.discover_python_scripts_dirs",
                return_value=[],
            ),
            patch(
                "bitchat.platform.uninstaller.discover_site_packages_dirs",
                return_value=[],
            ),
            patch(
                "bitchat.platform.uninstaller.clean_windows_path_environment",
                return_value=[],
            ),
            patch(
                "bitchat.platform.uninstaller.verify_remaining_bitchat_commands",
                return_value=[],
            ),
        ):
            report = run_uninstaller(remove_user_data=False, include_system_paths=True)
            assert not desktop_lnk.exists()
            assert not start_menu_dir.exists()
            assert not startup_lnk.exists()
            assert len(report.removed_shortcuts) >= 3


def test_scenario_11_safe_path_cleanup() -> None:
    """Scenario 11: PATH cleanup removes BitChat-owned paths and preserves Python314\\Scripts & System32."""
    raw_path = (
        r"C:\Windows\System32;"
        r"C:\Users\Alice\AppData\Local\Programs\Python\Python314\Scripts;"
        r"C:\Users\Alice\AppData\Local\Programs\BitChat;"
        r'"C:\Users\Alice\AppData\Local\Programs\BitChat\";'
        r"D:\CustomTools\bin;"
        r"D:\Apps\BitChat"
    )
    cleaned, removed = filter_path_string(
        raw_path,
        dirs_to_remove=[
            r"C:\Users\Alice\AppData\Local\Programs\BitChat",
            r"D:\Apps\BitChat",
        ],
        sep=";",
    )
    assert len(removed) == 3
    assert r"C:\Windows\System32" in cleaned
    assert r"C:\Users\Alice\AppData\Local\Programs\Python\Python314\Scripts" in cleaned
    assert r"D:\CustomTools\bin" in cleaned
    assert "Programs\\BitChat" not in cleaned
    assert "Apps\\BitChat" not in cleaned
    assert ";;" not in cleaned


def test_scenario_13_14_17_user_data_preservation_vs_purge_and_reinstall(
    tmp_path: Path,
) -> None:
    """Scenarios 13, 14, 17: Standard uninstall preserves ~/.bitchat; --remove-user-data deletes it."""
    standalone_dir = tmp_path / "Programs" / "BitChat"
    user_data_dir = tmp_path / ".bitchat"
    _populate_standalone_install(standalone_dir)
    _populate_user_data(user_data_dir)

    # 1. Standard uninstall (remove_user_data=False) -> preserves ~/.bitchat
    report_keep = run_uninstaller(
        remove_user_data=False,
        extra_standalone_dirs=[standalone_dir],
        extra_user_data_dirs=[user_data_dir],
        include_system_paths=False,
    )
    assert report_keep.succeeded
    assert not standalone_dir.exists()
    assert user_data_dir.exists()
    assert (user_data_dir / "identity.json").exists()
    assert str(user_data_dir) in report_keep.preserved_user_data
    assert report_keep.removed_user_data == []

    # 2. Reinstall after standard uninstall -> existing identity.json is still present
    _populate_standalone_install(standalone_dir)
    assert standalone_dir.exists()
    assert (user_data_dir / "identity.json").exists()

    # 3. Complete uninstall (remove_user_data=True) -> deletes both app and ~/.bitchat
    report_purge = run_uninstaller(
        remove_user_data=True,
        extra_standalone_dirs=[standalone_dir],
        extra_user_data_dirs=[user_data_dir],
        include_system_paths=False,
    )
    assert report_purge.succeeded
    assert not standalone_dir.exists()
    assert not user_data_dir.exists()
    assert str(user_data_dir) in report_purge.removed_user_data


def test_scenario_15_locked_file_handling_schedules_deferred_deletion(
    tmp_path: Path,
) -> None:
    """Scenario 15: Locked executable on Windows schedules deferred deletion instead of crashing."""
    locked_exe = tmp_path / "bitchat.exe"
    locked_exe.write_bytes(b"LOCKED")
    report = UninstallReport(dry_run=False, remove_user_data=False)

    with (
        patch.object(
            Path,
            "unlink",
            side_effect=PermissionError("File is locked by another process"),
        ),
        patch(
            "bitchat.platform.uninstaller._schedule_windows_delete_on_exit_or_reboot",
            return_value=True,
        ) as mock_sched,
    ):
        _remove_file_safe(locked_exe, report)
        mock_sched.assert_called_once_with(locked_exe)
        assert str(locked_exe) in report.deferred_reboot_deletions
        assert report.errors == []


def test_scenario_16_idempotent_repeated_uninstall(tmp_path: Path) -> None:
    """Scenario 16: Running the uninstaller repeatedly is completely idempotent and succeeds."""
    standalone_dir = tmp_path / "Programs" / "BitChat"
    scripts_dir = tmp_path / "Python314" / "Scripts"
    _populate_standalone_install(standalone_dir)
    _populate_python_scripts_install(scripts_dir)

    first = run_uninstaller(
        remove_user_data=False,
        extra_standalone_dirs=[standalone_dir],
        extra_scripts_dirs=[scripts_dir],
        include_system_paths=False,
    )
    assert first.succeeded
    assert len(first.removed_dirs) == 1
    assert len(first.removed_files) >= 1

    # Second run when nothing is left
    second = run_uninstaller(
        remove_user_data=False,
        extra_standalone_dirs=[standalone_dir],
        extra_scripts_dirs=[scripts_dir],
        include_system_paths=False,
    )
    assert second.succeeded
    assert second.removed_dirs == []
    assert second.removed_files == []
    formatted = format_uninstall_report(second)
    assert "No BitChat installation artifacts were found." in formatted


def test_inno_setup_and_linux_deb_uninstaller_scripts_completeness() -> None:
    """Verify Inno Setup (bitchat.iss) and Debian (prerm/postrm) scripts contain all cleanup hooks."""
    iss_path = REPO_ROOT / "packaging" / "windows" / "bitchat.iss"
    iss_text = iss_path.read_text(encoding="utf-8")

    # Inno Setup must clean Python3XX\Scripts\bitchat.exe shims, stop processes, and clean PATH
    assert "RemovePythonScriptLaunchersAndShims" in iss_text
    assert "StopAllRunningBitChatProcesses" in iss_text
    assert "RemoveSpecificDirFromPathValue" in iss_text
    assert "[UninstallDelete]" in iss_text
    assert r"Programs\Python" in iss_text
    assert "/REMOVEUSERDATA" in iss_text

    # Linux .deb prerm & postrm scripts
    prerm_path = REPO_ROOT / "packaging" / "linux" / "deb" / "prerm"
    postrm_path = REPO_ROOT / "packaging" / "linux" / "deb" / "postrm"
    assert prerm_path.is_file()
    assert postrm_path.is_file()
    assert "/usr/lib/bitchat/bitchat" in prerm_path.read_text(encoding="utf-8")
    postrm_text = postrm_path.read_text(encoding="utf-8")
    assert "rm -rf /usr/lib/bitchat" in postrm_text
    assert "purge" in postrm_text


def test_cli_uninstall_flags_and_confirmation_safety(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify CLI `--uninstall --dry-run` and `--uninstall --remove-user-data` confirmation guards."""
    fake_report = UninstallReport(
        dry_run=True,
        remove_user_data=False,
        removed_files=[str(tmp_path / "Python314" / "Scripts" / "bitchat.exe")],
    )
    with (
        patch(
            "bitchat.platform.uninstaller.run_uninstaller", return_value=fake_report
        ) as mock_run,
        patch.object(sys, "argv", ["bitchat", "--uninstall", "--dry-run"]),
    ):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        mock_run.assert_called_once_with(remove_user_data=False, dry_run=True)
    out = capsys.readouterr().out
    assert "[DRY RUN]" in out
    assert "bitchat.exe" in out

    # Non-interactive `--uninstall --remove-user-data` without `--yes` must refuse with exit code 2
    with (
        patch.object(sys.stdin, "isatty", return_value=False),
        patch.object(sys, "argv", ["bitchat", "--uninstall", "--remove-user-data"]),
    ):
        with pytest.raises(SystemExit) as exc2:
            main()
        assert exc2.value.code == 2

    # Interactive prompt declined ('n') cancels without deleting user data
    with (
        patch.object(sys.stdin, "isatty", return_value=True),
        patch("builtins.input", return_value="n"),
        patch.object(sys, "argv", ["bitchat", "--uninstall", "--remove-user-data"]),
    ):
        with pytest.raises(SystemExit) as exc3:
            main()
        assert exc3.value.code == 1
