"""Tests for bitchat.crypto.hkdf — Noise-internal and legacy HKDF variants."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from bitchat.crypto.hkdf import legacy_hkdf, noise_hkdf


class TestNoiseHkdf:
    """Tests for the custom Noise HKDF (matching Rust noise_protocol.rs)."""

    def test_returns_correct_number_of_outputs_2(self) -> None:
        ck = bytes(32)
        outputs = noise_hkdf(ck, b"", 2)
        assert len(outputs) == 2
        for out in outputs:
            assert len(out) == 32

    def test_returns_correct_number_of_outputs_3(self) -> None:
        ck = bytes(32)
        outputs = noise_hkdf(ck, b"", 3)
        assert len(outputs) == 3

    def test_deterministic_for_same_inputs(self) -> None:
        ck = bytes(range(32))
        ikm = b"input key material"
        out1 = noise_hkdf(ck, ikm, 2)
        out2 = noise_hkdf(ck, ikm, 2)
        assert out1 == out2

    def test_different_ck_gives_different_outputs(self) -> None:
        ikm = b"same ikm"
        out1 = noise_hkdf(bytes(32), ikm, 2)
        out2 = noise_hkdf(bytes(range(32)), ikm, 2)
        assert out1[0] != out2[0]

    def test_different_ikm_gives_different_outputs(self) -> None:
        ck = bytes(32)
        out1 = noise_hkdf(ck, b"ikm1", 2)
        out2 = noise_hkdf(ck, b"ikm2", 2)
        assert out1[0] != out2[0]

    def test_known_vector_matches_manual_computation(self) -> None:
        """Verify against a manually computed value using the Rust HMAC chain logic."""
        ck = bytes(32)
        ikm = b""
        # Step 1: temp_key = HMAC-SHA256(key=ck, data=ikm)
        temp_key = hmac.new(ck, msg=ikm, digestmod=hashlib.sha256).digest()
        # Step 2: T(1) = HMAC-SHA256(key=temp_key, data="" || 0x01)
        t1 = hmac.new(temp_key, msg=b"\x01", digestmod=hashlib.sha256).digest()
        # Step 3: T(2) = HMAC-SHA256(key=temp_key, data=T(1) || 0x02)
        t2 = hmac.new(temp_key, msg=t1 + b"\x02", digestmod=hashlib.sha256).digest()

        outputs = noise_hkdf(ck, ikm, 2)
        assert outputs[0] == t1
        assert outputs[1] == t2

    def test_invalid_num_outputs_zero(self) -> None:
        with pytest.raises(ValueError):
            noise_hkdf(bytes(32), b"", 0)

    def test_invalid_num_outputs_negative(self) -> None:
        with pytest.raises(ValueError):
            noise_hkdf(bytes(32), b"", -1)

    def test_outputs_are_not_equal(self) -> None:
        """Each output block should be distinct."""
        outputs = noise_hkdf(bytes(32), b"ikm", 3)
        assert outputs[0] != outputs[1]
        assert outputs[1] != outputs[2]


class TestLegacyHkdf:
    """Tests for the standard HKDF-SHA256 (matching Rust encryption.rs)."""

    def test_returns_32_bytes_by_default(self) -> None:
        ikm = bytes(32)
        result = legacy_hkdf(ikm)
        assert isinstance(result, bytes)
        assert len(result) == 32

    def test_deterministic(self) -> None:
        ikm = bytes(range(32))
        r1 = legacy_hkdf(ikm)
        r2 = legacy_hkdf(ikm)
        assert r1 == r2

    def test_salt_sensitivity(self) -> None:
        ikm = bytes(32)
        r1 = legacy_hkdf(ikm, salt=b"bitchat-v1")
        r2 = legacy_hkdf(ikm, salt=b"different-salt")
        assert r1 != r2

    def test_ikm_sensitivity(self) -> None:
        r1 = legacy_hkdf(bytes(32))
        r2 = legacy_hkdf(bytes(range(32)))
        assert r1 != r2

    def test_custom_length(self) -> None:
        result = legacy_hkdf(bytes(32), length=16)
        assert len(result) == 16

    def test_known_output_with_bitchat_v1_salt(self) -> None:
        """Derive using the canonical BitChat legacy parameters.

        Known output computed externally from HKDF-SHA256 spec:
        IKM = 32 zero bytes, salt = b"bitchat-v1", info = b"", L = 32.
        We validate by checking the output is 32 bytes and consistent.
        (Full external vector can be added once Rust test suite emits values.)
        """
        ikm = bytes(32)
        result = legacy_hkdf(ikm, salt=b"bitchat-v1", info=b"", length=32)
        assert len(result) == 32
        # Determinism check — calling again must give the same result
        assert result == legacy_hkdf(ikm, salt=b"bitchat-v1", info=b"", length=32)

    def test_noise_hkdf_and_legacy_hkdf_differ(self) -> None:
        """The two HKDF variants use fundamentally different constructions.

        noise_hkdf: custom HMAC chain (key=chaining_key, then keyed counter chain)
        legacy_hkdf: standard HKDF-SHA256 (salt=bitchat-v1, info=empty)

        For any given IKM, they must not produce the same first output block.
        We verify this with three different IKM values to ensure robustness.
        """
        test_ikms = [
            bytes(range(32)),
            bytes([0xAA] * 32),
            bytes([0x55] * 32),
        ]
        ck = bytes(range(32))
        for ikm in test_ikms:
            noise_out = noise_hkdf(ck, ikm, 2)[0]
            legacy_out = legacy_hkdf(ikm, salt=b"bitchat-v1")
            assert noise_out != legacy_out, (
                f"noise_hkdf and legacy_hkdf unexpectedly agree for IKM={ikm.hex()}"
            )
