//! Wire-compatible binary packet encoding, decoding, PKCS#7-style block padding, and Peer ID helpers.

use pyo3::prelude::*;
use pyo3::types::PyBytes;
use rand::RngCore;

use crate::errors::CoreError;

pub const PROTOCOL_VERSION: u8 = 1;
pub const FIXED_HEADER_SIZE: usize = 14;
pub const SENDER_ID_SIZE: usize = 8;
pub const RECIPIENT_ID_SIZE: usize = 8;
pub const SIGNATURE_SIZE: usize = 64;
pub const MIN_PACKET_SIZE: usize = FIXED_HEADER_SIZE + SENDER_ID_SIZE;
pub const MAX_PAYLOAD_SIZE: usize = 65535;

pub const FLAG_HAS_RECIPIENT: u8 = 0x01;
pub const FLAG_HAS_SIGNATURE: u8 = 0x02;
pub const FLAG_IS_COMPRESSED: u8 = 0x04;
pub const VALID_FLAGS_MASK: u8 = FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE | FLAG_IS_COMPRESSED;

pub const BLOCK_SIZES: [usize; 4] = [256, 512, 1024, 2048];
pub const PADDING_OVERHEAD_ESTIMATE: usize = 16;
pub const MAX_PADDING_SIZE: usize = 255;

pub type RawDecodedPacket = (
    u8,
    u8,
    u8,
    u64,
    u8,
    Vec<u8>,
    Option<Vec<u8>>,
    Vec<u8>,
    Option<Vec<u8>>,
);

#[inline]
pub fn is_valid_message_type(raw: u8) -> bool {
    matches!(raw, 0x01..=0x0C | 0x10..=0x13 | 0x20..=0x25)
}

#[inline]
pub fn optimal_block_size(data_length: usize) -> usize {
    let total_needed = data_length.saturating_add(PADDING_OVERHEAD_ESTIMATE);
    for &block_size in &BLOCK_SIZES {
        if total_needed <= block_size {
            return block_size;
        }
    }
    data_length
}

pub fn pad_bytes(data: &[u8], target_size: usize) -> Vec<u8> {
    if data.len() >= target_size {
        return data.to_vec();
    }
    let padding_needed = target_size - data.len();
    if padding_needed > MAX_PADDING_SIZE {
        return data.to_vec();
    }
    let mut out = Vec::with_capacity(target_size);
    out.extend_from_slice(data);
    if padding_needed > 1 {
        let start = out.len();
        out.resize(target_size - 1, 0u8);
        rand::thread_rng().fill_bytes(&mut out[start..]);
    }
    out.push(padding_needed as u8);
    out
}

pub fn unpad_slice(data: &[u8]) -> &[u8] {
    if data.is_empty() {
        return data;
    }
    let pad_len = data[data.len() - 1] as usize;
    if pad_len == 0 || pad_len > data.len() {
        return data;
    }
    &data[..data.len() - pad_len]
}

#[allow(clippy::too_many_arguments)]
pub fn encode_packet_bytes(
    version: i64,
    message_type: i64,
    ttl: i64,
    timestamp: i128,
    flags: i64,
    sender_id: &[u8],
    recipient_id: Option<&[u8]>,
    payload: &[u8],
    signature: Option<&[u8]>,
    add_padding: bool,
) -> Result<Vec<u8>, CoreError> {
    if version != PROTOCOL_VERSION as i64 {
        return Err(CoreError::packet_encoding(format!(
            "Unsupported protocol version: {version}"
        )));
    }
    if !(0..=255).contains(&message_type) || !is_valid_message_type(message_type as u8) {
        return Err(CoreError::packet_encoding(format!(
            "Invalid message_type: {message_type}"
        )));
    }
    if !(0..=255).contains(&ttl) {
        return Err(CoreError::packet_encoding(format!(
            "TTL must be 0..255, got {ttl}"
        )));
    }
    if !(0..=(u64::MAX as i128)).contains(&timestamp) {
        return Err(CoreError::packet_encoding(format!(
            "Timestamp must be uint64, got {timestamp}"
        )));
    }
    if !(0..=255).contains(&flags) {
        return Err(CoreError::packet_encoding(format!(
            "Invalid flags byte: {flags:#x}"
        )));
    }
    if sender_id.len() != SENDER_ID_SIZE {
        return Err(CoreError::packet_encoding(format!(
            "sender_id must be {SENDER_ID_SIZE} bytes, got {}",
            sender_id.len()
        )));
    }
    if payload.len() > MAX_PAYLOAD_SIZE {
        return Err(CoreError::packet_encoding(format!(
            "payload exceeds max size ({MAX_PAYLOAD_SIZE} bytes): {}",
            payload.len()
        )));
    }

    let flags_u8 = flags as u8;
    let has_recipient = (flags_u8 & FLAG_HAS_RECIPIENT) != 0;
    let has_signature = (flags_u8 & FLAG_HAS_SIGNATURE) != 0;

    if has_recipient {
        match recipient_id {
            Some(rec) if rec.len() == RECIPIENT_ID_SIZE => {}
            _ => {
                return Err(CoreError::packet_encoding(
                    "Inconsistent recipient_id and FLAG_HAS_RECIPIENT",
                ));
            }
        }
    } else if recipient_id.is_some() {
        return Err(CoreError::packet_encoding(
            "recipient_id provided without FLAG_HAS_RECIPIENT set",
        ));
    }

    if has_signature {
        match signature {
            Some(sig) if sig.len() == SIGNATURE_SIZE => {}
            _ => {
                return Err(CoreError::packet_encoding(
                    "Inconsistent signature and FLAG_HAS_SIGNATURE",
                ));
            }
        }
    } else if signature.is_some() {
        return Err(CoreError::packet_encoding(
            "signature provided without FLAG_HAS_SIGNATURE set",
        ));
    }

    let unpadded_len = FIXED_HEADER_SIZE
        + SENDER_ID_SIZE
        + if has_recipient { RECIPIENT_ID_SIZE } else { 0 }
        + payload.len()
        + if has_signature { SIGNATURE_SIZE } else { 0 };

    let target_size = if add_padding {
        optimal_block_size(unpadded_len)
    } else {
        unpadded_len
    };
    let padding_needed = if add_padding && target_size > unpadded_len {
        let diff = target_size - unpadded_len;
        if diff <= MAX_PADDING_SIZE {
            diff
        } else {
            0
        }
    } else {
        0
    };

    let total_alloc = unpadded_len + padding_needed;
    let mut buf = Vec::with_capacity(total_alloc);

    // Pack 14-byte header (>BBBQBH)
    buf.push(version as u8);
    buf.push(message_type as u8);
    buf.push(ttl as u8);
    buf.extend_from_slice(&(timestamp as u64).to_be_bytes());
    buf.push(flags_u8);
    buf.extend_from_slice(&(payload.len() as u16).to_be_bytes());

    buf.extend_from_slice(sender_id);
    if let Some(rec) = recipient_id {
        buf.extend_from_slice(rec);
    }
    buf.extend_from_slice(payload);
    if let Some(sig) = signature {
        buf.extend_from_slice(sig);
    }

    if padding_needed > 0 {
        if padding_needed > 1 {
            let start = buf.len();
            buf.resize(total_alloc - 1, 0u8);
            rand::thread_rng().fill_bytes(&mut buf[start..]);
        }
        buf.push(padding_needed as u8);
    }

    Ok(buf)
}

pub fn decode_packet_slice(data: &[u8]) -> Result<RawDecodedPacket, CoreError> {
    if data.len() < MIN_PACKET_SIZE {
        return Err(CoreError::packet_decoding(format!(
            "Packet too small: {} bytes, minimum required is {MIN_PACKET_SIZE} bytes",
            data.len()
        )));
    }

    let version = data[0];
    let msg_type_raw = data[1];
    let ttl = data[2];
    let timestamp = u64::from_be_bytes([
        data[3], data[4], data[5], data[6], data[7], data[8], data[9], data[10],
    ]);
    let flags = data[11];
    let payload_len = u16::from_be_bytes([data[12], data[13]]) as usize;

    if version != PROTOCOL_VERSION {
        return Err(CoreError::unsupported_version(format!(
            "Unsupported protocol version: {version} (expected {PROTOCOL_VERSION})"
        )));
    }

    if !is_valid_message_type(msg_type_raw) {
        return Err(CoreError::unknown_message_type(format!(
            "Unknown message type: {msg_type_raw:#04x}"
        )));
    }

    let has_recipient = (flags & FLAG_HAS_RECIPIENT) != 0;
    let has_signature = (flags & FLAG_HAS_SIGNATURE) != 0;

    let expected_unpadded_size = FIXED_HEADER_SIZE
        + SENDER_ID_SIZE
        + if has_recipient { RECIPIENT_ID_SIZE } else { 0 }
        + payload_len
        + if has_signature { SIGNATURE_SIZE } else { 0 };

    if data.len() < expected_unpadded_size {
        return Err(CoreError::packet_decoding(format!(
            "Packet data ({} bytes) is shorter than expected unpadded size ({expected_unpadded_size} bytes)",
            data.len()
        )));
    }

    if data.len() > expected_unpadded_size {
        let padding_needed = data.len() - expected_unpadded_size;
        if padding_needed > MAX_PADDING_SIZE {
            return Err(CoreError::packet_decoding(format!(
                "Trailing bytes ({padding_needed}) exceed maximum valid PKCS#7 padding size (255)"
            )));
        }
        let last_byte = data[data.len() - 1] as usize;
        if last_byte != padding_needed || last_byte == 0 {
            return Err(CoreError::packet_decoding(format!(
                "Malformed packet padding: expected delimiter {padding_needed}, found {last_byte}"
            )));
        }
    }

    let mut offset = FIXED_HEADER_SIZE;
    let sender_id = data[offset..offset + SENDER_ID_SIZE].to_vec();
    offset += SENDER_ID_SIZE;

    let recipient_id = if has_recipient {
        let r = data[offset..offset + RECIPIENT_ID_SIZE].to_vec();
        offset += RECIPIENT_ID_SIZE;
        Some(r)
    } else {
        None
    };

    let payload = data[offset..offset + payload_len].to_vec();
    offset += payload_len;

    let signature = if has_signature {
        let s = data[offset..offset + SIGNATURE_SIZE].to_vec();
        Some(s)
    } else {
        None
    };

    Ok((
        version,
        msg_type_raw,
        ttl,
        timestamp,
        flags,
        sender_id,
        recipient_id,
        payload,
        signature,
    ))
}

#[pyfunction]
pub fn get_optimal_block_size(data_length: usize) -> usize {
    optimal_block_size(data_length)
}

#[pyfunction]
pub fn pad_packet_data<'py>(
    py: Python<'py>,
    data: &[u8],
    target_size: usize,
) -> Bound<'py, PyBytes> {
    let out = pad_bytes(data, target_size);
    PyBytes::new(py, &out)
}

#[pyfunction]
pub fn unpad_packet_data<'py>(py: Python<'py>, data: &[u8]) -> Bound<'py, PyBytes> {
    let slice = unpad_slice(data);
    PyBytes::new(py, slice)
}

pub fn hex_encode_lower(bytes: &[u8]) -> String {
    const HEX_CHARS: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(HEX_CHARS[(b >> 4) as usize] as char);
        out.push(HEX_CHARS[(b & 0x0f) as usize] as char);
    }
    out
}

#[pyfunction]
pub fn peer_id_to_hex(peer_id: &[u8]) -> PyResult<String> {
    if peer_id.len() != SENDER_ID_SIZE {
        return Err(CoreError::invalid_packet(format!(
            "Peer ID must be exactly {SENDER_ID_SIZE} bytes, got {}",
            peer_id.len()
        ))
        .into());
    }
    Ok(hex_encode_lower(peer_id))
}

#[pyfunction]
pub fn peer_id_from_hex<'py>(py: Python<'py>, hex_str: &str) -> PyResult<Bound<'py, PyBytes>> {
    let clean = hex_str.trim().to_ascii_lowercase();
    let bytes = clean.as_bytes();
    if !bytes.len().is_multiple_of(2)
        || !bytes.iter().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
    {
        return Err(
            CoreError::invalid_packet(format!("Invalid hexadecimal peer ID '{hex_str}'")).into(),
        );
    }
    if bytes.len() != SENDER_ID_SIZE * 2 {
        return Err(CoreError::invalid_packet(format!(
            "Hexadecimal peer ID must represent {SENDER_ID_SIZE} bytes (16 hex chars), got {}",
            bytes.len() / 2
        ))
        .into());
    }
    let mut out = [0u8; SENDER_ID_SIZE];
    for i in 0..SENDER_ID_SIZE {
        let hi = match bytes[i * 2] {
            b'0'..=b'9' => bytes[i * 2] - b'0',
            b'a'..=b'f' => bytes[i * 2] - b'a' + 10,
            _ => unreachable!(),
        };
        let lo = match bytes[i * 2 + 1] {
            b'0'..=b'9' => bytes[i * 2 + 1] - b'0',
            b'a'..=b'f' => bytes[i * 2 + 1] - b'a' + 10,
            _ => unreachable!(),
        };
        out[i] = (hi << 4) | lo;
    }
    Ok(PyBytes::new(py, &out))
}

#[pyfunction]
#[pyo3(signature = (version, message_type, ttl, timestamp, flags, sender_id, recipient_id, payload, signature, add_padding=true))]
#[allow(clippy::too_many_arguments)]
pub fn encode_packet_raw<'py>(
    py: Python<'py>,
    version: i64,
    message_type: i64,
    ttl: i64,
    timestamp: i128,
    flags: i64,
    sender_id: &[u8],
    recipient_id: Option<&[u8]>,
    payload: &[u8],
    signature: Option<&[u8]>,
    add_padding: bool,
) -> PyResult<Bound<'py, PyBytes>> {
    let encoded = if payload.len() >= 2048 {
        py.allow_threads(|| {
            encode_packet_bytes(
                version,
                message_type,
                ttl,
                timestamp,
                flags,
                sender_id,
                recipient_id,
                payload,
                signature,
                add_padding,
            )
        })?
    } else {
        encode_packet_bytes(
            version,
            message_type,
            ttl,
            timestamp,
            flags,
            sender_id,
            recipient_id,
            payload,
            signature,
            add_padding,
        )?
    };
    Ok(PyBytes::new(py, &encoded))
}

#[allow(clippy::type_complexity)]
#[pyfunction]
pub fn decode_packet_raw<'py>(
    py: Python<'py>,
    raw_bytes: &[u8],
) -> PyResult<(
    u8,
    u8,
    u8,
    u64,
    u8,
    Bound<'py, PyBytes>,
    Option<Bound<'py, PyBytes>>,
    Bound<'py, PyBytes>,
    Option<Bound<'py, PyBytes>>,
)> {
    let (version, msg_type_raw, ttl, timestamp, flags, sender, recipient, payload, signature) =
        decode_packet_slice(raw_bytes)?;

    Ok((
        version,
        msg_type_raw,
        ttl,
        timestamp,
        flags,
        PyBytes::new(py, &sender),
        recipient.as_ref().map(|r| PyBytes::new(py, r)),
        PyBytes::new(py, &payload),
        signature.as_ref().map(|s| PyBytes::new(py, s)),
    ))
}
