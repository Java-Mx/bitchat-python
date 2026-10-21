"""Tests for centralized OS detection, backend probing, and recovery guidance.

Platform identifiers are mocked, so these run identically on any host OS and
without Bluetooth hardware.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from bitchat.ble.adapter import AdapterInfo, BLEAdapterManager
from bitchat.platform import detection, recovery
from bitchat.platform.capabilities import detect_bluetooth_info
from bitchat.platform.detection import (
    PlatformKind,
    detect_platform,
    is_linux,
    is_supported_platform,
    is_windows,
    peripheral_backend_implemented,
    probe_ble_backend,
)


@pytest.mark.parametrize(
    ("platform_id", "expected"),
    [
        ("win32", PlatformKind.WINDOWS),
        ("linux", PlatformKind.LINUX),
        ("linux2", PlatformKind.LINUX),
        ("darwin", PlatformKind.OTHER),
        ("cygwin", PlatformKind.OTHER),
        ("freebsd14", PlatformKind.OTHER),
        ("", PlatformKind.OTHER),
    ],
)
def test_detect_platform_from_sys_platform(
    monkeypatch: pytest.MonkeyPatch, platform_id: str, expected: PlatformKind
) -> None:
    monkeypatch.setattr(sys, "platform", platform_id)

    assert detect_platform() is expected
    assert is_windows() is (expected is PlatformKind.WINDOWS)
    assert is_linux() is (expected is PlatformKind.LINUX)
    assert is_supported_platform() is (expected is not PlatformKind.OTHER)


def test_peripheral_backend_is_only_implemented_on_windows() -> None:
    assert peripheral_backend_implemented(PlatformKind.WINDOWS) is True
    assert peripheral_backend_implemented(PlatformKind.LINUX) is False
    assert peripheral_backend_implemented(PlatformKind.OTHER) is False


def test_backend_probe_reports_missing_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        detection, "_module_available", lambda name: name != "dbus_fast"
    )

    status = probe_ble_backend(PlatformKind.LINUX)

    assert status.available is False
    assert status.missing_modules == ("dbus_fast",)
    assert status.reason is not None and "dbus_fast" in status.reason
    assert probe_ble_backend(PlatformKind.OTHER).available is True


def test_backend_probe_available_when_modules_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(detection, "_module_available", lambda name: True)

    status = probe_ble_backend(PlatformKind.WINDOWS)

    assert status.available is True
    assert status.reason is None


def test_module_available_honours_blocked_and_absent_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "bitchat_blocked_backend", None)
    assert detection._module_available("bitchat_blocked_backend") is False
    assert detection._module_available("bitchat_no_such_backend") is False
    assert detection._module_available("bitchat_no_such_pkg.sub.mod") is False
    assert detection._module_available("sys") is True


# ---------------------------------------------------------------------------
# Platform detection is independent of adapter availability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform_id", "kind", "checker"),
    [
        ("linux", PlatformKind.LINUX, "_check_linux_adapter"),
        ("win32", PlatformKind.WINDOWS, "_check_windows_adapter"),
    ],
)
async def test_supported_os_without_adapter_is_not_reported_available(
    monkeypatch: pytest.MonkeyPatch, platform_id: str, kind: PlatformKind, checker: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform_id)
    monkeypatch.setattr(detection, "_module_available", lambda name: True)
    calls: list[str] = []

    async def no_adapter(self: BLEAdapterManager) -> AdapterInfo:
        calls.append(checker)
        return AdapterInfo(is_available=False, radio_state="unavailable")

    monkeypatch.setattr(BLEAdapterManager, checker, no_adapter)

    info = await BLEAdapterManager().check_adapter()

    assert detect_platform() is kind
    assert is_supported_platform() is True
    assert info.is_available is False
    assert calls == [checker]


@pytest.mark.parametrize(
    ("platform_id", "checker", "missing"),
    [
        ("linux", "_check_linux_adapter", "dbus_fast"),
        ("win32", "_check_windows_adapter", "winrt.windows.devices.bluetooth"),
    ],
)
async def test_missing_platform_backend_marks_adapter_unavailable(
    monkeypatch: pytest.MonkeyPatch, platform_id: str, checker: str, missing: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform_id)
    monkeypatch.setattr(detection, "_module_available", lambda name: name != missing)

    async def must_not_run(self: BLEAdapterManager) -> AdapterInfo:
        raise AssertionError("platform adapter probe ran without its backend")

    monkeypatch.setattr(BLEAdapterManager, checker, must_not_run)

    info = await BLEAdapterManager().check_adapter()

    assert info.is_available is False
    assert info.is_enabled is False
    assert missing in info.name


async def test_linux_capability_check_failure_is_not_reported_as_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(detection, "_module_available", lambda name: True)

    async def boom() -> Any:
        raise RuntimeError("dbus exploded")

    monkeypatch.setattr("bitchat.platform.capabilities.detect_bluetooth_info", boom)

    info = await BLEAdapterManager()._check_linux_adapter()

    assert info.is_available is False
    assert "dbus exploded" in info.name


@pytest.mark.parametrize(
    ("platform_id", "expected_bluez"),
    [
        ("linux", "Not detected"),
        ("win32", "Not applicable (WinRT)"),
        ("darwin", "Not applicable"),
    ],
)
async def test_capability_report_marks_missing_backend_not_detected(
    monkeypatch: pytest.MonkeyPatch, platform_id: str, expected_bluez: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform_id)
    monkeypatch.setattr(detection, "_module_available", lambda name: False)

    caps = await detect_bluetooth_info()

    assert caps.adapter == "Not detected"
    assert caps.is_central_available is False
    assert caps.is_peripheral_available is False
    assert caps.bluez == expected_bluez


async def test_capability_detection_dispatches_on_central_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(detection, "_module_available", lambda name: True)
    seen: list[str] = []

    async def fake_linux() -> Any:
        seen.append("linux")
        return "linux-caps"

    async def fake_windows() -> Any:
        seen.append("windows")
        return "windows-caps"

    monkeypatch.setattr(
        "bitchat.platform.capabilities._detect_linux_bluetooth", fake_linux
    )
    monkeypatch.setattr(
        "bitchat.platform.capabilities._detect_windows_bluetooth", fake_windows
    )

    monkeypatch.setattr(sys, "platform", "linux")
    assert await detect_bluetooth_info() == "linux-caps"
    monkeypatch.setattr(sys, "platform", "win32")
    assert await detect_bluetooth_info() == "windows-caps"
    monkeypatch.setattr(sys, "platform", "darwin")
    generic = await detect_bluetooth_info()

    assert seen == ["linux", "windows"]
    assert generic.ble_peripheral == "Unsupported"


# ---------------------------------------------------------------------------
# OS-specific recovery guidance lives in the platform layer
# ---------------------------------------------------------------------------


def test_recovery_guidance_is_os_specific_without_cross_contamination() -> None:
    windows = " ".join(recovery.bluetooth_recovery_hints(PlatformKind.WINDOWS))
    linux = " ".join(recovery.bluetooth_recovery_hints(PlatformKind.LINUX))

    assert "Windows Settings" in windows
    assert "bluetoothd" not in windows and "systemctl" not in windows
    assert "bluetoothd" in linux and "Windows" not in linux
    # Distribution-neutral: systemd is mentioned only as an example.
    assert "systemd-based" in linux
    assert "Windows" in recovery.gatt_failure_hint(PlatformKind.WINDOWS)
    assert "Windows" not in recovery.gatt_failure_hint(PlatformKind.LINUX)
    assert recovery.bluetooth_recovery_hints(PlatformKind.OTHER)


def test_recovery_guidance_defaults_to_current_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert recovery.bluetooth_recovery_hints() == recovery.bluetooth_recovery_hints(
        PlatformKind.WINDOWS
    )
    monkeypatch.setattr(sys, "platform", "linux")
    assert recovery.gatt_failure_hint() == recovery.gatt_failure_hint(
        PlatformKind.LINUX
    )
