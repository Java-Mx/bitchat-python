"""Comprehensive automated tests for settings configuration data flow,
widget rendering, dirty-state detection, save/cancel/reset, and cross-platform parity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from tests.ble.mocks import (
    MockBleakClient,
    MockBleakScanner,
    MockBLEServerBackend,
)
from textual.widgets import Button, Input, RadioButton, Switch

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.mesh.router import MeshRouter
from bitchat.storage.config import (
    DEFAULT_KEYBINDINGS,
    AppConfig,
    FileConfigStorage,
)
from bitchat.tui.app import BitChatApp
from bitchat.tui.screens.home import HomeScreen
from bitchat.tui.screens.settings import (
    SaveStatusIndicator,
    SettingsScreen,
    UnsavedChangesModal,
)
from bitchat.tui.widgets.message_input import MessageInput


@pytest.fixture
def test_identity() -> LocalIdentity:
    return LocalIdentity.generate()


@pytest.fixture
def mock_storage(test_identity: LocalIdentity, tmp_path: Path) -> FileConfigStorage:
    storage = FileConfigStorage(
        config_path=tmp_path / "config.json",
        identity_path=tmp_path / "identity.json",
    )
    storage.save_config(AppConfig(nickname="AliceNode", transport="bluetooth"))
    storage.save_identity(test_identity)
    return storage


def create_coordinator(
    identity: LocalIdentity, storage: FileConfigStorage, nickname: str = "AliceNode"
) -> SessionCoordinator:
    server = BLEServer(backend=MockBLEServerBackend())
    manager = BLEManager(
        sender_id=identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
        client_factory=lambda address, **kw: MockBleakClient(address=address, **kw),
    )
    return SessionCoordinator(
        local_identity=identity,
        ble_manager=manager,
        ble_server=server,
        mesh_router=MeshRouter(identity.peer_id),
        nickname=nickname,
        storage=storage,
    )


# ---------------------------------------------------------------------------
# Test 1: Fresh configuration with documented defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_configuration_documented_defaults(
    test_identity: LocalIdentity, tmp_path: Path
) -> None:
    """Fresh configuration loads documented defaults into all widget controls."""
    storage = FileConfigStorage(
        config_path=tmp_path / "fresh_config.json",
        identity_path=tmp_path / "fresh_identity.json",
    )
    storage.save_identity(test_identity)
    coord = create_coordinator(test_identity, storage, nickname="Anonymous")

    app = BitChatApp(coordinator=coord, storage=storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        app.action_open_settings()
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        screen = app.screen

        # Assert rendered widget values match documented defaults
        nick_inp = screen.query_one("#settings-input-nickname", Input)
        assert nick_inp.value == "Anonymous"

        hops_inp = screen.query_one("#settings-input-hops", Input)
        assert hops_inp.value == "3"

        delay_inp = screen.query_one("#settings-input-delay", Input)
        assert delay_inp.value == "20"

        radio_bt = screen.query_one("#radio-transport-bluetooth", RadioButton)
        assert radio_bt.value is True

        switch_ts = screen.query_one("#settings-switch-timestamps", Switch)
        assert switch_ts.value is True

        radio_dense = screen.query_one("#radio-density-comfortable", RadioButton)
        assert radio_dense.value is True

        radio_accent = screen.query_one("#radio-accent-blue", RadioButton)
        assert radio_accent.value is True

        switch_dbg = screen.query_one("#settings-switch-debug", Switch)
        assert switch_dbg.value is False

        # Fresh open must NOT be dirty
        indicator = screen.query_one(SaveStatusIndicator)
        assert indicator.is_saved is True
        assert screen.has_unsaved_changes is False


# ---------------------------------------------------------------------------
# Test 2: Existing configuration with a custom nickname
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_configuration_with_custom_nickname(
    test_identity: LocalIdentity, tmp_path: Path
) -> None:
    """Existing configuration with custom nickname displays real persisted value."""
    storage = FileConfigStorage(
        config_path=tmp_path / "custom_config.json",
        identity_path=tmp_path / "custom_identity.json",
    )
    custom_cfg = AppConfig(
        nickname="CustomNode_99",
        max_hops=5,
        inter_fragment_delay_ms=45,
        transport="lan",
        density="compact",
        accent="purple",
        show_timestamps=False,
        debug=True,
    )
    storage.save_config(custom_cfg)
    storage.save_identity(test_identity)
    coord = create_coordinator(test_identity, storage, nickname="CustomNode_99")

    app = BitChatApp(coordinator=coord, storage=storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        app.action_open_settings()
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        screen = app.screen

        assert (
            screen.query_one("#settings-input-nickname", Input).value == "CustomNode_99"
        )
        assert screen.query_one("#settings-input-hops", Input).value == "5"
        assert screen.query_one("#settings-input-delay", Input).value == "45"
        assert screen.query_one("#radio-transport-lan", RadioButton).value is True
        assert screen.query_one("#radio-density-compact", RadioButton).value is True
        assert screen.query_one("#radio-accent-purple", RadioButton).value is True
        assert screen.query_one("#settings-switch-timestamps", Switch).value is False
        assert screen.query_one("#settings-switch-debug", Switch).value is True

        # False dirty-check invariant: must be saved immediately upon opening
        assert screen.has_unsaved_changes is False
        assert screen.query_one(SaveStatusIndicator).is_saved is True


# ---------------------------------------------------------------------------
# Test 3: Missing configuration file
# ---------------------------------------------------------------------------


def test_missing_configuration_file(tmp_path: Path) -> None:
    """Missing configuration file falls back to AppConfig defaults without errors."""
    storage = FileConfigStorage(config_path=tmp_path / "non_existent.json")
    cfg = storage.load_config()
    assert cfg.nickname == "Anonymous"
    assert cfg.max_hops == 3
    assert cfg.inter_fragment_delay_ms == 20
    assert cfg.density == "comfortable"
    assert cfg.accent == "blue"
    assert cfg.show_timestamps is True


# ---------------------------------------------------------------------------
# Test 4: Invalid configuration defensive validation
# ---------------------------------------------------------------------------


def test_invalid_configuration_defensive_bounds(tmp_path: Path) -> None:
    """Corrupted config values are safely clamped to defensive ranges."""
    bad_data = {
        "nickname": "   ExtremelyLongNicknameBeyondAllowedLimitExceedingBounds   ",
        "max_hops": 9999,
        "inter_fragment_delay_ms": -100,
        "density": "ultra_spacious",
        "accent": "neon_pink",
        "transport": "carrier_pigeon",
        "keybindings": "not_a_dict",
    }
    cfg = AppConfig.from_dict(bad_data)
    assert len(cfg.nickname) <= 32
    assert cfg.max_hops == 7  # Clamped to upper bound
    assert cfg.inter_fragment_delay_ms == 5  # Clamped to lower bound
    assert cfg.density == "comfortable"
    assert cfg.accent == "blue"
    assert cfg.transport == "bluetooth"
    assert cfg.keybindings == DEFAULT_KEYBINDINGS


# ---------------------------------------------------------------------------
# Test 5: Configuration migration
# ---------------------------------------------------------------------------


def test_configuration_migration_partial_schema(tmp_path: Path) -> None:
    """Partial legacy config preserves custom keys while populating missing ones."""
    legacy_data = {
        "nickname": "OldPeer",
        "debug": True,
    }
    cfg = AppConfig.from_dict(legacy_data)
    assert cfg.nickname == "OldPeer"
    assert cfg.debug is True
    # Migrated defaults
    assert cfg.max_hops == 3
    assert cfg.inter_fragment_delay_ms == 20
    assert cfg.density == "comfortable"
    assert cfg.keybindings == DEFAULT_KEYBINDINGS


# ---------------------------------------------------------------------------
# Test 6: Loading each settings category
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loading_each_settings_category(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """All 8 configuration categories can be selected and display proper sections."""
    coord = create_coordinator(test_identity, mock_storage)
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        app.action_open_settings()
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        screen = app.screen

        categories = [
            "general",
            "identity",
            "bluetooth",
            "network",
            "notifications",
            "appearance",
            "startup",
            "advanced",
        ]
        for cat in categories:
            screen.switch_category(cat)
            await pilot.pause()
            assert screen.active_category == cat
            sec = screen.query_one(f"#section-cat-{cat}")
            assert sec.display is True
            btn = screen.query_one(f"#btn-cat-{cat}", Button)
            assert "active-cat" in btn.classes
            assert str(btn.label).startswith("> ")


@pytest.mark.asyncio
async def test_settings_category_keyboard_navigation_and_focus(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Category keys navigate, activate content, and restore modal focus."""
    coord = create_coordinator(test_identity, mock_storage)
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        chat_input = app.query_one(MessageInput)
        chat_input.focus()
        app.action_open_settings()
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        assert screen.focused is screen.query_one("#btn-cat-general", Button)

        # Up/Down changes the selected category without wrapping at boundaries.
        await pilot.press("up")
        assert screen.selected_category == "general"
        await pilot.press("down")
        assert screen.selected_category == "identity"
        assert screen.active_category == "general"
        await pilot.press("enter")
        await pilot.pause()
        assert screen.active_category == "identity"
        assert screen.query_one("#section-cat-identity").display is True

        await pilot.press("down", "enter")
        await pilot.pause()
        assert screen.active_category == "bluetooth"
        assert screen.query_one("#section-cat-bluetooth").display is True

        await pilot.press("down", "down", "down", "down", "down", "enter")
        await pilot.pause()
        assert screen.selected_category == "advanced"
        assert screen.active_category == "advanced"
        assert screen.query_one("#section-cat-advanced").display is True
        await pilot.press("down")
        assert screen.selected_category == "advanced"  # Boundary stops, no wrap.

        # Left/Right transfer focus between navigation and active content.
        await pilot.press("right")
        assert isinstance(screen.focused, (Input, RadioButton, Switch, Button))
        await pilot.press("left")
        assert screen.focused is screen.query_one("#btn-cat-advanced", Button)

        # Tab order remains available, including reverse traversal.
        await pilot.press("tab")
        next_focus = screen.focused
        assert next_focus is not screen.query_one("#btn-cat-advanced", Button)
        await pilot.press("shift+tab")
        assert screen.focused is screen.query_one("#btn-cat-advanced", Button)

        # Escape dismisses the modal and Textual restores the previous focus.
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)
        assert app.screen.focused is chat_input


@pytest.mark.asyncio
async def test_settings_keyboard_navigation_from_home_screen(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """The modal's navigation works at a smaller size over another screen."""
    coord = create_coordinator(test_identity, mock_storage)
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="home")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)

        app.action_open_settings()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        assert screen.focused is screen.query_one("#btn-cat-general", Button)

        await pilot.press("down", "enter")
        await pilot.pause()
        assert screen.active_category == "identity"
        assert screen.query_one("#section-cat-identity").display is True

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_settings_category_keys_do_not_intercept_text_input(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Arrow keys and text entry remain owned by a focused settings Input."""
    coord = create_coordinator(test_identity, mock_storage)
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        app.action_open_settings()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)

        await pilot.press("right")
        nickname = screen.query_one("#settings-input-nickname", Input)
        assert screen.focused is nickname
        active_category = screen.active_category
        selected_category = screen.selected_category

        await pilot.press("left", "x")
        await pilot.pause()
        assert screen.focused is nickname
        assert screen.active_category == active_category
        assert screen.selected_category == selected_category
        assert "x" in nickname.value


# ---------------------------------------------------------------------------
# Test 7: Switching between categories preserves unsaved input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switching_categories_preserves_unsaved_input(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Switching categories never erases unsaved user inputs in other sections."""
    coord = create_coordinator(test_identity, mock_storage)
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        app.action_open_settings()
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        screen = app.screen

        # 1. Edit nickname in General
        nick_inp = screen.query_one("#settings-input-nickname", Input)
        nick_inp.value = "Unsaved_Alice"
        await pilot.pause()
        assert screen.has_unsaved_changes is True

        # 2. Switch away to Appearance
        screen.switch_category("appearance")
        await pilot.pause()

        # 3. Switch away to Advanced
        screen.switch_category("advanced")
        await pilot.pause()

        # 4. Switch back to General
        screen.switch_category("general")
        await pilot.pause()

        # Input must still retain edited value
        assert (
            screen.query_one("#settings-input-nickname", Input).value == "Unsaved_Alice"
        )
        assert screen.has_unsaved_changes is True


# ---------------------------------------------------------------------------
# Test 8: Editing a setting marks dirty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_editing_a_setting_marks_dirty(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Modifying a control transitions status indicator to unsaved changes."""
    coord = create_coordinator(test_identity, mock_storage)
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        app.action_open_settings()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        assert screen.has_unsaved_changes is False

        hops_inp = screen.query_one("#settings-input-hops", Input)
        hops_inp.value = "6"
        await pilot.pause()

        assert screen.has_unsaved_changes is True
        indicator = screen.query_one(SaveStatusIndicator)
        assert indicator.is_saved is False
        assert "UNSAVED CHANGES" in str(indicator.render())


# ---------------------------------------------------------------------------
# Test 9: Returning a setting to original value clears dirty state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returning_to_original_value_clears_dirty(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Restoring input to match original persisted snapshot clears dirty flag."""
    coord = create_coordinator(test_identity, mock_storage, nickname="AliceNode")
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        app.action_open_settings()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)

        nick_inp = screen.query_one("#settings-input-nickname", Input)
        assert nick_inp.value == "AliceNode"
        assert screen.has_unsaved_changes is False

        # Modify
        nick_inp.value = "TemporaryAlice"
        await pilot.pause()
        assert screen.has_unsaved_changes is True

        # Restore exact original value
        nick_inp.value = "AliceNode"
        await pilot.pause()
        assert screen.has_unsaved_changes is False
        indicator = screen.query_one(SaveStatusIndicator)
        assert indicator.is_saved is True
        assert "ALL CHANGES SAVED" in str(indicator.render())


# ---------------------------------------------------------------------------
# Test 10: Saving successfully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saving_successfully_persists_and_updates_state(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Saving writes atomically to disk, updates coordinator, and clears dirty."""
    coord = create_coordinator(test_identity, mock_storage, nickname="AliceNode")
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        app.action_open_settings()
        await pilot.pause()
        screen = app.screen

        # Make modifications
        screen.query_one("#settings-input-nickname", Input).value = "Alice_Saved"
        screen.query_one("#settings-input-hops", Input).value = "4"
        screen.query_one("#settings-input-delay", Input).value = "35"
        await pilot.pause()

        # Click save
        await pilot.click("#btn-settings-save")
        await pilot.pause()

        # Modal is dismissed
        assert not isinstance(app.screen, SettingsScreen)

        # Check persisted file
        reloaded = mock_storage.load_config()
        assert reloaded.nickname == "Alice_Saved"
        assert reloaded.max_hops == 4
        assert reloaded.inter_fragment_delay_ms == 35
        assert app.config.nickname == "Alice_Saved"

        # Check coordinator runtime state
        assert coord.nickname == "Alice_Saved"
        assert coord.mesh_router.max_relay_ttl == 4
        assert coord.inter_fragment_delay == 0.035

    restarted_coord = create_coordinator(
        test_identity, mock_storage, nickname="Anonymous"
    )
    restarted_app = BitChatApp(
        coordinator=restarted_coord,
        storage=mock_storage,
        initial_screen="chat",
    )
    async with restarted_app.run_test(size=(120, 45)) as pilot:
        restarted_app.action_open_settings()
        await pilot.pause()
        assert (
            restarted_app.screen.query_one("#settings-input-nickname", Input).value
            == "Alice_Saved"
        )


# ---------------------------------------------------------------------------
# Test 11: Saving failure keeps dirty state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saving_failure_preserves_dirty_state(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Filesystem save failure retains unsaved status and does not dismiss."""
    coord = create_coordinator(test_identity, mock_storage)
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        app.action_open_settings()
        await pilot.pause()
        screen = app.screen

        screen.query_one("#settings-input-nickname", Input).value = "FailSaveNick"
        await pilot.pause()

        with patch.object(
            mock_storage, "save_config", side_effect=OSError("Read-only filesystem")
        ):
            await pilot.click("#btn-settings-save")
            await pilot.pause()

        # Screen remains open with error indicator
        assert isinstance(app.screen, SettingsScreen)
        assert app.screen.has_unsaved_changes is True
        indicator = screen.query_one(SaveStatusIndicator)
        assert indicator.is_saved is False


# ---------------------------------------------------------------------------
# Test 12: Canceling changes with and without confirmation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_canceling_changes(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Canceling without changes closes directly; with changes prompts modal."""
    coord = create_coordinator(test_identity, mock_storage)
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        # Case A: Clean cancel closes immediately
        app.action_open_settings()
        await pilot.pause()
        await pilot.click("#btn-settings-cancel")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)

        # Case B: Dirty cancel prompts confirmation
        app.action_open_settings()
        await pilot.pause()
        screen = app.screen
        screen.query_one("#settings-input-nickname", Input).value = "DirtyCancel"
        await pilot.pause()

        await pilot.click("#btn-settings-cancel")
        await pilot.pause()
        assert isinstance(app.screen, UnsavedChangesModal)

        # Click keep editing
        await pilot.click("#btn-unsaved-stay")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)

        # Click cancel again and discard
        await pilot.click("#btn-settings-cancel")
        await pilot.pause()
        assert isinstance(app.screen, UnsavedChangesModal)
        await pilot.click("#btn-unsaved-discard")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)

        # Storage was not updated
        assert mock_storage.load_config().nickname == "AliceNode"


# ---------------------------------------------------------------------------
# Test 13: Resetting settings to defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resetting_settings_to_defaults(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Resetting restores documented defaults without touching cryptographic identity."""
    orig_fp = test_identity.fingerprint
    coord = create_coordinator(test_identity, mock_storage, nickname="CustomNode")
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        app.action_open_settings()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)

        # Click reset
        await pilot.click("#btn-settings-restore-defaults")
        await pilot.pause()

        assert screen.query_one("#settings-input-nickname", Input).value == "Anonymous"
        assert screen.query_one("#settings-input-hops", Input).value == "3"
        assert screen.query_one("#settings-input-delay", Input).value == "20"
        assert screen.query_one("#radio-transport-bluetooth", RadioButton).value is True
        assert screen.has_unsaved_changes is True

        # Identity file is completely untouched
        stored_ident = mock_storage.load_identity()
        assert stored_ident is not None
        assert stored_ident.fingerprint == orig_fp


# ---------------------------------------------------------------------------
# Test 14: Restarting and reloading persisted settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restarting_and_reloading_persisted_settings(
    test_identity: LocalIdentity, tmp_path: Path
) -> None:
    """Settings persisted survive application teardown and reload identically."""
    cfg_file = tmp_path / "persist_test.json"
    ident_file = tmp_path / "persist_ident.json"

    storage1 = FileConfigStorage(config_path=cfg_file, identity_path=ident_file)
    storage1.save_identity(test_identity)
    storage1.save_config(
        AppConfig(
            nickname="PersistentNode",
            max_hops=6,
            inter_fragment_delay_ms=75,
            density="compact",
            accent="emerald",
        )
    )

    # Launch second session
    storage2 = FileConfigStorage(config_path=cfg_file, identity_path=ident_file)
    coord2 = create_coordinator(test_identity, storage2, nickname="PersistentNode")
    app2 = BitChatApp(coordinator=coord2, storage=storage2, initial_screen="chat")

    async with app2.run_test(size=(120, 45)) as pilot:
        app2.action_open_settings()
        await pilot.pause()
        screen = app2.screen
        assert isinstance(screen, SettingsScreen)

        assert (
            screen.query_one("#settings-input-nickname", Input).value
            == "PersistentNode"
        )
        assert screen.query_one("#settings-input-hops", Input).value == "6"
        assert screen.query_one("#settings-input-delay", Input).value == "75"
        assert screen.query_one("#radio-density-compact", RadioButton).value is True
        assert screen.query_one("#radio-accent-emerald", RadioButton).value is True
        assert screen.has_unsaved_changes is False


# ---------------------------------------------------------------------------
# Test 15: Unsaved-change confirmation dialog buttons
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsaved_changes_modal_buttons_and_bindings() -> None:
    """UnsavedChangesModal presents distinct visible buttons and safe escape behavior."""
    modal = UnsavedChangesModal()
    app = BitChatApp(initial_screen="chat")
    async with app.run_test(size=(100, 32)) as pilot:
        app.push_screen(modal)
        await pilot.pause()

        # Both buttons are present and have explicit readable labels
        btn_discard = modal.query_one("#btn-unsaved-discard", Button)
        btn_stay = modal.query_one("#btn-unsaved-stay", Button)
        assert str(btn_discard.label) == "Discard Changes"
        assert str(btn_stay.label) == "Keep Editing"

        # Pressing escape keeps editing (safe cancel)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, UnsavedChangesModal)
