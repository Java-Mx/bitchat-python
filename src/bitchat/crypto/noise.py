"""
Noise protocol implementation for BitChat: Noise_XX_25519_ChaChaPoly_SHA256.

This module implements the complete Noise XX handshake state machine and
transport cipher state, matching the Rust reference implementation in
``noise_protocol.rs``.

**Protocol:** ``Noise_XX_25519_ChaChaPoly_SHA256``
  Confirmed from ``noise_protocol.rs`` ``NoiseProtocolName::new`` (lines 70-85).

**XX message patterns** (confirmed lines 1265-1275):
  - Message 1 (Initiator → Responder): ``[E]``
  - Message 2 (Responder → Initiator): ``[E, EE, S, ES]``
  - Message 3 (Initiator → Responder): ``[S, SE]``

**Nonce format** (confirmed lines 270-273):
  12-byte array where bytes 4-11 contain the u64 counter in little-endian.
  Bytes 0-3 are always zero.

**Transport nonce wire format** (confirmed lines 296-310):
  Transport ``NoiseCipherState`` prepends a 4-byte LE counter to ciphertext.
  The counter is extracted from the first 4 bytes of the received ciphertext.

**Transport cipher assignment** (confirmed lines 1235-1240):
  - Initiator: send=c1, recv=c2
  - Responder: send=c2, recv=c1

**Replay protection** (confirmed lines 128-213):
  1024-entry sliding window using a set of seen nonces.

**Handshake HKDF** (confirmed lines 564-587):
  Custom HMAC-SHA256 chain — NOT standard HKDF expand.

**Prologue:** Empty bytes (``mix_hash(b"")``) for XX pattern (line 662).

**Initial symmetric state hash:**
  Protocol name bytes if len ≤ 32, else SHA-256(protocol name).
  For ``Noise_XX_25519_ChaChaPoly_SHA256`` (len=32 exactly: 32 chars), the
  bytes are used directly.  Confirmed lines 420-428.

**Security deviations from Rust reference (documented):**
  - Rust's ``read_message`` silently continues handshake when payload
    decryption fails (line 1201: ``// Continue handshake even if payload
    decryption fails (for debugging)``).  Python raises ``AuthenticationError``
    instead — this is intentional and more secure.

Do NOT log Noise cipher key material, shared secrets, or handshake state.
"""

from __future__ import annotations

import enum
import hashlib

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from bitchat.crypto.hkdf import noise_hkdf
from bitchat.crypto.x25519 import (
    diffie_hellman,
    generate_private_key,
    public_key_from_private,
    validate_public_key,
)
from bitchat.exceptions import (
    AuthenticationError,
    DecryptionError,
    EncryptionError,
    InvalidKeyError,
    InvalidNonceError,
    NoiseError,
    NoiseStateError,
    ReplayError,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOISE_PROTOCOL_NAME: str = "Noise_XX_25519_ChaChaPoly_SHA256"
"""Full protocol name string (exactly 32 bytes as UTF-8)."""

NOISE_REPLAY_WINDOW_SIZE: int = 1024
"""Sliding window size for replay protection (matching Rust constant)."""

_NONCE_SIZE_BYTES: int = 4
"""Wire size of the nonce prefix prepended to transport ciphertext (4 bytes LE)."""

_CHACHA_NONCE_SIZE: int = 12
"""ChaCha20-Poly1305 requires a 12-byte nonce."""

_DH_KEY_SIZE: int = 32
"""X25519 key size in bytes."""

_TAG_SIZE: int = 16
"""ChaCha20-Poly1305 authentication tag size in bytes."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class NoiseRole(enum.Enum):
    """Role in a Noise handshake."""

    INITIATOR = "initiator"
    RESPONDER = "responder"


class NoiseSessionState(enum.Enum):
    """Lifecycle state of a Noise session."""

    UNINITIALIZED = "uninitialized"
    HANDSHAKING = "handshaking"
    ESTABLISHED = "established"
    FAILED = "failed"
    CLOSED = "closed"


# ---------------------------------------------------------------------------
# Handshake role determination
# ---------------------------------------------------------------------------


def determine_handshake_role(my_peer_id_hex: str, remote_peer_id_hex: str) -> NoiseRole:
    """Determine the Noise role based on lexicographic peer ID comparison.

    Matches Rust ``notification_handlers.rs`` line 1771:
    ``if my_peer_id < requester_id.as_str()`` → we have lower ID → Initiator.

    The peer ID comparison is performed as a lexicographic string comparison
    of the hex-encoded peer ID strings.

    Args:
        my_peer_id_hex: Local peer ID as a hex string.
        remote_peer_id_hex: Remote peer ID as a hex string.

    Returns:
        ``NoiseRole.INITIATOR`` if ``my_peer_id_hex < remote_peer_id_hex``,
        else ``NoiseRole.RESPONDER``.

    Raises:
        ValueError: If either peer ID is empty.
    """
    if not my_peer_id_hex:
        raise ValueError("my_peer_id_hex must not be empty")
    if not remote_peer_id_hex:
        raise ValueError("remote_peer_id_hex must not be empty")
    if my_peer_id_hex < remote_peer_id_hex:
        return NoiseRole.INITIATOR
    return NoiseRole.RESPONDER


# ---------------------------------------------------------------------------
# NoiseCipherState
# ---------------------------------------------------------------------------


class NoiseCipherState:
    """Symmetric AEAD cipher state for Noise protocol.

    Wraps ChaCha20-Poly1305 with automatic nonce management and replay
    protection.  Matches Rust ``NoiseCipherState`` (``noise_protocol.rs``
    lines 138-403).

    Two operating modes controlled by ``use_extracted_nonce``:
      - ``False`` (handshake mode): nonce counter is internal; not prepended
        to ciphertext.
      - ``True`` (transport mode): 4-byte LE counter is prepended to
        ciphertext on send; extracted from ciphertext on receive.  Replay
        protection is active.

    Nonce wire format (12 bytes, matching Rust lines 270-274):
      ``[0x00, 0x00, 0x00, 0x00] + counter.to_bytes(8, 'little')``
    """

    def __init__(
        self,
        key: bytes | None = None,
        *,
        use_extracted_nonce: bool = False,
    ) -> None:
        """Initialise the cipher state.

        Args:
            key: Optional 32-byte ChaCha20-Poly1305 key.  If ``None``, the
                cipher is uninitialised and encrypt/decrypt will raise.
            use_extracted_nonce: If ``True``, nonce is prepended to / extracted
                from the wire ciphertext (transport mode).
        """
        self._key: bytes | None = bytes(key) if key is not None else None
        self._nonce: int = 0
        self._use_extracted_nonce: bool = use_extracted_nonce
        self._replay_window: set[int] = set()
        self._highest_received_nonce: int = 0

    def has_key(self) -> bool:
        """Return True if a cipher key has been initialised."""
        return self._key is not None

    def initialize_key(self, key: bytes) -> None:
        """Set (or reset) the cipher key.

        Resets nonce counter and replay window.

        Args:
            key: 32-byte ChaCha20-Poly1305 key.
        """
        self._key = bytes(key)
        self._nonce = 0
        self._replay_window.clear()
        self._highest_received_nonce = 0

    # -----------------------------------------------------------------------
    # Nonce helpers
    # -----------------------------------------------------------------------

    def _build_chacha_nonce(self, counter: int) -> bytes:
        """Build the 12-byte ChaCha20-Poly1305 nonce from a counter.

        Matching Rust ``noise_protocol.rs`` lines 270-274:
          ``nonce_bytes[4..12].copy_from_slice(&nonce_le_bytes)``
        Result: ``[0,0,0,0] + counter.to_bytes(8, 'little')``

        Args:
            counter: u64 nonce counter value.

        Returns:
            12-byte nonce.
        """
        nonce_bytes = bytearray(12)
        nonce_bytes[4:12] = counter.to_bytes(8, "little")
        return bytes(nonce_bytes)

    def _counter_to_wire_bytes(self, counter: int) -> bytes:
        """Encode the counter as a 4-byte little-endian wire prefix.

        Matching Rust ``nonce_to_bytes`` (lines 239-245):
          takes first 4 bytes of u64 LE encoding.

        Args:
            counter: u64 nonce counter value (fits in 32 bits for wire format).

        Returns:
            4-byte little-endian encoding.
        """
        return counter.to_bytes(8, "little")[:_NONCE_SIZE_BYTES]

    def _extract_wire_nonce(self, data: bytes) -> tuple[int, bytes]:
        """Extract 4-byte LE nonce prefix and remaining ciphertext.

        Matching Rust ``extract_nonce_from_ciphertext_payload``
        (lines 218-236).

        Args:
            data: Combined ``nonce(4) || ciphertext+tag`` bytes.

        Returns:
            Tuple of ``(counter: int, ciphertext_and_tag: bytes)``.

        Raises:
            InvalidNonceError: If ``data`` is shorter than 4 bytes.
        """
        if len(data) < _NONCE_SIZE_BYTES:
            raise InvalidNonceError(
                f"Ciphertext too short to contain 4-byte nonce prefix "
                f"(got {len(data)} bytes)"
            )
        counter_bytes = data[:_NONCE_SIZE_BYTES]
        counter = int.from_bytes(counter_bytes, "little")
        return counter, data[_NONCE_SIZE_BYTES:]

    # -----------------------------------------------------------------------
    # Replay protection
    # -----------------------------------------------------------------------

    def _is_valid_nonce(self, received_nonce: int) -> bool:
        """Check whether a received nonce is outside the replay window.

        Matching Rust ``is_valid_nonce`` (lines 181-192).

        Args:
            received_nonce: Counter value extracted from the wire.

        Returns:
            True if the nonce should be accepted (not replayed or too old).
        """
        if received_nonce + NOISE_REPLAY_WINDOW_SIZE <= self._highest_received_nonce:
            return False  # Too old
        if received_nonce > self._highest_received_nonce:
            return True  # Always accept newer nonces
        return received_nonce not in self._replay_window

    def _mark_nonce_seen(self, received_nonce: int) -> None:
        """Record a nonce as seen in the sliding replay window.

        Matching Rust ``mark_nonce_as_seen`` (lines 195-213).

        Args:
            received_nonce: Counter value to record.
        """
        if received_nonce > self._highest_received_nonce:
            shift = received_nonce - self._highest_received_nonce
            if shift >= NOISE_REPLAY_WINDOW_SIZE:
                self._replay_window.clear()
            else:
                self._replay_window = {
                    n
                    for n in self._replay_window
                    if n + NOISE_REPLAY_WINDOW_SIZE > received_nonce
                }
            self._highest_received_nonce = received_nonce
        self._replay_window.add(received_nonce)

    # -----------------------------------------------------------------------
    # Encrypt / Decrypt
    # -----------------------------------------------------------------------

    def encrypt(self, plaintext: bytes, aad: bytes) -> bytes:
        """Encrypt with the current nonce, then advance the counter.

        Matching Rust ``NoiseCipherState::encrypt`` (lines 248-326).

        In transport mode (``use_extracted_nonce=True``), the 4-byte LE
        nonce prefix is prepended to the ciphertext output.

        Args:
            plaintext: Data to encrypt.
            aad: Associated data (used as ChaCha20 AAD).

        Returns:
            - Handshake mode: ``ciphertext+tag``
            - Transport mode: ``nonce(4) || ciphertext+tag``

        Raises:
            NoiseStateError: If no key has been initialised.
            EncryptionError: If ChaCha20-Poly1305 encryption fails.
        """
        if self._key is None:
            raise NoiseStateError("NoiseCipherState: no key initialised (encrypt)")
        current_nonce = self._nonce
        chacha_nonce = self._build_chacha_nonce(current_nonce)
        try:
            cipher = ChaCha20Poly1305(self._key)
            ciphertext = cipher.encrypt(chacha_nonce, bytes(plaintext), bytes(aad))
        except Exception as exc:
            raise EncryptionError(
                f"ChaCha20-Poly1305 encryption failed: {exc}"
            ) from exc
        self._nonce += 1
        if self._use_extracted_nonce:
            return self._counter_to_wire_bytes(current_nonce) + ciphertext
        return ciphertext

    def decrypt(self, ciphertext: bytes, aad: bytes) -> bytes:
        """Decrypt and authenticate, advancing the nonce counter.

        Matching Rust ``NoiseCipherState::decrypt`` (lines 328-403).

        In transport mode (``use_extracted_nonce=True``):
          - Extract 4-byte LE nonce from the start.
          - Validate replay window (nonce=0 is NOT checked; matching Rust
            comment: "FIXED: Only validate nonce for non-zero nonces in
            transport mode").
          - After successful decryption, mark nonce as seen.

        Args:
            ciphertext: Data to decrypt.
              - Handshake mode: ``ciphertext+tag``
              - Transport mode: ``nonce(4) || ciphertext+tag``
            aad: Associated data (used as ChaCha20 AAD).

        Returns:
            Decrypted plaintext bytes.

        Raises:
            NoiseStateError: If no key has been initialised.
            InvalidNonceError: If the extracted nonce prefix is missing.
            ReplayError: If a replayed transport nonce is detected.
            DecryptionError: If authentication fails or decryption errors.
        """
        if self._key is None:
            raise NoiseStateError("NoiseCipherState: no key initialised (decrypt)")

        if self._use_extracted_nonce:
            counter, payload = self._extract_wire_nonce(bytes(ciphertext))
            # Rust: skip replay check for nonce=0
            if counter > 0 and not self._is_valid_nonce(counter):
                raise ReplayError(
                    f"Replay detected: nonce {counter} has already been seen "
                    f"or is outside the replay window"
                )
            chacha_nonce = self._build_chacha_nonce(counter)
        else:
            counter = self._nonce
            payload = bytes(ciphertext)
            chacha_nonce = self._build_chacha_nonce(counter)

        try:
            cipher = ChaCha20Poly1305(self._key)
            plaintext = cipher.decrypt(chacha_nonce, payload, bytes(aad))
        except Exception as exc:
            raise DecryptionError(
                "ChaCha20-Poly1305 decryption or authentication failed"
            ) from exc

        if self._use_extracted_nonce:
            if counter > 0:
                self._mark_nonce_seen(counter)
        else:
            self._nonce += 1

        return plaintext


# ---------------------------------------------------------------------------
# NoiseSymmetricState
# ---------------------------------------------------------------------------


class NoiseSymmetricState:
    """Manages the running cryptographic state during a Noise handshake.

    Tracks the chaining key (``ck``), the handshake hash (``h``), and the
    current cipher state.  Matches Rust ``NoiseSymmetricState``
    (``noise_protocol.rs`` lines 411-588).
    """

    def __init__(self, protocol_name: str) -> None:
        """Initialise the symmetric state with the protocol name.

        Matching Rust ``NoiseSymmetricState::new`` (lines 418-434):
        - If len(protocol_name_bytes) <= 32: zero-pad to 32 bytes.
        - Else: h = SHA-256(protocol_name_bytes).
        Both ``h`` and ``ck`` are initialised to the same value.

        Args:
            protocol_name: The full Noise protocol name string.
        """
        name_bytes = protocol_name.encode("utf-8")
        if len(name_bytes) <= 32:
            h = bytearray(32)
            h[: len(name_bytes)] = name_bytes
            initial_hash = bytes(h)
        else:
            initial_hash = hashlib.sha256(name_bytes).digest()

        self._hash: bytes = initial_hash
        self._chaining_key: bytes = initial_hash
        self._cipher_state: NoiseCipherState = NoiseCipherState()

    def has_cipher_key(self) -> bool:
        """Return True if the internal cipher has been initialised."""
        return self._cipher_state.has_key()

    def get_handshake_hash(self) -> bytes:
        """Return the current handshake transcript hash.

        Returns:
            32-byte handshake hash (SHA-256 over the full transcript).
        """
        return self._hash

    def mix_key(self, ikm: bytes) -> None:
        """Update chaining key and derive a new temporary cipher key.

        Matching Rust ``mix_key`` (lines 437-443):
          ``noise_hkdf(ck, ikm, 2)`` → ``new_ck, temp_key``

        Args:
            ikm: Input key material (DH output, 32 bytes).
        """
        outputs = noise_hkdf(self._chaining_key, ikm, 2)
        self._chaining_key = outputs[0]
        self._cipher_state.initialize_key(outputs[1])

    def mix_hash(self, data: bytes) -> None:
        """Extend the handshake transcript hash.

        Matching Rust ``mix_hash`` (lines 445-449):
          ``h = SHA-256(h || data)``

        Args:
            data: Data to mix into the hash.
        """
        self._hash = hashlib.sha256(self._hash + bytes(data)).digest()

    def mix_key_and_hash(self, ikm: bytes) -> None:
        """Update chaining key, mix a hash contribution, and derive a cipher key.

        Matching Rust ``mix_key_and_hash`` (lines 452-458):
          ``noise_hkdf(ck, ikm, 3)`` → ``new_ck, temp_hash, temp_key``
          ``mix_hash(temp_hash)``

        Args:
            ikm: Input key material (32 bytes).
        """
        outputs = noise_hkdf(self._chaining_key, ikm, 3)
        self._chaining_key = outputs[0]
        self.mix_hash(outputs[1])
        self._cipher_state.initialize_key(outputs[2])

    def encrypt_and_hash(self, plaintext: bytes) -> bytes:
        """Encrypt (if key exists) and mix result into handshake hash.

        Matching Rust ``encrypt_and_hash`` (lines 469-477):
          - If cipher key: encrypt with ``h`` as AAD, mix_hash(ciphertext).
          - Else: mix_hash(plaintext), return plaintext.

        Args:
            plaintext: Data to encrypt.

        Returns:
            Ciphertext (or plaintext if no key).
        """
        if self._cipher_state.has_key():
            ciphertext = self._cipher_state.encrypt(bytes(plaintext), self._hash)
            self.mix_hash(ciphertext)
            return ciphertext
        else:
            self.mix_hash(bytes(plaintext))
            return bytes(plaintext)

    def decrypt_and_hash(self, ciphertext: bytes) -> bytes:
        """Decrypt (if key exists) and mix ciphertext into handshake hash.

        Matching Rust ``decrypt_and_hash`` (lines 480-540):
          - If cipher key:
            - Empty ciphertext: mix_hash(b""), return b"" (matching Rust line 498-505).
            - Else: decrypt with ``h`` as AAD; mix_hash(ciphertext) after success.
          - Else: mix_hash(ciphertext), return ciphertext.

        **Security deviation from Rust reference:**
        The Rust reference ``read_message`` continues the handshake even when
        payload decryption fails (comment: "Continue handshake even if payload
        decryption fails (for debugging)").  This Python implementation raises
        ``AuthenticationError`` instead — failing closed is more secure.

        Args:
            ciphertext: Data to decrypt.

        Returns:
            Plaintext (or ciphertext if no key).

        Raises:
            AuthenticationError: If decryption fails (fails closed).
        """
        if self._cipher_state.has_key():
            if len(ciphertext) == 0:
                self.mix_hash(b"")
                return b""
            try:
                plaintext = self._cipher_state.decrypt(bytes(ciphertext), self._hash)
            except (DecryptionError, ReplayError) as exc:
                raise AuthenticationError(
                    "Noise handshake payload authentication failed"
                ) from exc
            self.mix_hash(bytes(ciphertext))
            return plaintext
        else:
            self.mix_hash(bytes(ciphertext))
            return bytes(ciphertext)

    def split(self) -> tuple[NoiseCipherState, NoiseCipherState]:
        """Derive two transport cipher states from the final chaining key.

        Matching Rust ``split`` (lines 543-561):
          ``noise_hkdf(ck, b"", 2)`` → ``(c1_key, c2_key)``
          Both ciphers have ``use_extracted_nonce=True``.

        Returns:
            Tuple of ``(c1, c2)`` NoiseCipherState instances.
        """
        outputs = noise_hkdf(self._chaining_key, b"", 2)
        c1 = NoiseCipherState(outputs[0], use_extracted_nonce=True)
        c2 = NoiseCipherState(outputs[1], use_extracted_nonce=True)
        return c1, c2


# ---------------------------------------------------------------------------
# NoiseHandshakeState
# ---------------------------------------------------------------------------


class NoiseHandshakeState:
    """Orchestrates the Noise XX handshake message exchange.

    Implements the three-message XX pattern:
      - Msg 1 (Initiator): ``e``
      - Msg 2 (Responder): ``e, ee, s, es``
      - Msg 3 (Initiator): ``s, se``

    Matches Rust ``NoiseHandshakeState`` (``noise_protocol.rs`` lines 595-1250).
    """

    # XX message patterns (confirmed noise_protocol.rs lines 1265-1275)
    _XX_PATTERNS: tuple[list[str], ...] = (
        ["E"],  # -> e
        ["E", "EE", "S", "ES"],  # <- e, ee, s, es
        ["S", "SE"],  # -> s, se
    )

    def __init__(
        self,
        role: NoiseRole,
        local_static_private: bytes,
        remote_static_public: bytes | None = None,
    ) -> None:
        """Initialise a Noise XX handshake state.

        Applies the empty prologue (``mix_hash(b"")``) matching Rust line 662.

        Args:
            role: ``INITIATOR`` or ``RESPONDER``.
            local_static_private: 32-byte X25519 local static private key.
            remote_static_public: Optional 32-byte remote static public key
                (not used for XX pattern).
        """
        self._role = role
        self._local_static_private = bytes(local_static_private)
        self._local_static_public = public_key_from_private(local_static_private)
        self._local_ephemeral_private: bytes | None = None
        self._local_ephemeral_public: bytes | None = None
        self._remote_static_public: bytes | None = (
            bytes(remote_static_public) if remote_static_public is not None else None
        )
        self._remote_ephemeral_public: bytes | None = None

        self._symmetric_state = NoiseSymmetricState(NOISE_PROTOCOL_NAME)
        self._patterns = self._XX_PATTERNS
        self._current_pattern = 0

        # Empty prologue for XX pattern (noise_protocol.rs line 662)
        self._symmetric_state.mix_hash(b"")

    def is_handshake_complete(self) -> bool:
        """Return True when all message patterns have been processed."""
        return self._current_pattern >= len(self._patterns)

    def get_transport_ciphers(self) -> tuple[NoiseCipherState, NoiseCipherState]:
        """Split into transport cipher pair once handshake is complete.

        Cipher assignment (confirmed noise_protocol.rs lines 1235-1240):
          - Initiator: ``(send=c1, recv=c2)``
          - Responder: ``(send=c2, recv=c1)``

        Returns:
            Tuple of ``(send_cipher, recv_cipher)``.

        Raises:
            NoiseStateError: If handshake is not yet complete.
        """
        if not self.is_handshake_complete():
            raise NoiseStateError(
                "Handshake is not complete; cannot get transport ciphers"
            )
        c1, c2 = self._symmetric_state.split()
        if self._role == NoiseRole.INITIATOR:
            return c1, c2  # send=c1, recv=c2
        else:
            return c2, c1  # send=c2, recv=c1

    def get_remote_static_public_key(self) -> bytes | None:
        """Return the authenticated remote static public key after handshake."""
        return self._remote_static_public

    def get_handshake_hash(self) -> bytes:
        """Return the final handshake hash for channel binding."""
        return self._symmetric_state.get_handshake_hash()

    def write_message(self, payload: bytes) -> bytes:
        """Process the next outbound handshake message pattern and produce bytes.

        Matching Rust ``write_message`` (lines 679-904).

        Args:
            payload: Optional payload bytes (typically empty for XX).

        Returns:
            Handshake message bytes to send to the peer.

        Raises:
            NoiseStateError: If the handshake is already complete.
            NoiseError: If required keys are missing.
        """
        if self.is_handshake_complete():
            raise NoiseStateError("Handshake is complete; cannot write more messages")

        message_buffer = bytearray()
        patterns = self._patterns[self._current_pattern]

        for token in patterns:
            match token:
                case "E":
                    # Generate fresh ephemeral key
                    self._local_ephemeral_private = generate_private_key()
                    self._local_ephemeral_public = public_key_from_private(
                        self._local_ephemeral_private
                    )
                    message_buffer.extend(self._local_ephemeral_public)
                    self._symmetric_state.mix_hash(self._local_ephemeral_public)

                case "S":
                    # Send static key (encrypt_and_hash encrypts if key exists)
                    encrypted_static = self._symmetric_state.encrypt_and_hash(
                        self._local_static_public
                    )
                    message_buffer.extend(encrypted_static)

                case "EE":
                    # DH(local_ephemeral, remote_ephemeral)
                    self._dh_mix_key(
                        self._local_ephemeral_private,
                        self._remote_ephemeral_public,
                        "EE",
                    )

                case "ES":
                    # DH(ephemeral, static) — direction depends on role
                    if self._role == NoiseRole.INITIATOR:
                        # Initiator: DH(local_ephemeral, remote_static)
                        self._dh_mix_key(
                            self._local_ephemeral_private,
                            self._remote_static_public,
                            "ES(initiator)",
                        )
                    else:
                        # Responder: DH(local_static, remote_ephemeral)
                        self._dh_mix_key(
                            self._local_static_private,
                            self._remote_ephemeral_public,
                            "ES(responder)",
                        )

                case "SE":
                    # DH(static, ephemeral) — direction depends on role
                    if self._role == NoiseRole.INITIATOR:
                        # Initiator: DH(local_static, remote_ephemeral)
                        self._dh_mix_key(
                            self._local_static_private,
                            self._remote_ephemeral_public,
                            "SE(initiator)",
                        )
                    else:
                        # Responder: DH(local_ephemeral, remote_static)
                        self._dh_mix_key(
                            self._local_ephemeral_private,
                            self._remote_static_public,
                            "SE(responder)",
                        )

        # Encrypt and append payload
        encrypted_payload = self._symmetric_state.encrypt_and_hash(bytes(payload))
        message_buffer.extend(encrypted_payload)
        self._current_pattern += 1
        return bytes(message_buffer)

    def read_message(self, message: bytes) -> bytes:
        """Process the next inbound handshake message and extract payload.

        Matching Rust ``read_message`` (lines 907-1219).

        Args:
            message: Raw handshake message bytes received from the peer.

        Returns:
            Decrypted payload bytes (typically empty for XX).

        Raises:
            NoiseStateError: If the handshake is already complete.
            NoiseError: If the message is too short or keys are missing.
            AuthenticationError: If decryption/authentication fails (fails closed).
        """
        if self.is_handshake_complete():
            raise NoiseStateError("Handshake is complete; cannot read more messages")

        patterns = self._patterns[self._current_pattern]
        offset = 0
        message = bytes(message)

        for token in patterns:
            match token:
                case "E":
                    if offset + _DH_KEY_SIZE > len(message):
                        raise NoiseError(
                            f"Message too short for ephemeral key at offset {offset}"
                        )
                    ephemeral_bytes = message[offset : offset + _DH_KEY_SIZE]
                    offset += _DH_KEY_SIZE
                    self._remote_ephemeral_public = ephemeral_bytes
                    self._symmetric_state.mix_hash(ephemeral_bytes)

                case "S":
                    # Static key may be encrypted (32 + 16 tag) or plain (32)
                    key_len = (
                        _DH_KEY_SIZE + _TAG_SIZE
                        if self._symmetric_state.has_cipher_key()
                        else _DH_KEY_SIZE
                    )
                    if offset + key_len > len(message):
                        raise NoiseError(
                            f"Message too short for static key at offset {offset}"
                        )
                    static_data = message[offset : offset + key_len]
                    offset += key_len
                    decrypted_static = self._symmetric_state.decrypt_and_hash(
                        static_data
                    )
                    if len(decrypted_static) != _DH_KEY_SIZE:
                        msg = (
                            f"Decrypted static key has wrong length: "
                            f"{len(decrypted_static)}"
                        )
                        raise AuthenticationError(msg)
                    try:
                        validated = validate_public_key(decrypted_static)
                    except InvalidKeyError as exc:
                        raise AuthenticationError(
                            "Static public key validation failed"
                        ) from exc
                    self._remote_static_public = validated

                case "EE":
                    self._dh_mix_key(
                        self._local_ephemeral_private,
                        self._remote_ephemeral_public,
                        "EE",
                    )

                case "ES":
                    if self._role == NoiseRole.INITIATOR:
                        self._dh_mix_key(
                            self._local_ephemeral_private,
                            self._remote_static_public,
                            "ES(initiator)",
                        )
                    else:
                        self._dh_mix_key(
                            self._local_static_private,
                            self._remote_ephemeral_public,
                            "ES(responder)",
                        )

                case "SE":
                    if self._role == NoiseRole.INITIATOR:
                        self._dh_mix_key(
                            self._local_static_private,
                            self._remote_ephemeral_public,
                            "SE(initiator)",
                        )
                    else:
                        self._dh_mix_key(
                            self._local_ephemeral_private,
                            self._remote_static_public,
                            "SE(responder)",
                        )

        # Decrypt payload (remaining bytes)
        payload_bytes = message[offset:]
        # AuthenticationError raised internally if decryption fails (fails closed)
        decrypted_payload = self._symmetric_state.decrypt_and_hash(payload_bytes)
        self._current_pattern += 1
        return decrypted_payload

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _dh_mix_key(
        self,
        local_private: bytes | None,
        remote_public: bytes | None,
        label: str,
    ) -> None:
        """Perform DH and mix the result into the symmetric state.

        Args:
            local_private: Local 32-byte X25519 private key.
            remote_public: Remote 32-byte X25519 public key.
            label: Descriptive label for error messages.

        Raises:
            NoiseError: If either key is None.
            KeyExchangeError: If the DH operation fails.
        """
        if local_private is None:
            raise NoiseError(f"Missing local private key for DH operation: {label}")
        if remote_public is None:
            raise NoiseError(f"Missing remote public key for DH operation: {label}")
        shared = diffie_hellman(local_private, remote_public)
        self._symmetric_state.mix_key(shared)
