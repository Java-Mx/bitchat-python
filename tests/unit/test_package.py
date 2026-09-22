"""Tests for package initialization and CLI entry point."""

import subprocess
import sys

import bitchat


def test_version_exists() -> None:
    """Package exposes a version string."""
    assert isinstance(bitchat.__version__, str)
    assert len(bitchat.__version__) > 0


def test_cli_entry_point() -> None:
    """CLI entry point runs without error."""
    result = subprocess.run(
        [sys.executable, "-m", "bitchat"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "BitChat Python" in result.stdout
