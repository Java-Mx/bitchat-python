"""Tests for bitchat.crypto.identity — LocalIdentity abstraction."""

from __future__ import annotations

import pytest

from bitchat.crypto import ed25519 as _ed
from bitchat.crypto import x25519 as _x
from bitchat.crypto.identity import LocalIdentity, calculate_fingerprint


class TestLocalIdentityGenerate:
    def test_generate_returns_local_identity(self) -> None:
        ident = LocalIdentity.generate()
        assert isinstance(ident, LocalIdentity)

    def test_x25519_public_is_32_bytes(self) -> None:
        ident = LocalIdentity.generate()
        assert isinstance(ident.x25519_public, bytes)
        assert len(ident.x25519_public) == 32

    def test_ed25519_public_is_32_bytes(self) -> None:
        ident = LocalIdentity.generate()
        assert isinstance(ident.ed25519_public, bytes)
        assert len(ident.ed25519_public) == 32

    def test_peer_id_is_8_bytes(self) -> None:
        ident = LocalIdentity.generate()
        assert isinstance(ident.peer_id, bytes)
        assert len(ident.peer_id) == 8

    def test_fingerprint_is_64_char_hex(self) -> None:
        ident = LocalIdentity.generate()
        assert isinstance(ident.fingerprint, str)
        assert len(ident.fingerprint) == 64
        # Must be valid lowercase hex
        assert all(c in "0123456789abcdef" for c in ident.fingerprint)

    def test_generate_different_keys_each_call(self) -> None:
        id1 = LocalIdentity.generate()
        id2 = LocalIdentity.generate()
        assert id1.x25519_public != id2.x25519_public
        assert id1.fingerprint != id2.fingerprint
        assert id1.peer_id != id2.peer_id

    def test_public_keys_consistent_with_private(self) -> None:
        ident = LocalIdentity.generate()
        expected_x25519_pub = _x.public_key_from_private(ident.x25519_private)
        expected_ed25519_pub = _ed.public_key_from_private(ident.ed25519_private)
        assert ident.x25519_public == expected_x25519_pub
        assert ident.ed25519_public == expected_ed25519_pub


class TestFingerprint:
    def test_fingerprint_matches_sha256_of_x25519_public(self) -> None:
        import hashlib

        ident = LocalIdentity.generate()
        expected = hashlib.sha256(ident.x25519_public).hexdigest()
        assert ident.fingerprint == expected

    def test_peer_id_is_first_8_bytes_of_sha256(self) -> None:
        import hashlib

        ident = LocalIdentity.generate()
        expected_peer_id = hashlib.sha256(ident.x25519_public).digest()[:8]
        assert ident.peer_id == expected_peer_id

    def test_peer_id_hex_is_lowercase_hex(self) -> None:
        ident = LocalIdentity.generate()
        assert ident.peer_id_hex == ident.peer_id.hex()
        assert len(ident.peer_id_hex) == 16


class TestCombinedPublicKey:
    def test_combined_public_key_is_96_bytes(self) -> None:
        ident = LocalIdentity.generate()
        assert len(ident.combined_public_key) == 96

    def test_combined_public_key_structure(self) -> None:
        """Verify x25519_pub || ed25519_pub || ed25519_pub layout."""
        ident = LocalIdentity.generate()
        combined = ident.combined_public_key
        assert combined[:32] == ident.x25519_public
        assert combined[32:64] == ident.ed25519_public
        assert combined[64:96] == ident.ed25519_public


class TestSafeRepresentation:
    def test_repr_does_not_contain_private_key(self) -> None:
        ident = LocalIdentity.generate()
        r = repr(ident)
        # Private keys must not appear in repr
        assert ident.x25519_private.hex() not in r
        assert ident.ed25519_private.hex() not in r

    def test_str_does_not_contain_private_key(self) -> None:
        ident = LocalIdentity.generate()
        s = str(ident)
        assert ident.x25519_private.hex() not in s
        assert ident.ed25519_private.hex() not in s

    def test_repr_contains_fingerprint(self) -> None:
        ident = LocalIdentity.generate()
        assert ident.fingerprint in repr(ident)


class TestImmutability:
    def test_fields_cannot_be_reassigned(self) -> None:
        import dataclasses

        ident = LocalIdentity.generate()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ident.x25519_public = bytes(32)  # type: ignore[misc]

    def test_byte_fields_are_immutable_bytes(self) -> None:
        ident = LocalIdentity.generate()
        assert isinstance(ident.x25519_public, bytes)
        assert isinstance(ident.x25519_private, bytes)
        assert isinstance(ident.ed25519_public, bytes)
        assert isinstance(ident.ed25519_private, bytes)
        assert isinstance(ident.peer_id, bytes)


class TestFromX25519Private:
    def test_deterministic_from_known_key(self) -> None:
        from bitchat.crypto import x25519 as _x

        priv = _x.generate_private_key()
        id1 = LocalIdentity.from_x25519_private(priv)
        id2 = LocalIdentity.from_x25519_private(priv)
        # Same x25519 private → same x25519 public and fingerprint
        assert id1.x25519_public == id2.x25519_public
        assert id1.fingerprint == id2.fingerprint
        assert id1.peer_id == id2.peer_id

    def test_with_both_private_keys_deterministic(self) -> None:
        from bitchat.crypto import ed25519 as _ed
        from bitchat.crypto import x25519 as _x

        x_priv = _x.generate_private_key()
        e_priv = _ed.generate_signing_key()
        id1 = LocalIdentity.from_x25519_private(x_priv, e_priv)
        id2 = LocalIdentity.from_x25519_private(x_priv, e_priv)
        assert id1.x25519_public == id2.x25519_public
        assert id1.ed25519_public == id2.ed25519_public


class TestCalculateFingerprint:
    def test_returns_64_char_hex(self) -> None:
        pub = _x.generate_private_key()  # 32 bytes, good enough for test
        fp = calculate_fingerprint(pub)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_matches_sha256_digest(self) -> None:
        import hashlib

        pub = bytes(range(32))
        fp = calculate_fingerprint(pub)
        assert fp == hashlib.sha256(pub).hexdigest()
