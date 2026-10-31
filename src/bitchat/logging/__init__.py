"""Diagnostic rotating file logging and sensitive data redaction for BitChat."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LOG_FILE_NAME = "bitchat.log"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_BACKUP_COUNT = 5
DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class SensitiveDataFilter(logging.Filter):
    """Logging filter to redact hex private keys, session tokens, and credentials."""

    REDACTED = "[REDACTED]"

    # 32-byte hex strings (64 hex characters, e.g. private keys, session keys)
    HEX_KEY_PATTERN = re.compile(r"\b[0-9a-fA-F]{64}\b")

    # Key-value secret patterns: private_key=..., session_token: ..., password=..., etc.
    KEY_VALUE_SECRET_PATTERN = re.compile(
        r"(?i)([\"']?(?:private[_\s-]?key|priv[_\s-]?key|secret[_\s-]?key|secret|seed|"
        r"session[_\s-]?token|token|password|auth[_\s-]?token|api[_\s-]?key)[\"']?)"
        r"(\s*[:=]\s*)[\"']?([^\s,'\"]+)[\"']?"
    )

    # Authorization Bearer tokens
    BEARER_PATTERN = re.compile(r"(?i)\b(bearer)\s+([a-zA-Z0-9_\-\.]+)\b")

    def redact(self, text: str) -> str:
        """Apply redactions to text containing potential credentials or keys."""
        if not text:
            return text
        # Redact key-value secrets
        redacted = self.KEY_VALUE_SECRET_PATTERN.sub(rf"\1\2{self.REDACTED}", text)
        # Redact Bearer tokens
        redacted = self.BEARER_PATTERN.sub(rf"\1 {self.REDACTED}", redacted)
        # Redact 64-char hex keys
        redacted = self.HEX_KEY_PATTERN.sub(self.REDACTED, redacted)
        return redacted

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter and redact sensitive material in log records."""
        try:
            if isinstance(record.msg, str):
                formatted = record.getMessage()
                record.msg = self.redact(formatted)
                record.args = None

            if record.exc_text:
                record.exc_text = self.redact(record.exc_text)
            elif record.exc_info:
                import traceback

                raw_exc = "".join(traceback.format_exception(*record.exc_info))
                record.exc_text = self.redact(raw_exc)

            if record.stack_info:
                record.stack_info = self.redact(record.stack_info)
        except Exception:
            pass
        return True


def disable_console_logging() -> None:
    """Disable console handlers to prevent terminal UI artifacts and screen tearing."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            root.removeHandler(handler)
    bitchat_logger = logging.getLogger("bitchat")
    for handler in list(bitchat_logger.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            bitchat_logger.removeHandler(handler)


def setup_logging(
    log_dir: Path | str,
    level: int = logging.INFO,
    tui_mode: bool = False,
) -> None:
    """Configure diagnostic rotating file logging with sensitive data redaction.

    Args:
        log_dir: Directory where log files are stored.
        level: Minimum logging level (defaults to INFO).
        tui_mode: If True, suppresses console handler output to prevent screen tearing.
    """
    path_dir = Path(log_dir)
    path_dir.mkdir(parents=True, exist_ok=True)
    log_file = path_dir / DEFAULT_LOG_FILE_NAME

    handler = RotatingFileHandler(
        log_file,
        maxBytes=DEFAULT_MAX_BYTES,
        backupCount=DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)
    handler.setFormatter(formatter)
    sensitive_filter = SensitiveDataFilter()
    handler.addFilter(sensitive_filter)
    handler.setLevel(level)

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate RotatingFileHandlers for the same file
    for existing in list(root.handlers):
        if (
            isinstance(existing, RotatingFileHandler)
            and getattr(existing, "baseFilename", None) == handler.baseFilename
        ):
            root.removeHandler(existing)
            existing.close()

    root.addHandler(handler)

    if tui_mode:
        disable_console_logging()


__all__ = [
    "DEFAULT_BACKUP_COUNT",
    "DEFAULT_LOG_FILE_NAME",
    "DEFAULT_MAX_BYTES",
    "SensitiveDataFilter",
    "disable_console_logging",
    "setup_logging",
]
