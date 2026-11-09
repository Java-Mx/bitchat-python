//! High-performance 8-byte magic + length-prefixed TCP stream framing with O(1) cursor compaction.

use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::errors::CoreError;
use crate::protocol::hex_encode_lower;

pub const FRAME_MAGIC: [u8; 4] = *b"BC\x01\x00";
pub const HEADER_SIZE: usize = 8;
pub const MAX_FRAME_SIZE: usize = 65_536;

pub fn encode_frame_vec(payload: &[u8], max_frame_size: usize) -> Result<Vec<u8>, CoreError> {
    let length = payload.len();
    if length > max_frame_size {
        return Err(CoreError::framing(format!(
            "Payload size {length} exceeds maximum frame limit of {max_frame_size} bytes"
        )));
    }
    let mut out = Vec::with_capacity(HEADER_SIZE + length);
    out.extend_from_slice(&FRAME_MAGIC);
    out.extend_from_slice(&(length as u32).to_be_bytes());
    out.extend_from_slice(payload);
    Ok(out)
}

#[pyfunction]
#[pyo3(signature = (payload, max_frame_size=MAX_FRAME_SIZE))]
pub fn encode_frame_bytes<'py>(
    py: Python<'py>,
    payload: &[u8],
    max_frame_size: usize,
) -> PyResult<Bound<'py, PyBytes>> {
    let out = encode_frame_vec(payload, max_frame_size)?;
    Ok(PyBytes::new(py, &out))
}

#[pyclass]
pub struct NativeStreamFramer {
    max_frame_size: usize,
    buffer: Vec<u8>,
    read_pos: usize,
}

impl NativeStreamFramer {
    fn compact_if_needed(&mut self) {
        if self.read_pos > 0 {
            if self.read_pos == self.buffer.len() {
                self.buffer.clear();
                self.read_pos = 0;
            } else if self.read_pos >= 4096 || self.read_pos * 2 >= self.buffer.len() {
                self.buffer.drain(0..self.read_pos);
                self.read_pos = 0;
            }
        }
    }
}

#[pymethods]
impl NativeStreamFramer {
    #[new]
    #[pyo3(signature = (max_frame_size=MAX_FRAME_SIZE))]
    pub fn new(max_frame_size: usize) -> Self {
        Self {
            max_frame_size,
            buffer: Vec::with_capacity(8192),
            read_pos: 0,
        }
    }

    #[getter]
    pub fn max_frame_size(&self) -> usize {
        self.max_frame_size
    }

    #[setter]
    pub fn set_max_frame_size(&mut self, value: usize) {
        self.max_frame_size = value;
    }

    #[getter]
    pub fn buffered_bytes(&self) -> usize {
        self.buffer.len().saturating_sub(self.read_pos)
    }

    pub fn clear(&mut self) {
        self.buffer.clear();
        self.read_pos = 0;
    }

    pub fn feed<'py>(
        &mut self,
        py: Python<'py>,
        chunk: &[u8],
    ) -> PyResult<Vec<Bound<'py, PyBytes>>> {
        if !chunk.is_empty() {
            self.buffer.extend_from_slice(chunk);
        }
        let mut frames = Vec::new();

        while self.buffer.len().saturating_sub(self.read_pos) >= HEADER_SIZE {
            let hdr = &self.buffer[self.read_pos..self.read_pos + HEADER_SIZE];
            let magic = &hdr[0..4];
            if magic != FRAME_MAGIC {
                let magic_hex = hex_encode_lower(magic);
                self.compact_if_needed();
                return Err(CoreError::framing(format!(
                    "Invalid frame magic: {magic_hex} (expected 42430100)"
                ))
                .into());
            }

            let payload_length = u32::from_be_bytes([hdr[4], hdr[5], hdr[6], hdr[7]]) as usize;
            if payload_length > self.max_frame_size {
                let max_sz = self.max_frame_size;
                self.compact_if_needed();
                return Err(CoreError::framing(format!(
                    "Frame length {payload_length} exceeds limit of {max_sz}"
                ))
                .into());
            }

            let total_frame_len = HEADER_SIZE + payload_length;
            if self.buffer.len().saturating_sub(self.read_pos) < total_frame_len {
                break;
            }

            let start = self.read_pos + HEADER_SIZE;
            let end = self.read_pos + total_frame_len;
            frames.push(PyBytes::new(py, &self.buffer[start..end]));
            self.read_pos = end;
        }

        self.compact_if_needed();
        Ok(frames)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_encode_and_magic_header() {
        let f = encode_frame_vec(b"hello", MAX_FRAME_SIZE).unwrap();
        assert_eq!(&f[0..4], b"BC\x01\x00");
        assert_eq!(&f[4..8], &[0, 0, 0, 5]);
        assert_eq!(&f[8..], b"hello");
    }
}
