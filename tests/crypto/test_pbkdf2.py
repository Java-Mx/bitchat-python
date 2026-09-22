"""Tests for bitchat.crypto.pbkdf2 — PBKDF2-HMAC-SHA256 channel key derivation."""

from __future__ import annotations

import pytest

from bitchat.crypto.pbkdf2 import (
    PBKDF2_ITERATIONS,
    PBKDF2_OUTPUT_LENGTH,
    derive_channel_key,
)


class TestDeriveChannelKey:
    def test_returns_32_bytes(self) -> None:
        key = derive_channel_key("password", "#general")
        assert isinstance(key, bytes)
        assert len(key) == PBKDF2_OUTPUT_LENGTH

    def test_deterministic_same_inputs(self) -> None:
        k1 = derive_channel_key("secret", "#channel")
        k2 = derive_channel_key("secret", "#channel")
        assert k1 == k2

    def test_different_password_different_key(self) -> None:
        k1 = derive_channel_key("password1", "#general")
        k2 = derive_channel_key("password2", "#general")
        assert k1 != k2

    def test_different_channel_different_key(self) -> None:
        k1 = derive_channel_key("password", "#channel1")
        k2 = derive_channel_key("password", "#channel2")
        assert k1 != k2

    def test_salt_is_channel_name_not_password(self) -> None:
        """Channel name is the salt — swapping produces different keys."""
        k1 = derive_channel_key("alpha", "#beta")
        k2 = derive_channel_key("#beta", "alpha")
        assert k1 != k2

    def test_wrong_password_type(self) -> None:
        with pytest.raises(TypeError):
            derive_channel_key(b"bytes", "#channel")  # type: ignore[arg-type]

    def test_wrong_channel_name_type(self) -> None:
        with pytest.raises(TypeError):
            derive_channel_key("password", b"#channel")  # type: ignore[arg-type]

    def test_empty_password(self) -> None:
        key = derive_channel_key("", "#channel")
        assert len(key) == 32

    def test_empty_channel_name(self) -> None:
        key = derive_channel_key("password", "")
        assert len(key) == 32

    def test_unicode_password(self) -> None:
        key = derive_channel_key("pässwørd 🔑", "#général")
        assert len(key) == 32

    def test_constants_match_rust_reference(self) -> None:
        """Verify iteration count matches Rust encryption.rs (line 290)."""
        assert PBKDF2_ITERATIONS == 100_000
        assert PBKDF2_OUTPUT_LENGTH == 32

    def test_known_vector(self) -> None:
        """Known-good output for password='password123', channel='#general'.

        Computed independently using:
        PBKDF2-HMAC-SHA256(
            password=b'password123', salt=b'#general',
            iterations=100_000, dklen=32
        )
        """
        import hashlib

        expected = hashlib.pbkdf2_hmac(
            "sha256",
            b"password123",
            b"#general",
            100_000,
            dklen=32,
        )
        result = derive_channel_key("password123", "#general")
        assert result == expected
