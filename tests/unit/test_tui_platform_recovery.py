"""TUI recovery dialog: OS-specific guidance comes from the platform layer."""

from __future__ import annotations

import sys

import pytest
from textual.widgets import Button, Static

from bitchat.tui.app import BitChatApp
from bitchat.tui.screens.ble_error import BLEErrorModal


def _dialog_text(app: BitChatApp) -> str:
    return " ".join(
        str(widget.content)
        for widget in app.screen.query(".ble-error-text").results(Static)
    )


def _button_labels(app: BitChatApp) -> list[str]:
    return [str(b.label) for b in app.screen.query(Button)]


@pytest.mark.parametrize(
    ("platform_id", "expected", "forbidden"),
    [
        ("linux", "bluetoothd", "Windows"),
        ("win32", "Windows Settings", "bluetoothd"),
    ],
)
async def test_hardware_error_dialog_guidance_matches_platform(
    monkeypatch: pytest.MonkeyPatch, platform_id: str, expected: str, forbidden: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform_id)
    app = BitChatApp()
    async with app.run_test() as pilot:
        await app.push_screen(BLEErrorModal(error_message="No adapter"))
        await pilot.pause()

        text = _dialog_text(app)
        assert expected in text
        assert forbidden not in text
        # Missing hardware must never show the GATT-specific explanation.
        assert "GATT" not in text


@pytest.mark.parametrize(
    ("platform_id", "expected", "forbidden"),
    [
        ("linux", "BlueZ", "Windows"),
        ("win32", "Windows can abort GATT advertising", "BlueZ"),
    ],
)
async def test_gatt_failure_dialog_guidance_matches_platform(
    monkeypatch: pytest.MonkeyPatch, platform_id: str, expected: str, forbidden: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform_id)
    app = BitChatApp()
    async with app.run_test() as pilot:
        await app.push_screen(
            BLEErrorModal(
                error_message="GATT failed",
                bluetooth_available=True,
                peripheral_supported=True,
            )
        )
        await pilot.pause()

        text = _dialog_text(app)
        assert expected in text
        assert forbidden not in text
        assert _button_labels(app) == [
            "Retry Adapter",
            "Continue Wi-Fi/LAN",
            "Continue Offline",
        ]
