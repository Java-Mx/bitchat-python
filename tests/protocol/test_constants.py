"""Unit tests for BitChat protocol constants and MessageType enum."""

import pytest

from bitchat.protocol.constants import (
    BITCHAT_CHARACTERISTIC_UUID,
    BITCHAT_SERVICE_UUID,
    BLOCK_SIZES,
    BROADCAST_RECIPIENT,
    COVER_TRAFFIC_PREFIX,
    CURRENT_PROTOCOL_VERSION,
    FIXED_HEADER_SIZE,
    FLAG_HAS_RECIPIENT,
    FLAG_HAS_SIGNATURE,
    FLAG_IS_COMPRESSED,
    MAX_PADDING_SIZE,
    MAXIMUM_PROTOCOL_VERSION,
    MINIMUM_PACKET_SIZE,
    MINIMUM_PROTOCOL_VERSION,
    PADDING_OVERHEAD_ESTIMATE,
    RECIPIENT_ID_SIZE,
    SENDER_ID_SIZE,
    SIGNATURE_SIZE,
    MessageType,
)


class TestProtocolConstants:
    """Validate protocol constants match the BitChat specification."""

    def test_version_constants(self) -> None:
        """Protocol version constants are strictly 1."""
        assert CURRENT_PROTOCOL_VERSION == 1
        assert MINIMUM_PROTOCOL_VERSION == 1
        assert MAXIMUM_PROTOCOL_VERSION == 1

    def test_ble_uuids(self) -> None:
        """BLE UUID constants match the reference implementation."""
        assert BITCHAT_SERVICE_UUID == "F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C"
        assert BITCHAT_CHARACTERISTIC_UUID == "A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D"

    def test_packet_flags(self) -> None:
        """Header flag bitmask constants match the wire protocol."""
        assert FLAG_HAS_RECIPIENT == 0x01
        assert FLAG_HAS_SIGNATURE == 0x02
        assert FLAG_IS_COMPRESSED == 0x04

    def test_size_constants(self) -> None:
        """Field size constants match the wire specification."""
        assert SENDER_ID_SIZE == 8
        assert RECIPIENT_ID_SIZE == 8
        assert SIGNATURE_SIZE == 64
        assert FIXED_HEADER_SIZE == 14
        assert MINIMUM_PACKET_SIZE == 22
        assert BROADCAST_RECIPIENT == b"\xff" * 8
        assert len(BROADCAST_RECIPIENT) == 8

    def test_padding_constants(self) -> None:
        """Padding constants align with Swift/Rust block configurations."""
        assert BLOCK_SIZES == (256, 512, 1024, 2048)
        assert PADDING_OVERHEAD_ESTIMATE == 16
        assert MAX_PADDING_SIZE == 255
        assert COVER_TRAFFIC_PREFIX == "☂DUMMY☂"


class TestMessageTypeEnum:
    """Validate MessageType IntEnum members and values."""

    def test_all_22_message_types_defined(self) -> None:
        """All 22 Rust MessageType enum variants are defined with exact values."""
        expected_types = {
            "Announce": 0x01,
            "KeyExchange": 0x02,
            "Leave": 0x03,
            "Message": 0x04,
            "FragmentStart": 0x05,
            "FragmentContinue": 0x06,
            "FragmentEnd": 0x07,
            "ChannelAnnounce": 0x08,
            "ChannelRetention": 0x09,
            "DeliveryAck": 0x0A,
            "DeliveryStatusRequest": 0x0B,
            "ReadReceipt": 0x0C,
            "NoiseHandshakeInit": 0x10,
            "NoiseHandshakeResp": 0x11,
            "NoiseEncrypted": 0x12,
            "NoiseIdentityAnnounce": 0x13,
            "VersionHello": 0x20,
            "VersionAck": 0x21,
            "ProtocolAck": 0x22,
            "ProtocolNack": 0x23,
            "SystemValidation": 0x24,
            "HandshakeRequest": 0x25,
        }

        assert len(MessageType) == 22
        for name, value in expected_types.items():
            assert getattr(MessageType, name).value == value
            assert MessageType(value).name == name

    def test_invalid_message_type_raises_value_error(self) -> None:
        """Unknown message type integers raise ValueError."""
        with pytest.raises(ValueError):
            MessageType(0x00)
        with pytest.raises(ValueError):
            MessageType(0x0E)
        with pytest.raises(ValueError):
            MessageType(0xFF)
