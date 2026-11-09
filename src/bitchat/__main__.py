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
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help=(
            "Uninstall BitChat binaries, console-script launchers, "
            "shortcuts, and PATH entries"
        ),
    )
    parser.add_argument(
        "--remove-user-data",
        "--purge",
        dest="remove_user_data",
        action="store_true",
        help=(
            "Also delete BitChat user data, identity keys, configuration, "
            "and caches (~/.bitchat)"
        ),
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=(
            "Confirm uninstallation (and user data deletion when combined "
            "with --remove-user-data)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview uninstallation actions without modifying the system",
    )
    args = parser.parse_args()

    if args.uninstall:
        from bitchat.platform.uninstaller import (
            format_uninstall_report,
            run_uninstaller,
        )

        if args.remove_user_data and not args.yes and not args.dry_run:
            if not sys.stdin.isatty():
                print(
                    "Error: Deleting user data (--remove-user-data / --purge) in "
                    "non-interactive mode requires explicit confirmation via --yes.",
                    file=sys.stderr,
                )
                sys.exit(2)
            reply = (
                input(
                    "WARNING: This will permanently delete your BitChat identity keys, "
                    "configuration, and history in ~/.bitchat. Continue? [y/N]: "
                )
                .strip()
                .lower()
            )
            if reply not in {"y", "yes"}:
                print("Uninstallation cancelled; user data was not modified.")
                sys.exit(1)

        report = run_uninstaller(
            remove_user_data=bool(args.remove_user_data),
            dry_run=bool(args.dry_run),
        )
        print(format_uninstall_report(report))
        sys.exit(0 if report.succeeded else 1)

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
        if instance_guard.already_running:
            if args.startup_launch:
                print(
                    "BitChat is already running for the current user; "
                    "skipping duplicate startup launch."
                )
            else:
                instance_guard.activate_existing_instance()
                print("BitChat is already running for this user.")
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
            from bitchat.crypto.identity import LocalIdentity
            from bitchat.storage.config import FileConfigStorage
            from bitchat.tui.app import BitChatApp

            storage = FileConfigStorage()
            config = storage.load_config()
            if config.security_mode == "maximum":
                # Maximum Security: Generate a fresh advertised session peer ID
                # and ephemeral keys on each fresh application launch.
                # The persistent identity.json on disk is preserved intact.
                identity = LocalIdentity.generate()
            else:
                identity = storage.load_or_create_identity()

            server = BLEServer()
            manager = BLEManager(sender_id=identity.peer_id)
            coordinator = SessionCoordinator(
                local_identity=identity,
                ble_manager=manager,
                ble_server=server,
                storage=storage,
                nickname=config.nickname,
                initial_transport=config.transport,
                lan_tcp_port=config.lan_tcp_port,
                lan_discovery_port=config.lan_discovery_port,
            )

            tui_app = BitChatApp(
                coordinator=coordinator,
                storage=storage,
                initial_screen="home",
            )
            tui_app.run()
            sys.exit(0)


if __name__ == "__main__":
    main()
