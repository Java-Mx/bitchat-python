"""Unit tests for the BitChat command parser."""

import pytest

from bitchat.commands.parser import Command, CommandParser, CommandType


@pytest.fixture
def parser() -> CommandParser:
    """Fixture providing a fresh CommandParser."""
    return CommandParser()


class TestCommandParser:
    """Tests for CommandParser behavior."""

    def test_empty_string(self, parser: CommandParser) -> None:
        """Empty input produces an EMPTY command."""
        cmd = parser.parse("")
        assert cmd.command_type == CommandType.EMPTY
        assert cmd.raw_input == ""
        assert cmd.args == []

    def test_whitespace_only(self, parser: CommandParser) -> None:
        """Whitespace-only input produces an EMPTY command."""
        cmd = parser.parse("   \t  \n  ")
        assert cmd.command_type == CommandType.EMPTY
        assert cmd.args == []

    @pytest.mark.parametrize(
        "text",
        [
            "initialize chat",
            "INITIALIZE CHAT",
            "Initialize Chat",
            "  initialize   chat  ",
            "InItIaLiZe ChAt",
        ],
    )
    def test_initialize_chat_command(self, parser: CommandParser, text: str) -> None:
        """'initialize chat' is recognized with arbitrary whitespace."""
        cmd = parser.parse(text)
        assert cmd.command_type == CommandType.INITIALIZE_CHAT
        assert cmd.error_message is None

    def test_initialize_chat_with_extra_args(self, parser: CommandParser) -> None:
        """'initialize chat' preserves trailing arguments if provided."""
        cmd = parser.parse("initialize chat --verbose")
        assert cmd.command_type == CommandType.INITIALIZE_CHAT
        assert cmd.args == ["--verbose"]

    @pytest.mark.parametrize("text", ["help", "HELP", "Help", "  help  ", "?"])
    def test_help_command(self, parser: CommandParser, text: str) -> None:
        """'help' and '?' produce a HELP command."""
        cmd = parser.parse(text)
        assert cmd.command_type == CommandType.HELP
        assert cmd.error_message is None

    def test_help_with_args(self, parser: CommandParser) -> None:
        """'help' preserves subtopic arguments."""
        cmd = parser.parse("help commands")
        assert cmd.command_type == CommandType.HELP
        assert cmd.args == ["commands"]

    @pytest.mark.parametrize(
        "text",
        [
            "exit",
            "EXIT",
            "Exit",
            "quit",
            "QUIT",
            "/exit",
            "/quit",
            "  exit  ",
        ],
    )
    def test_exit_command(self, parser: CommandParser, text: str) -> None:
        """'exit', 'quit', and slash aliases produce an EXIT command."""
        cmd = parser.parse(text)
        assert cmd.command_type == CommandType.EXIT
        assert cmd.error_message is None

    @pytest.mark.parametrize(
        "text",
        [
            "unknown",
            "foo bar",
            "init chat",
            "start",
            "/unknown_slash",
        ],
    )
    def test_unknown_commands(self, parser: CommandParser, text: str) -> None:
        """Unrecognized inputs produce an UNKNOWN command with error description."""
        cmd = parser.parse(text)
        assert cmd.command_type == CommandType.UNKNOWN
        assert cmd.error_message is not None
        assert "Unknown command" in cmd.error_message
        assert cmd.raw_input == text

    def test_command_is_immutable(self) -> None:
        """Command dataclass instances cannot be mutated."""
        cmd = Command(command_type=CommandType.HELP, raw_input="help")
        with pytest.raises(AttributeError):
            cmd.command_type = CommandType.EXIT  # type: ignore[misc]
