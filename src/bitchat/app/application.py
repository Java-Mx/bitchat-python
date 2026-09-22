"""Application controller managing lifecycle and command dispatch."""

import sys
from typing import TextIO

from bitchat.commands.parser import Command, CommandParser, CommandType
from bitchat.exceptions import ApplicationError, ConfigurationError
from bitchat.storage.config import AppConfig, FileConfigStorage, StorageInterface


class Application:
    """Core application controller managing lifecycle and command dispatch."""

    def __init__(
        self,
        storage: StorageInterface | None = None,
        command_parser: CommandParser | None = None,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        self.storage: StorageInterface = storage or FileConfigStorage()
        self.command_parser: CommandParser = command_parser or CommandParser()
        self.stdin: TextIO = stdin or sys.stdin
        self.stdout: TextIO = stdout or sys.stdout
        self.is_running: bool = False
        self.is_chat_initialized: bool = False
        self.config: AppConfig | None = None

    def startup(self) -> None:
        """Initialize configuration and start the application lifecycle."""
        if self.is_running:
            raise ApplicationError("Application is already running.")
        try:
            self.config = self.storage.load_config()
        except ConfigurationError as e:
            self.stdout.write(f"Warning: Failed to load configuration: {e}\n")
            self.config = AppConfig()

        self.is_running = True
        self.stdout.write("BitChat\n")
        self.stdout.write(
            "No chat session initialized. Available commands: "
            "initialize chat, help, exit\n"
        )
        self.stdout.flush()

    def shutdown(self) -> None:
        """Perform clean application shutdown."""
        if not self.is_running:
            return
        self.is_running = False
        self.storage.close()
        self.stdout.write("Goodbye!\n")
        self.stdout.flush()

    def dispatch(self, command: Command) -> bool:
        """Dispatch a parsed command.

        Returns True if the application should continue running, or False to exit.
        """
        match command.command_type:
            case CommandType.INITIALIZE_CHAT:
                return self._handle_initialize_chat(command)
            case CommandType.HELP:
                return self._handle_help(command)
            case CommandType.EXIT:
                return self._handle_exit(command)
            case CommandType.EMPTY:
                return True
            case CommandType.UNKNOWN:
                return self._handle_unknown(command)

    def _handle_initialize_chat(self, command: Command) -> bool:
        self.is_chat_initialized = True
        self.stdout.write(
            "Chat initialized. (Network and messaging features will be available "
            "in future phases.)\n"
        )
        self.stdout.flush()
        return True

    def _handle_help(self, command: Command) -> bool:
        self.stdout.write("Available commands:\n")
        self.stdout.write("  initialize chat - Initialize a chat session\n")
        self.stdout.write("  help            - Show this help message\n")
        self.stdout.write("  exit            - Exit the application\n")
        self.stdout.flush()
        return True

    def _handle_exit(self, command: Command) -> bool:
        return False

    def _handle_unknown(self, command: Command) -> bool:
        msg = command.error_message or f"Unknown command: '{command.raw_input}'"
        self.stdout.write(f"{msg}\n")
        self.stdout.flush()
        return True

    def run(self) -> int:
        """Run the complete application lifecycle.

        startup -> command loop -> command dispatch -> shutdown.
        Returns exit code 0 on normal exit.
        """
        self.startup()
        try:
            while self.is_running:
                self.stdout.write("> ")
                self.stdout.flush()
                try:
                    line = self.stdin.readline()
                except (KeyboardInterrupt, EOFError):
                    break
                if not line:  # EOF encountered
                    break
                command = self.command_parser.parse(line)
                should_continue = self.dispatch(command)
                if not should_continue:
                    break
        finally:
            self.shutdown()
        return 0
