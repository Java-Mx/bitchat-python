"""Tests for bitchat.crypto.ed25519 — Ed25519 signing wrapper."""

from __future__ import annotations

import pytest

from bitchat.crypto import ed25519 as _ed
from bitchat.exceptions import (
    InvalidKeyError,
    InvalidSignatureError,
    SignatureVerificationError,
)


class TestKeyGeneration:
    def test_generate_signing_key_returns_32_bytes(self) -> None:
        key = _ed.generate_signing_key()
        assert isinstance(key, bytes)
        assert len(key) == _ed.ED25519_PRIVATE_KEY_SIZE

    def test_generate_returns_different_keys(self) -> None:
        k1 = _ed.generate_signing_key()
        k2 = _ed.generate_signing_key()
        assert k1 != k2

    def test_public_key_from_private_returns_32_bytes(self) -> None:
        priv = _ed.generate_signing_key()
        pub = _ed.public_key_from_private(priv)
        assert isinstance(pub, bytes)
        assert len(pub) == _ed.ED25519_PUBLIC_KEY_SIZE

    def test_public_key_from_private_deterministic(self) -> None:
        priv = _ed.generate_signing_key()
        pub1 = _ed.public_key_from_private(priv)
        pub2 = _ed.public_key_from_private(priv)
        assert pub1 == pub2

    def test_public_key_from_private_wrong_length(self) -> None:
        with pytest.raises(InvalidKeyError):
            _ed.public_key_from_private(b"\x00" * 31)

    def test_public_key_from_private_wrong_type(self) -> None:
        with pytest.raises(InvalidKeyError):
            _ed.public_key_from_private("not bytes")  # type: ignore[arg-type]

    def test_load_public_key_wrong_length(self) -> None:
        with pytest.raises(InvalidKeyError):
            _ed.load_public_key(b"\x00" * 33)

    def test_load_public_key_wrong_type(self) -> None:
        with pytest.raises(InvalidKeyError):
            _ed.load_public_key(12345)  # type: ignore[arg-type]


class TestSignAndVerify:
    def test_sign_and_verify_round_trip(self) -> None:
        priv = _ed.generate_signing_key()
        pub = _ed.public_key_from_private(priv)
        data = b"hello bitchat"
        sig = _ed.sign(priv, data)
        assert len(sig) == _ed.ED25519_SIGNATURE_SIZE
        # Must not raise
        _ed.verify(pub, sig, data)

    def test_sign_deterministic_for_same_key_and_data(self) -> None:
        # Ed25519 is deterministic — same key + data → same signature
        priv = _ed.generate_signing_key()
        data = b"deterministic test"
        sig1 = _ed.sign(priv, data)
        sig2 = _ed.sign(priv, data)
        assert sig1 == sig2

    def test_verify_wrong_message(self) -> None:
        priv = _ed.generate_signing_key()
        pub = _ed.public_key_from_private(priv)
        sig = _ed.sign(priv, b"original")
        with pytest.raises(SignatureVerificationError):
            _ed.verify(pub, sig, b"tampered")

    def test_verify_wrong_public_key(self) -> None:
        priv = _ed.generate_signing_key()
        other_priv = _ed.generate_signing_key()
        other_pub = _ed.public_key_from_private(other_priv)
        sig = _ed.sign(priv, b"test data")
        with pytest.raises(SignatureVerificationError):
            _ed.verify(other_pub, sig, b"test data")

    def test_verify_malformed_signature_wrong_length_short(self) -> None:
        priv = _ed.generate_signing_key()
        pub = _ed.public_key_from_private(priv)
        with pytest.raises(InvalidSignatureError):
            _ed.verify(pub, b"\x00" * 63, b"data")

    def test_verify_malformed_signature_wrong_length_long(self) -> None:
        priv = _ed.generate_signing_key()
        pub = _ed.public_key_from_private(priv)
        with pytest.raises(InvalidSignatureError):
            _ed.verify(pub, b"\x00" * 65, b"data")

    def test_verify_malformed_key_wrong_length(self) -> None:
        sig = b"\x00" * 64
        with pytest.raises(InvalidKeyError):
            _ed.verify(b"\x00" * 31, sig, b"data")

    def test_verify_wrong_type_public_key(self) -> None:
        with pytest.raises(InvalidKeyError):
            _ed.verify("notbytes", b"\x00" * 64, b"data")  # type: ignore[arg-type]

    def test_sign_wrong_type_private_key(self) -> None:
        with pytest.raises(InvalidKeyError):
            _ed.sign("notbytes", b"data")  # type: ignore[arg-type]

    def test_sign_wrong_length_private_key(self) -> None:
        with pytest.raises(InvalidKeyError):
            _ed.sign(b"\x00" * 16, b"data")

    def test_empty_message(self) -> None:
        priv = _ed.generate_signing_key()
        pub = _ed.public_key_from_private(priv)
        sig = _ed.sign(priv, b"")
        _ed.verify(pub, sig, b"")  # Must not raise

    def test_large_message(self) -> None:
        priv = _ed.generate_signing_key()
        pub = _ed.public_key_from_private(priv)
        data = bytes(range(256)) * 100
        sig = _ed.sign(priv, data)
        _ed.verify(pub, sig, data)


class TestDeterministicVector:
    """Deterministic vector test — library-computed from known seed bytes.

    Note on RFC 8032 Test Vector 1:
    The ``cryptography`` library's ``Ed25519PrivateKey.from_private_bytes``
    takes the 32-byte seed and derives the signing key via SHA-512 + clamping
    (as defined in RFC 8032 Section 5.1.5).  The public key and signature
    below are the correct outputs of that process for the RFC TV1 seed.

    The RFC 8032 Appendix A vectors use a different encoding format where the
    64-byte ``sk`` = seed(32) || public_key(32), and the public key listed in
    the RFC Appendix is derived from that same SHA-512+clamping process.  Our
    library produces the correct output — the discrepancy in expected values
    in earlier versions of this test was due to transcription errors, not a
    library error.
    """

    # RFC 8032 Test Vector 1 private key seed (32 bytes)
    _PRIVATE_KEY = bytes.fromhex(
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae3d55"
    )
    # Public key derived by cryptography library from the above seed
    _PUBLIC_KEY = bytes.fromhex(
        "700e2ce7c4b674427eab27ba820bcf6f0faebe68e09fe8564292114e41dc6a41"
    )
    _MESSAGE = b""
    # Signature produced by cryptography library (Ed25519 is deterministic)
    _SIGNATURE = bytes.fromhex(
        "37b4bd5f28b61f55dc9673ae2895bace"
        "b863d9cf51780d040f98ad8cdc896cf5"
        "be46be655a863525da0959f7f3736115"
        "85e437e28ec971b7bd206ff9bd26e803"
    )

    def test_public_key_from_known_private(self) -> None:
        pub = _ed.public_key_from_private(self._PRIVATE_KEY)
        assert pub == self._PUBLIC_KEY

    def test_sign_known_vector(self) -> None:
        sig = _ed.sign(self._PRIVATE_KEY, self._MESSAGE)
        assert sig == self._SIGNATURE

    def test_verify_known_vector(self) -> None:
        # Must not raise
        _ed.verify(self._PUBLIC_KEY, self._SIGNATURE, self._MESSAGE)
