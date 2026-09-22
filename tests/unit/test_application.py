"""Unit tests for the BitChat Application controller."""

import io

import pytest

from bitchat.app.application import Application
from bitchat.commands.parser import CommandParser
from bitchat.exceptions import ApplicationError, ConfigurationError
from bitchat.storage.config import AppConfig, InMemoryStorage


class FailingStorage(InMemoryStorage):
    """Storage test double that raises ConfigurationError on load."""

    def load_config(self) -> AppConfig:
        raise ConfigurationError("Simulated storage read failure")


class TestApplication:
    """Tests for the Application lifecycle and command execution."""

    def test_startup_and_banner_output(self) -> None:
        """Startup sets running state and writes initial header."""
        out = io.StringIO()
        app = Application(
            storage=InMemoryStorage(),
            stdin=io.StringIO(),
            stdout=out,
        )
        app.startup()
        assert app.is_running is True
        output = out.getvalue()
        assert "BitChat" in output
        assert "No chat session initialized" in output
        assert "Available commands: initialize chat, help, exit" in output

    def test_startup_when_already_running_raises_error(self) -> None:
        """Calling startup on an already running application raises ApplicationError."""
        app = Application(
            storage=InMemoryStorage(),
            stdin=io.StringIO(),
            stdout=io.StringIO(),
        )
        app.startup()
        with pytest.raises(ApplicationError, match="already running"):
            app.startup()

    def test_shutdown_resets_running_state(self) -> None:
        """Shutdown marks the application as stopped and writes farewell."""
        out = io.StringIO()
        storage = InMemoryStorage()
        app = Application(
            storage=storage,
            stdin=io.StringIO(),
            stdout=out,
        )
        app.startup()
        app.shutdown()
        assert app.is_running is False
        assert "Goodbye!" in out.getvalue()

    def test_run_with_empty_input_exits_cleanly(self) -> None:
        """An empty input stream (immediate EOF) exits cleanly with code 0."""
        out = io.StringIO()
        app = Application(
            storage=InMemoryStorage(),
            stdin=io.StringIO(""),
            stdout=out,
        )
        exit_code = app.run()
        assert exit_code == 0
        assert "BitChat" in out.getvalue()
        assert "Goodbye!" in out.getvalue()

    def test_run_with_exit_command(self) -> None:
        """'exit' command terminates the application loop with code 0."""
        out = io.StringIO()
        app = Application(
            storage=InMemoryStorage(),
            stdin=io.StringIO("exit\n"),
            stdout=out,
        )
        exit_code = app.run()
        assert exit_code == 0
        assert "Goodbye!" in out.getvalue()

    def test_run_with_initialize_chat(self) -> None:
        """'initialize chat' marks the chat session as initialized."""
        out = io.StringIO()
        app = Application(
            storage=InMemoryStorage(),
            stdin=io.StringIO("initialize chat\nexit\n"),
            stdout=out,
        )
        assert app.is_chat_initialized is False
        exit_code = app.run()
        assert exit_code == 0
        assert app.is_chat_initialized is True
        output = out.getvalue()
        assert "Chat initialized" in output

    def test_run_with_help_command(self) -> None:
        """'help' command outputs available commands list."""
        out = io.StringIO()
        app = Application(
            storage=InMemoryStorage(),
            stdin=io.StringIO("help\nexit\n"),
            stdout=out,
        )
        exit_code = app.run()
        assert exit_code == 0
        output = out.getvalue()
        assert "Available commands:" in output
        assert "initialize chat" in output
        assert "exit" in output

    def test_run_with_unknown_command(self) -> None:
        """Unknown commands output an informative message without terminating."""
        out = io.StringIO()
        app = Application(
            storage=InMemoryStorage(),
            stdin=io.StringIO("invalid_cmd\nexit\n"),
            stdout=out,
        )
        exit_code = app.run()
        assert exit_code == 0
        output = out.getvalue()
        assert "Unknown command: 'invalid_cmd'" in output
        assert "Goodbye!" in output

    def test_startup_handles_configuration_error_gracefully(self) -> None:
        """If config fails to load, a warning is printed and default config is used."""
        out = io.StringIO()
        app = Application(
            storage=FailingStorage(),
            stdin=io.StringIO("exit\n"),
            stdout=out,
        )
        exit_code = app.run()
        assert exit_code == 0
        output = out.getvalue()
        assert "Warning: Failed to load configuration" in output
        assert app.config is not None
        assert app.config.nickname == "Anonymous"

    def test_custom_command_parser_injection(self) -> None:
        """Custom command parser instances can be injected."""
        custom_parser = CommandParser()
        app = Application(
            storage=InMemoryStorage(),
            command_parser=custom_parser,
            stdin=io.StringIO("exit\n"),
            stdout=io.StringIO(),
        )
        assert app.command_parser is custom_parser
