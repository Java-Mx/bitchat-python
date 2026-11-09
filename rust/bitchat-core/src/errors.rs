//! Structured error encoding for deterministic mapping to BitChat Python exceptions.

use pyo3::exceptions::PyValueError;
use pyo3::PyErr;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CoreErrorKind {
    InvalidPacket,
    PacketEncoding,
    PacketDecoding,
    UnsupportedProtocolVersion,
    UnknownMessageType,
    InvalidFragment,
    FragmentPayload,
    FragmentLimitExceeded,
    Framing,
    Value,
}

impl CoreErrorKind {
    pub const fn tag(self) -> &'static str {
        match self {
            Self::InvalidPacket => "InvalidPacketError",
            Self::PacketEncoding => "PacketEncodingError",
            Self::PacketDecoding => "PacketDecodingError",
            Self::UnsupportedProtocolVersion => "UnsupportedProtocolVersionError",
            Self::UnknownMessageType => "UnknownMessageTypeError",
            Self::InvalidFragment => "InvalidFragmentError",
            Self::FragmentPayload => "FragmentPayloadError",
            Self::FragmentLimitExceeded => "FragmentLimitExceededError",
            Self::Framing => "FramingError",
            Self::Value => "ValueError",
        }
    }
}

#[derive(Debug, Clone)]
pub struct CoreError {
    pub kind: CoreErrorKind,
    pub message: String,
}

impl CoreError {
    pub fn new(kind: CoreErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
        }
    }

    pub fn invalid_packet(msg: impl Into<String>) -> Self {
        Self::new(CoreErrorKind::InvalidPacket, msg)
    }

    pub fn packet_encoding(msg: impl Into<String>) -> Self {
        Self::new(CoreErrorKind::PacketEncoding, msg)
    }

    pub fn packet_decoding(msg: impl Into<String>) -> Self {
        Self::new(CoreErrorKind::PacketDecoding, msg)
    }

    pub fn unsupported_version(msg: impl Into<String>) -> Self {
        Self::new(CoreErrorKind::UnsupportedProtocolVersion, msg)
    }

    pub fn unknown_message_type(msg: impl Into<String>) -> Self {
        Self::new(CoreErrorKind::UnknownMessageType, msg)
    }

    pub fn invalid_fragment(msg: impl Into<String>) -> Self {
        Self::new(CoreErrorKind::InvalidFragment, msg)
    }

    pub fn fragment_payload(msg: impl Into<String>) -> Self {
        Self::new(CoreErrorKind::FragmentPayload, msg)
    }

    pub fn fragment_limit(msg: impl Into<String>) -> Self {
        Self::new(CoreErrorKind::FragmentLimitExceeded, msg)
    }

    pub fn framing(msg: impl Into<String>) -> Self {
        Self::new(CoreErrorKind::Framing, msg)
    }

    pub fn value_err(msg: impl Into<String>) -> Self {
        Self::new(CoreErrorKind::Value, msg)
    }
}

impl From<CoreError> for PyErr {
    fn from(err: CoreError) -> Self {
        PyValueError::new_err(format!(
            "__BITCHAT_ERR__:{}::{}",
            err.kind.tag(),
            err.message
        ))
    }
}
