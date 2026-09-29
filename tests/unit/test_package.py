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
        input="exit\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "BitChat" in result.stdout


def test_cli_version_flag() -> None:
    """CLI --version returns package version."""
    result = subprocess.run(
        [sys.executable, "-m", "bitchat", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert bitchat.__version__ in result.stdout


def test_cli_help_flag() -> None:
    """CLI --help returns help text."""
    result = subprocess.run(
        [sys.executable, "-m", "bitchat", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "BitChat BLE Messenger" in result.stdout
