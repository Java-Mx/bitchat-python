"""BitChat CLI / TUI entry point bootstrap."""

import argparse
import sys

from bitchat import __version__
from bitchat.app.application import Application


def main() -> None:
    """Bootstrap and run the BitChat application."""
    parser = argparse.ArgumentParser(
        prog="bitchat", description="BitChat BLE Messenger"
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
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
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Run system configuration, hardware detection, and diagnostics",
    )
    parser.add_argument(
        "--startup",
        choices=["enable", "disable", "status"],
        help="Manage per-user Windows sign-in startup (enable, disable, status)",
    )
    parser.add_argument(
        "--startup-launch",
        action="store_true",
        help="Internal flag for Windows Startup shortcut to prevent duplicates",
    )
    args = parser.parse_args()

    if args.startup:
        from bitchat.platform.startup import (
            disable_startup,
            enable_startup,
            format_startup_status,
        )

        if args.startup == "enable":
            shortcut = enable_startup()
            print(f"Enabled BitChat Windows sign-in startup shortcut:\n  {shortcut}")
        elif args.startup == "disable":
            removed = disable_startup()
            if removed:
                print("Disabled BitChat Windows sign-in startup (shortcut removed).")
            else:
                print("BitChat Windows sign-in startup was already disabled.")
        else:
            print(format_startup_status())
        sys.exit(0)

    if args.configure:
        import asyncio
        import contextlib

        from bitchat.platform.capabilities import (
            detect_system_capabilities,
            format_configure_report,
        )

        reconfigure_fn = getattr(sys.stdout, "reconfigure", None)
        if callable(reconfigure_fn):
            with contextlib.suppress(Exception):
                reconfigure_fn(encoding="utf-8", errors="replace")

        report = asyncio.run(detect_system_capabilities())
        print(format_configure_report(report))
        sys.exit(0)

    from bitchat.platform.startup import SingleInstanceGuard

    with SingleInstanceGuard() as instance_guard:
        if args.startup_launch and instance_guard.already_running:
            print(
                "BitChat is already running for the current user; "
                "skipping duplicate startup launch."
            )
            sys.exit(0)

        use_cli = args.cli or (not args.tui and not sys.stdin.isatty())

        if use_cli:
            app = Application(enable_ble=True)
            exit_code = app.run()
            sys.exit(exit_code)
        else:
            from bitchat.app.session_coordinator import SessionCoordinator
            from bitchat.ble.manager import BLEManager
            from bitchat.ble.server import BLEServer
            from bitchat.storage.config import FileConfigStorage
            from bitchat.tui.app import BitChatApp

            storage = FileConfigStorage()
            config = storage.load_config()
            identity = storage.load_or_create_identity()

            server = BLEServer()
            manager = BLEManager(sender_id=identity.peer_id)
            coordinator = SessionCoordinator(
                local_identity=identity,
                ble_manager=manager,
                ble_server=server,
                storage=storage,
                nickname=config.nickname,
            )

            tui_app = BitChatApp(coordinator=coordinator, storage=storage)
            tui_app.run()
            sys.exit(0)


if __name__ == "__main__":
    main()
