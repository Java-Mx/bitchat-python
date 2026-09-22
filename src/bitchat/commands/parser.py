"""Command parser for the BitChat CLI."""

from dataclasses import dataclass, field
from enum import StrEnum


class CommandType(StrEnum):
    """Supported command types in Phase 2."""

    INITIALIZE_CHAT = "initialize_chat"
    HELP = "help"
    EXIT = "exit"
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
        """Parse a line of text into a Command.

        Handles leading/trailing whitespace, tokenization, and case insensitivity.
        """
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

        # Single-word command matching
        first_token = normalized_tokens[0]

        if first_token in ("help", "?"):
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

        err_msg = f"Unknown command: '{stripped}'. Type 'help' for available commands."
        return Command(
            command_type=CommandType.UNKNOWN,
            raw_input=text,
            args=tokens,
            error_message=err_msg,
        )
