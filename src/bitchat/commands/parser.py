"""Command parser for the BitChat CLI."""

from dataclasses import dataclass, field
from enum import StrEnum


class CommandType(StrEnum):
    """Supported command types."""

    INITIALIZE_CHAT = "initialize_chat"
    HELP = "help"
    EXIT = "exit"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    SCAN = "scan"
    ONLINE = "online"
    NAME = "name"
    DM = "dm"
    LARGE = "large"
    CLEAR = "clear"
    EMPTY = "empty"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Command:
    """Structured representation of a parsed command."""

    command_type: CommandType
    raw_input: str
    args: list[str] = field(default_factory=list)
    error_message: str | None = None


class CommandParser:
    """Parses text input into structured Command objects."""

    def parse(self, text: str) -> Command:
        """Parse a line of text into a Command."""
        stripped = text.strip()
        if not stripped:
            return Command(command_type=CommandType.EMPTY, raw_input=text)

        tokens = stripped.split()
        normalized_tokens = [t.lower() for t in tokens]

        # Multi-word command: 'initialize chat'
        if len(normalized_tokens) >= 2 and normalized_tokens[:2] == [
            "initialize",
            "chat",
        ]:
            return Command(
                command_type=CommandType.INITIALIZE_CHAT,
                raw_input=text,
                args=tokens[2:],
            )

        first_token = normalized_tokens[0]

        if first_token in ("help", "?", "/help", "/?"):
            return Command(
                command_type=CommandType.HELP,
                raw_input=text,
                args=tokens[1:],
            )

        if first_token in ("exit", "quit", "/exit", "/quit"):
            return Command(
                command_type=CommandType.EXIT,
                raw_input=text,
                args=tokens[1:],
            )

        if first_token in ("connect", "/connect"):
            if len(tokens) < 2:
                return Command(
                    command_type=CommandType.CONNECT,
                    raw_input=text,
                    error_message="Usage: /connect <peer_address_or_id>",
                )
            return Command(
                command_type=CommandType.CONNECT,
                raw_input=text,
                args=[tokens[1]],
            )

        if first_token in ("disconnect", "/disconnect"):
            target = tokens[1] if len(tokens) > 1 else ""
            return Command(
                command_type=CommandType.DISCONNECT,
                raw_input=text,
                args=[target] if target else [],
            )

        if first_token in ("scan", "/scan"):
            return Command(
                command_type=CommandType.SCAN,
                raw_input=text,
                args=tokens[1:],
            )

        if first_token in ("online", "/online", "peers", "/peers"):
            return Command(
                command_type=CommandType.ONLINE,
                raw_input=text,
                args=tokens[1:],
            )

        if first_token in ("name", "/name", "nick", "/nick"):
            if len(tokens) < 2:
                return Command(
                    command_type=CommandType.NAME,
                    raw_input=text,
                    error_message="Usage: /name <nickname>",
                )
            return Command(
                command_type=CommandType.NAME,
                raw_input=text,
                args=[tokens[1]],
            )

        if first_token in ("dm", "/dm", "msg", "/msg"):
            if len(tokens) < 3:
                return Command(
                    command_type=CommandType.DM,
                    raw_input=text,
                    error_message="Usage: /dm <peer> <message>",
                )
            # Split maxsplit=2 to preserve message spaces
            parts = stripped.split(maxsplit=2)
            return Command(
                command_type=CommandType.DM,
                raw_input=text,
                args=[parts[1], parts[2]],
            )

        if first_token in ("large", "/large"):
            if len(tokens) < 2:
                return Command(
                    command_type=CommandType.LARGE,
                    raw_input=text,
                    error_message="Usage: /large <peer>",
                )
            return Command(
                command_type=CommandType.LARGE,
                raw_input=text,
                args=[tokens[1]],
            )

        if first_token in ("clear", "/clear"):
            return Command(
                command_type=CommandType.CLEAR,
                raw_input=text,
                args=tokens[1:],
            )

        err_msg = f"Unknown command: '{stripped}'. Type 'help' for available commands."
        return Command(
            command_type=CommandType.UNKNOWN,
            raw_input=text,
            args=tokens,
            error_message=err_msg,
        )
