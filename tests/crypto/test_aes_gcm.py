"""Tests for bitchat.crypto.aes_gcm — AES-256-GCM encryption wrapper."""

from __future__ import annotations

import pytest

from bitchat.crypto import aes_gcm as _aes
from bitchat.exceptions import DecryptionError, EncryptionError


def _make_key() -> bytes:
    """Return a valid 32-byte AES key for testing."""
    return bytes(range(32))


class TestEncrypt:
    def test_encrypt_returns_nonce_plus_ciphertext(self) -> None:
        key = _make_key()
        plaintext = b"hello bitchat"
        result = _aes.encrypt(key, plaintext)
        # nonce(12) + ciphertext(len) + tag(16)
        assert len(result) == _aes.AES_NONCE_SIZE + len(plaintext) + _aes.AES_TAG_SIZE

    def test_encrypt_produces_different_ciphertexts(self) -> None:
        key = _make_key()
        plaintext = b"same plaintext"
        c1 = _aes.encrypt(key, plaintext)
        c2 = _aes.encrypt(key, plaintext)
        # Different nonces → different output
        assert c1 != c2

    def test_encrypt_wrong_key_length(self) -> None:
        with pytest.raises(EncryptionError):
            _aes.encrypt(b"\x00" * 16, b"data")

    def test_encrypt_wrong_key_type(self) -> None:
        with pytest.raises(EncryptionError):
            _aes.encrypt("not bytes", b"data")  # type: ignore[arg-type]

    def test_encrypt_empty_plaintext(self) -> None:
        key = _make_key()
        result = _aes.encrypt(key, b"")
        assert len(result) == _aes.AES_NONCE_SIZE + _aes.AES_TAG_SIZE

    def test_encrypt_with_key_alias(self) -> None:
        key = _make_key()
        pt = b"channel message"
        result = _aes.encrypt_with_key(key, pt)
        # Should decrypt successfully
        decrypted = _aes.decrypt_with_key(key, result)
        assert decrypted == pt


class TestDecrypt:
    def test_decrypt_round_trip(self) -> None:
        key = _make_key()
        plaintext = b"test round trip"
        ciphertext = _aes.encrypt(key, plaintext)
        result = _aes.decrypt(key, ciphertext)
        assert result == plaintext

    def test_decrypt_wrong_key(self) -> None:
        key = _make_key()
        wrong_key = bytes(range(1, 33))
        ciphertext = _aes.encrypt(key, b"secret data")
        with pytest.raises(DecryptionError):
            _aes.decrypt(wrong_key, ciphertext)

    def test_decrypt_modified_ciphertext(self) -> None:
        key = _make_key()
        ciphertext = _aes.encrypt(key, b"important data")
        # Flip a byte in the ciphertext portion (after nonce)
        tampered = bytearray(ciphertext)
        tampered[_aes.AES_NONCE_SIZE] ^= 0xFF
        with pytest.raises(DecryptionError):
            _aes.decrypt(key, bytes(tampered))

    def test_decrypt_modified_tag(self) -> None:
        key = _make_key()
        ciphertext = _aes.encrypt(key, b"important data")
        # Flip a byte in the tag (last 16 bytes)
        tampered = bytearray(ciphertext)
        tampered[-1] ^= 0xFF
        with pytest.raises(DecryptionError):
            _aes.decrypt(key, bytes(tampered))

    def test_decrypt_modified_nonce(self) -> None:
        key = _make_key()
        ciphertext = _aes.encrypt(key, b"important data")
        # Flip a byte in the nonce (first 12 bytes)
        tampered = bytearray(ciphertext)
        tampered[0] ^= 0xFF
        with pytest.raises(DecryptionError):
            _aes.decrypt(key, bytes(tampered))

    def test_decrypt_too_short(self) -> None:
        key = _make_key()
        with pytest.raises(DecryptionError):
            _aes.decrypt(key, b"\x00" * 10)

    def test_decrypt_wrong_key_type(self) -> None:
        with pytest.raises(EncryptionError):
            _aes.decrypt("not bytes", b"\x00" * 28)  # type: ignore[arg-type]

    def test_decrypt_data_wrong_type(self) -> None:
        key = _make_key()
        with pytest.raises(DecryptionError):
            _aes.decrypt(key, "not bytes")  # type: ignore[arg-type]

    def test_decrypt_large_message(self) -> None:
        key = _make_key()
        plaintext = bytes(range(256)) * 50  # 12800 bytes
        ciphertext = _aes.encrypt(key, plaintext)
        result = _aes.decrypt(key, ciphertext)
        assert result == plaintext


class TestNistVector:
    """NIST AES-256-GCM Test Vector.

    From NIST GCM Test Case 14 (Appendix B):
    Plaintext: empty
    Key: 256-bit zeros
    IV (nonce): 96-bit zeros
    AAD: empty
    Ciphertext: (empty)
    Tag: 530f8afbc74536b9a963b4f1c4cb738b
    """

    _KEY = bytes(32)  # 256 zeros
    _NONCE = bytes(12)  # 96-bit zeros
    _PLAINTEXT = b""
    _EXPECTED_TAG = bytes.fromhex("530f8afbc74536b9a963b4f1c4cb738b")

    def test_empty_plaintext_produces_known_tag(self) -> None:
        """Verify AEAD over empty plaintext produces the NIST authentication tag."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(self._KEY)
        ct = aesgcm.encrypt(self._NONCE, self._PLAINTEXT, None)
        # ct should be just the 16-byte tag for empty plaintext
        assert ct == self._EXPECTED_TAG

    def test_round_trip_with_known_key(self) -> None:
        """Basic encrypt+decrypt sanity check with NIST key."""
        pt = b"NIST test plaintext"
        ct = _aes.encrypt(self._KEY, pt)
        assert _aes.decrypt(self._KEY, ct) == pt
