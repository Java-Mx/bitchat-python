"""Unit tests for BitChat data models."""

from datetime import UTC, datetime

import pytest

from bitchat.models.peer import Peer, PeerConnectionState


class TestPeerModel:
    """Tests for the Peer dataclass and PeerConnectionState enum."""

    def test_default_peer_creation(self) -> None:
        """Creating a peer with only peer_id uses sensible defaults."""
        peer = Peer(peer_id="a1b2c3d4e5f60718")
        assert peer.peer_id == "a1b2c3d4e5f60718"
        assert peer.nickname is None
        assert peer.fingerprint is None
        assert peer.last_seen is None
        assert peer.connection_state == PeerConnectionState.DISCONNECTED
        assert not peer.is_online
        assert peer.display_name == "a1b2c3d4e5f60718"

    def test_peer_with_nickname_display_name(self) -> None:
        """Display name prioritizes nickname over peer_id."""
        peer = Peer(peer_id="peer123", nickname="Alice")
        assert peer.display_name == "Alice"

    def test_peer_empty_nickname_fallback(self) -> None:
        """Empty string nickname falls back to peer_id."""
        peer = Peer(peer_id="peer123", nickname="")
        assert peer.display_name == "peer123"

    @pytest.mark.parametrize(
        ("state", "expected_online"),
        [
            (PeerConnectionState.DISCONNECTED, False),
            (PeerConnectionState.CONNECTED, True),
            (PeerConnectionState.AUTHENTICATING, True),
            (PeerConnectionState.AUTHENTICATED, True),
        ],
    )
    def test_peer_online_state_mapping(
        self, state: PeerConnectionState, expected_online: bool
    ) -> None:
        """is_online accurately reflects whether the connection state is active."""
        peer = Peer(peer_id="peer123", connection_state=state)
        assert peer.is_online is expected_online

    def test_peer_full_initialization(self) -> None:
        """All fields can be explicitly configured."""
        now = datetime.now(UTC)
        peer = Peer(
            peer_id="0102030405060708",
            nickname="Bob",
            fingerprint="e3b0c44298fc1c149afbf4c8996fb924",
            last_seen=now,
            connection_state=PeerConnectionState.AUTHENTICATED,
        )
        assert peer.peer_id == "0102030405060708"
        assert peer.nickname == "Bob"
        assert peer.fingerprint == "e3b0c44298fc1c149afbf4c8996fb924"
        assert peer.last_seen == now
        assert peer.connection_state == PeerConnectionState.AUTHENTICATED
        assert peer.is_online is True
        assert peer.display_name == "Bob"

    def test_peer_connection_state_enum_values(self) -> None:
        """Enum string values match the protocol specification."""
        assert PeerConnectionState.DISCONNECTED.value == "disconnected"
        assert PeerConnectionState.CONNECTED.value == "connected"
        assert PeerConnectionState.AUTHENTICATING.value == "authenticating"
        assert PeerConnectionState.AUTHENTICATED.value == "authenticated"
