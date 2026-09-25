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

    def test_phase8_commands(self, parser: CommandParser) -> None:
        """Phase 8 commands parse correctly with arguments."""
        # /connect
        c1 = parser.parse("/connect AA:BB:CC:DD:EE:01")
        assert c1.command_type == CommandType.CONNECT
        assert c1.args == ["AA:BB:CC:DD:EE:01"]

        c1_err = parser.parse("/connect")
        assert c1_err.command_type == CommandType.CONNECT
        assert c1_err.error_message is not None

        # /disconnect
        c2 = parser.parse("/disconnect AA:BB:CC:DD:EE:01")
        assert c2.command_type == CommandType.DISCONNECT
        assert c2.args == ["AA:BB:CC:DD:EE:01"]

        # /scan
        c3 = parser.parse("/scan")
        assert c3.command_type == CommandType.SCAN

        # /online
        c4 = parser.parse("/online")
        assert c4.command_type == CommandType.ONLINE
        c4b = parser.parse("/peers")
        assert c4b.command_type == CommandType.ONLINE

        # /name
        c5 = parser.parse("/name Alice")
        assert c5.command_type == CommandType.NAME
        assert c5.args == ["Alice"]

        # /dm
        c6 = parser.parse("/dm Bob hello world from Alice")
        assert c6.command_type == CommandType.DM
        assert c6.args == ["Bob", "hello world from Alice"]

        c6_err = parser.parse("/dm Bob")
        assert c6_err.command_type == CommandType.DM
        assert c6_err.error_message is not None

        # /large
        c7 = parser.parse("/large Bob")
        assert c7.command_type == CommandType.LARGE
        assert c7.args == ["Bob"]

        # /clear
        c8 = parser.parse("/clear")
        assert c8.command_type == CommandType.CLEAR

    def test_command_is_immutable(self) -> None:
        """Command dataclass instances cannot be mutated."""
        cmd = Command(command_type=CommandType.HELP, raw_input="help")
        with pytest.raises(AttributeError):
            cmd.command_type = CommandType.EXIT  # type: ignore[misc]

    def test_command_registry_and_suggestions(self) -> None:
        """Command registry contains specifications and filters suggestions."""
        from bitchat.commands.parser import COMMAND_REGISTRY, get_command_suggestions

        assert len(COMMAND_REGISTRY) >= 10
        names = [spec.name for spec in COMMAND_REGISTRY]
        assert "/connect" in names
        assert "/dm" in names
        assert "/help" in names

        # Suggestion filtering
        all_sug = get_command_suggestions("/")
        assert len(all_sug) == len(COMMAND_REGISTRY)

        co_sug = get_command_suggestions("/co")
        assert len(co_sug) == 1
        assert co_sug[0].name == "/connect"

        d_sug = get_command_suggestions("/d")
        d_names = [s.name for s in d_sug]
        assert "/dm" in d_names
        assert "/disconnect" in d_names

        empty_sug = get_command_suggestions("hello")
        assert len(empty_sug) == 0

    def test_at_peer_direct_message_syntax(self, parser: CommandParser) -> None:
        """@peer <message> syntax parses into DM command."""
        cmd1 = parser.parse("@alice Hello Alice!")
        assert cmd1.command_type == CommandType.DM
        assert cmd1.args == ["alice", "Hello Alice!"]
        assert cmd1.error_message is None

        cmd2 = parser.parse("@cafebabe12345678 Encrypted packet data")
        assert cmd2.command_type == CommandType.DM
        assert cmd2.args == ["cafebabe12345678", "Encrypted packet data"]

        # Missing body
        cmd_err1 = parser.parse("@alice")
        assert cmd_err1.command_type == CommandType.DM
        assert cmd_err1.error_message is not None

        # Just '@'
        cmd_err2 = parser.parse("@")
        assert cmd_err2.command_type == CommandType.DM
        assert cmd_err2.error_message is not None

    def test_phase92_management_commands(self, parser: CommandParser) -> None:
        """Phase 9.2 management commands parse properly."""
        # /settings & aliases
        c_set1 = parser.parse("/settings")
        assert c_set1.command_type == CommandType.SETTINGS
        c_set2 = parser.parse("/config")
        assert c_set2.command_type == CommandType.SETTINGS

        # /edit & aliases
        c_edit1 = parser.parse("/edit")
        assert c_edit1.command_type == CommandType.EDIT
        c_edit2 = parser.parse("/theme")
        assert c_edit2.command_type == CommandType.EDIT
        c_edit3 = parser.parse("/appearance")
        assert c_edit3.command_type == CommandType.EDIT

        # /status & aliases
        c_stat1 = parser.parse("/status")
        assert c_stat1.command_type == CommandType.STATUS
        c_stat2 = parser.parse("/diag")
        assert c_stat2.command_type == CommandType.STATUS

        # /public & aliases
        c_pub1 = parser.parse("/public")
        assert c_pub1.command_type == CommandType.PUBLIC
        c_pub2 = parser.parse("/channel")
        assert c_pub2.command_type == CommandType.PUBLIC

        # /info
        c_info = parser.parse("/info Bob")
        assert c_info.command_type == CommandType.INFO
        assert c_info.args == ["Bob"]

        c_info_err = parser.parse("/info")
        assert c_info_err.command_type == CommandType.INFO
        assert c_info_err.error_message is not None

    def test_phase11_transport_command(self, parser: CommandParser) -> None:
        """Phase 11 /transport command and aliases."""
        c1 = parser.parse("/transport")
        assert c1.command_type == CommandType.TRANSPORT
        assert c1.args == []

        c2 = parser.parse("/transport lan")
        assert c2.command_type == CommandType.TRANSPORT
        assert c2.args == ["lan"]

        c3 = parser.parse("/transport bluetooth")
        assert c3.command_type == CommandType.TRANSPORT
        assert c3.args == ["bluetooth"]

        c4 = parser.parse("/medium lan")
        assert c4.command_type == CommandType.TRANSPORT
        assert c4.args == ["lan"]
