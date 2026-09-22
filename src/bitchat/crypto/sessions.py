"""
High-level Noise session abstraction for BitChat.

``NoiseSession`` wraps a complete per-peer Noise XX handshake and transport
cipher lifecycle.  It is the only public interface that upper-layer code
(routing, application) should use for Noise operations.

The session API exposes only the operations required by higher layers:
  - ``start_handshake()``
  - ``process_handshake_message()``
  - ``encrypt()``
  - ``decrypt()``
  - ``close()``

Internal Noise state (cipher keys, chaining key, handshake hash) is NOT
exposed to callers.  Read-only metadata (state, role, remote fingerprint) is
accessible through properties.

Reference: Rust ``noise_session.rs`` ``NoiseSession`` (lines 56-426).
"""

from __future__ import annotations

from bitchat.crypto.identity import LocalIdentity, calculate_fingerprint
from bitchat.crypto.noise import (
    NoiseCipherState,
    NoiseHandshakeState,
    NoiseRole,
    NoiseSessionState,
    determine_handshake_role,
)
from bitchat.exceptions import (
    NoiseError,
    NoiseStateError,
)


class NoiseSession:
    """Per-peer Noise XX session — handshake and transport cipher lifecycle.

    State machine:
      UNINITIALIZED → (start_handshake or receive) → HANDSHAKING
      HANDSHAKING   → (all messages exchanged)     → ESTABLISHED
      ESTABLISHED   → (close)                      → CLOSED
      HANDSHAKING   → (auth failure)               → FAILED
      Any           → (close)                      → CLOSED

    Only the ESTABLISHED state allows encrypt/decrypt.  Calling them in any
    other state raises ``NoiseStateError``.

    Args:
        local_identity: Local cryptographic identity (holds static X25519 key).
        remote_peer_id: Remote peer ID as a hex string (for tie-breaking).
    """

    def __init__(
        self,
        local_identity: LocalIdentity,
        remote_peer_id: str,
    ) -> None:
        self._local_identity = local_identity
        self._remote_peer_id = remote_peer_id
        self._role: NoiseRole = determine_handshake_role(
            local_identity.peer_id_hex, remote_peer_id
        )
        self._state: NoiseSessionState = NoiseSessionState.UNINITIALIZED
        self._handshake_state: NoiseHandshakeState | None = None
        self._send_cipher: NoiseCipherState | None = None
        self._recv_cipher: NoiseCipherState | None = None
        self._remote_static_public: bytes | None = None
        self._handshake_hash: bytes | None = None
        self._remote_fingerprint: str | None = None

    # -----------------------------------------------------------------------
    # Properties — read-only session metadata
    # -----------------------------------------------------------------------

    @property
    def state(self) -> NoiseSessionState:
        """Current lifecycle state of this session."""
        return self._state

    @property
    def role(self) -> NoiseRole:
        """Noise role (INITIATOR or RESPONDER) for this session."""
        return self._role

    @property
    def remote_peer_id(self) -> str:
        """Hex-encoded remote peer ID."""
        return self._remote_peer_id

    @property
    def remote_fingerprint(self) -> str | None:
        """64-char hex fingerprint of the remote peer's X25519 static key.

        Available only after handshake reaches ESTABLISHED.
        """
        return self._remote_fingerprint

    @property
    def handshake_hash(self) -> bytes | None:
        """32-byte handshake transcript hash for channel binding.

        Available only after handshake reaches ESTABLISHED.
        """
        return self._handshake_hash

    @property
    def is_established(self) -> bool:
        """Return True if the session is in the ESTABLISHED state."""
        return self._state == NoiseSessionState.ESTABLISHED

    # -----------------------------------------------------------------------
    # Handshake
    # -----------------------------------------------------------------------

    def start_handshake(self) -> bytes | None:
        """Initialise the handshake and return the first message if Initiator.

        Valid from UNINITIALIZED state only.

        Returns:
            - Initiator: first handshake message bytes to send.
            - Responder: ``None`` (waits for initiator's first message).

        Raises:
            NoiseStateError: If called from a state other than UNINITIALIZED.
        """
        if self._state != NoiseSessionState.UNINITIALIZED:
            raise NoiseStateError(
                f"start_handshake() called in invalid state: {self._state.value}"
            )
        self._handshake_state = NoiseHandshakeState(
            role=self._role,
            local_static_private=self._local_identity.x25519_private,
        )
        self._state = NoiseSessionState.HANDSHAKING
        if self._role == NoiseRole.INITIATOR:
            return self._handshake_state.write_message(b"")
        return None

    def process_handshake_message(self, message: bytes) -> bytes | None:
        """Process an inbound handshake message and return response if needed.

        Handles both Initiator and Responder message flows.  Automatically
        transitions to ESTABLISHED once all patterns are complete.

        Matching Rust ``NoiseSession::process_handshake_message``
        (``noise_session.rs`` lines 191-366).

        Args:
            message: Raw handshake message bytes from the peer.

        Returns:
            Response bytes to send back, or ``None`` if no response is needed.

        Raises:
            NoiseStateError: If called outside HANDSHAKING or UNINITIALIZED
                (Responder auto-initialises from UNINITIALIZED).
            NoiseError: If the handshake message is malformed.
            AuthenticationError: If authentication fails during handshake.
        """
        # Responder may auto-initialise (matching Rust lines 206-227)
        if (
            self._state == NoiseSessionState.UNINITIALIZED
            and self._role == NoiseRole.RESPONDER
        ):
            self._handshake_state = NoiseHandshakeState(
                role=self._role,
                local_static_private=self._local_identity.x25519_private,
            )
            self._state = NoiseSessionState.HANDSHAKING

        if self._state != NoiseSessionState.HANDSHAKING:
            raise NoiseStateError(
                f"process_handshake_message() called in invalid state: "
                f"{self._state.value}"
            )
        if self._handshake_state is None:
            raise NoiseStateError("Handshake state is not initialised")

        try:
            _payload = self._handshake_state.read_message(bytes(message))
        except (NoiseStateError, NoiseError):
            self._state = NoiseSessionState.FAILED
            raise

        # Check if we need to write a response
        response: bytes | None = None
        if not self._handshake_state.is_handshake_complete():
            try:
                response = self._handshake_state.write_message(b"")
            except (NoiseStateError, NoiseError):
                self._state = NoiseSessionState.FAILED
                raise

        # Check completion after possible write
        if self._handshake_state.is_handshake_complete():
            self._finalise_handshake()

        return response

    def _finalise_handshake(self) -> None:
        """Extract transport ciphers and transition to ESTABLISHED."""
        assert self._handshake_state is not None
        send_cipher, recv_cipher = self._handshake_state.get_transport_ciphers()
        self._send_cipher = send_cipher
        self._recv_cipher = recv_cipher
        self._remote_static_public = (
            self._handshake_state.get_remote_static_public_key()
        )
        self._handshake_hash = self._handshake_state.get_handshake_hash()
        if self._remote_static_public is not None:
            self._remote_fingerprint = calculate_fingerprint(self._remote_static_public)
        self._handshake_state = None  # Clear handshake state (Rust line 292)
        self._state = NoiseSessionState.ESTABLISHED

    # -----------------------------------------------------------------------
    # Transport
    # -----------------------------------------------------------------------

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt a transport message.

        Only valid in ESTABLISHED state.

        Args:
            plaintext: Data to encrypt.

        Returns:
            ``nonce(4) || ciphertext+tag`` bytes.

        Raises:
            NoiseStateError: If the session is not ESTABLISHED.
            EncryptionError: If encryption fails.
        """
        if self._state != NoiseSessionState.ESTABLISHED:
            raise NoiseStateError(
                f"encrypt() requires ESTABLISHED state, got {self._state.value}"
            )
        if self._send_cipher is None:
            raise NoiseStateError("No send cipher available")
        return self._send_cipher.encrypt(bytes(plaintext), b"")

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt a transport message.

        Only valid in ESTABLISHED state.  Raises ``ReplayError`` for duplicate
        transport nonces.

        Args:
            ciphertext: ``nonce(4) || ciphertext+tag`` bytes.

        Returns:
            Decrypted plaintext bytes.

        Raises:
            NoiseStateError: If the session is not ESTABLISHED.
            DecryptionError: If authentication fails.
            ReplayError: If the transport nonce is a replay.
        """
        if self._state != NoiseSessionState.ESTABLISHED:
            raise NoiseStateError(
                f"decrypt() requires ESTABLISHED state, got {self._state.value}"
            )
        if self._recv_cipher is None:
            raise NoiseStateError("No receive cipher available")
        return self._recv_cipher.decrypt(bytes(ciphertext), b"")

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    def close(self) -> None:
        """Close the session and zero out cipher key references.

        Transitions to CLOSED state.  Subsequent encrypt/decrypt will raise
        ``NoiseStateError``.
        """
        self._send_cipher = None
        self._recv_cipher = None
        self._handshake_state = None
        self._state = NoiseSessionState.CLOSED
