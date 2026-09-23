"""BitChat CLI / TUI entry point bootstrap."""

import argparse
import sys

from bitchat.app.application import Application


def main() -> None:
    """Bootstrap and run the BitChat application."""
    parser = argparse.ArgumentParser(description="BitChat BLE Messenger")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in headless / CLI mode instead of interactive TUI",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Force interactive TUI mode even if stdin is not a TTY",
    )
    args = parser.parse_args()

    use_cli = args.cli or (not args.tui and not sys.stdin.isatty())

    if use_cli:
        app = Application(enable_ble=True)
        exit_code = app.run()
        sys.exit(exit_code)
    else:
        from bitchat.app.session_coordinator import SessionCoordinator
        from bitchat.ble.manager import BLEManager
        from bitchat.ble.server import BLEServer
        from bitchat.crypto.identity import LocalIdentity
        from bitchat.storage.config import FileConfigStorage
        from bitchat.tui.app import BitChatApp

        storage = FileConfigStorage()
        config = storage.load_config()
        identity = storage.load_identity()
        if identity is None:
            identity = LocalIdentity.generate()
            storage.save_identity(identity)

        server = BLEServer()
        manager = BLEManager(sender_id=identity.peer_id)
        coordinator = SessionCoordinator(
            local_identity=identity,
            ble_manager=manager,
            ble_server=server,
            storage=storage,
            nickname=config.nickname,
        )

        tui_app = BitChatApp(coordinator=coordinator)
        tui_app.run()
        sys.exit(0)


if __name__ == "__main__":
    main()
