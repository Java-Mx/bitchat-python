"""Application error hierarchy for BitChat."""


class BitChatError(Exception):
    """Base exception for all BitChat errors."""


class ConfigurationError(BitChatError):
    """Raised when configuration loading or saving fails."""


class CommandError(BitChatError):
    """Raised when a command fails to parse or execute."""


class ApplicationError(BitChatError):
    """Raised when an application lifecycle error occurs."""
