//! Packet fragmentation and stateful LRU fragment reassembly engine.

use std::collections::{HashMap, VecDeque};
use std::time::{SystemTime, UNIX_EPOCH};

use pyo3::prelude::*;
use pyo3::types::PyBytes;
use rand::RngCore;

use crate::errors::CoreError;
use crate::protocol::{PROTOCOL_VERSION, SENDER_ID_SIZE};

pub const FRAGMENTATION_THRESHOLD: usize = 500;
pub const FRAGMENT_CHUNK_SIZE: usize = 150;
pub const FRAGMENT_ID_SIZE: usize = 8;
pub const FRAGMENT_HEADER_SIZE: usize = 13; // >8sHHB
pub const MAX_FRAGMENTS_PER_ASSEMBLY: usize = 1000;
pub const MAX_ACTIVE_ASSEMBLIES: usize = 100;
pub const MAX_REASSEMBLED_BYTES: usize = 150_000;

pub const MSG_FRAGMENT_START: u8 = 0x05;
pub const MSG_FRAGMENT_CONTINUE: u8 = 0x06;
pub const MSG_FRAGMENT_END: u8 = 0x07;

#[inline]
fn now_secs_f64() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

#[inline]
fn now_millis_u64() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

pub fn build_fragment_payload(
    fragment_id: &[u8],
    index: i64,
    total: i64,
    original_message_type: i64,
    chunk_data: &[u8],
) -> Result<Vec<u8>, CoreError> {
    if fragment_id.len() != FRAGMENT_ID_SIZE {
        return Err(CoreError::invalid_fragment(format!(
            "fragment_id must be {FRAGMENT_ID_SIZE} bytes, got {}",
            fragment_id.len()
        )));
    }
    if total <= 0 {
        return Err(CoreError::invalid_fragment(format!(
            "total fragments must be positive, got {total}"
        )));
    }
    if total as usize > MAX_FRAGMENTS_PER_ASSEMBLY {
        return Err(CoreError::fragment_limit(format!(
            "total fragments {total} exceeds limit of {MAX_FRAGMENTS_PER_ASSEMBLY}"
        )));
    }
    if index < 0 || index >= total {
        return Err(CoreError::invalid_fragment(format!(
            "fragment index {index} out of bounds for total {total}"
        )));
    }
    if !(0..=255).contains(&original_message_type) {
        return Err(CoreError::invalid_fragment(format!(
            "original_message_type must be a single byte (0..255), got {original_message_type}"
        )));
    }

    let mut out = Vec::with_capacity(FRAGMENT_HEADER_SIZE + chunk_data.len());
    out.extend_from_slice(fragment_id);
    out.extend_from_slice(&(index as u16).to_be_bytes());
    out.extend_from_slice(&(total as u16).to_be_bytes());
    out.push(original_message_type as u8);
    out.extend_from_slice(chunk_data);
    Ok(out)
}

#[allow(clippy::type_complexity)]
pub fn unpack_fragment_payload(
    payload: &[u8],
) -> Result<([u8; 8], u16, u16, u8, &[u8]), CoreError> {
    if payload.len() < FRAGMENT_HEADER_SIZE {
        return Err(CoreError::fragment_payload(format!(
            "Fragment payload too short: {} bytes (minimum {FRAGMENT_HEADER_SIZE})",
            payload.len()
        )));
    }
    let mut frag_id = [0u8; 8];
    frag_id.copy_from_slice(&payload[0..8]);
    let index = u16::from_be_bytes([payload[8], payload[9]]);
    let total = u16::from_be_bytes([payload[10], payload[11]]);
    let orig_type_raw = payload[12];

    if total == 0 {
        return Err(CoreError::invalid_fragment(format!(
            "Invalid fragment total count: {total}"
        )));
    }
    if (total as usize) > MAX_FRAGMENTS_PER_ASSEMBLY {
        return Err(CoreError::fragment_limit(format!(
            "Fragment total {total} exceeds maximum allowed ({MAX_FRAGMENTS_PER_ASSEMBLY})"
        )));
    }
    if index >= total {
        return Err(CoreError::invalid_fragment(format!(
            "Fragment index {index} >= total {total}"
        )));
    }
    Ok((
        frag_id,
        index,
        total,
        orig_type_raw,
        &payload[FRAGMENT_HEADER_SIZE..],
    ))
}

#[pyfunction]
#[pyo3(signature = (encoded_packet, threshold=FRAGMENTATION_THRESHOLD))]
pub fn should_fragment_bytes(encoded_packet: &[u8], threshold: usize) -> bool {
    encoded_packet.len() > threshold
}

#[pyfunction]
#[pyo3(signature = (data, chunk_size=FRAGMENT_CHUNK_SIZE as i64))]
pub fn split_chunks<'py>(
    py: Python<'py>,
    data: &[u8],
    chunk_size: i64,
) -> PyResult<Vec<Bound<'py, PyBytes>>> {
    if chunk_size <= 0 {
        return Err(CoreError::invalid_fragment("chunk_size must be positive").into());
    }
    if data.is_empty() {
        return Ok(vec![PyBytes::new(py, b"")]);
    }
    let cs = chunk_size as usize;
    let mut out = Vec::with_capacity(data.len().div_ceil(cs));
    for slice in data.chunks(cs) {
        out.push(PyBytes::new(py, slice));
    }
    Ok(out)
}

#[pyfunction]
pub fn create_fragment_payload<'py>(
    py: Python<'py>,
    fragment_id: &[u8],
    index: i64,
    total: i64,
    original_message_type: i64,
    chunk_data: &[u8],
) -> PyResult<Bound<'py, PyBytes>> {
    let raw = build_fragment_payload(fragment_id, index, total, original_message_type, chunk_data)?;
    Ok(PyBytes::new(py, &raw))
}

#[allow(clippy::type_complexity)]
#[pyfunction]
pub fn parse_fragment_payload<'py>(
    py: Python<'py>,
    payload: &[u8],
) -> PyResult<(Bound<'py, PyBytes>, u16, u16, u8, Bound<'py, PyBytes>)> {
    let (frag_id, index, total, orig_type, chunk) = unpack_fragment_payload(payload)?;
    Ok((
        PyBytes::new(py, &frag_id),
        index,
        total,
        orig_type,
        PyBytes::new(py, chunk),
    ))
}

#[allow(clippy::too_many_arguments, clippy::type_complexity)]
#[pyfunction]
#[pyo3(signature = (encoded_packet, sender_id, original_message_type, ttl=7, timestamp=None, chunk_size=FRAGMENT_CHUNK_SIZE as i64, fragment_id=None))]
pub fn fragment_encoded_packet_raw<'py>(
    py: Python<'py>,
    encoded_packet: &[u8],
    sender_id: &[u8],
    original_message_type: i64,
    ttl: i64,
    timestamp: Option<i128>,
    chunk_size: i64,
    fragment_id: Option<&[u8]>,
) -> PyResult<
    Vec<(
        u8,
        u8,
        u8,
        u64,
        u8,
        Bound<'py, PyBytes>,
        Bound<'py, PyBytes>,
    )>,
> {
    if encoded_packet.is_empty() {
        return Err(CoreError::invalid_fragment("encoded_packet must be non-empty bytes").into());
    }
    if sender_id.len() != SENDER_ID_SIZE {
        return Err(CoreError::invalid_fragment(format!(
            "sender_id must be {SENDER_ID_SIZE} bytes"
        ))
        .into());
    }
    if chunk_size <= 0 {
        return Err(CoreError::invalid_fragment("chunk_size must be positive").into());
    }
    if !(0..=255).contains(&ttl) {
        return Err(CoreError::invalid_fragment(format!("Invalid ttl: {ttl}")).into());
    }
    if !(0..=255).contains(&original_message_type) {
        return Err(CoreError::invalid_fragment(format!(
            "Invalid original_message_type: {original_message_type}"
        ))
        .into());
    }

    let mut fid = [0u8; FRAGMENT_ID_SIZE];
    if let Some(given_fid) = fragment_id {
        if given_fid.len() != FRAGMENT_ID_SIZE {
            return Err(CoreError::invalid_fragment(format!(
                "fragment_id must be {FRAGMENT_ID_SIZE} bytes"
            ))
            .into());
        }
        fid.copy_from_slice(given_fid);
    } else {
        rand::thread_rng().fill_bytes(&mut fid);
    }

    let cs = chunk_size as usize;
    let total = encoded_packet.len().div_ceil(cs);
    if total > MAX_FRAGMENTS_PER_ASSEMBLY {
        return Err(CoreError::fragment_limit(format!(
            "Packet requires {total} fragments, exceeding limit of {MAX_FRAGMENTS_PER_ASSEMBLY}"
        ))
        .into());
    }

    let ts: u64 = match timestamp {
        Some(v) if (0..=(u64::MAX as i128)).contains(&v) => v as u64,
        Some(v) => {
            return Err(CoreError::invalid_fragment(format!("Invalid timestamp: {v}")).into())
        }
        None => now_millis_u64(),
    };

    let sender_py = PyBytes::new(py, sender_id);
    let mut results = Vec::with_capacity(total);
    for (idx, chunk) in encoded_packet.chunks(cs).enumerate() {
        let frag_msg_type = if idx == 0 {
            MSG_FRAGMENT_START
        } else if idx == total - 1 {
            MSG_FRAGMENT_END
        } else {
            MSG_FRAGMENT_CONTINUE
        };
        let frag_payload =
            build_fragment_payload(&fid, idx as i64, total as i64, original_message_type, chunk)?;
        results.push((
            PROTOCOL_VERSION,
            frag_msg_type,
            ttl as u8,
            ts,
            0u8,
            sender_py.clone(),
            PyBytes::new(py, &frag_payload),
        ));
    }

    Ok(results)
}

#[derive(Debug, Clone)]
struct AssemblyBuffer {
    total: u16,
    original_message_type: u8,
    chunks: HashMap<u16, Vec<u8>>,
    total_bytes: usize,
    created_at: f64,
}

type AssemblyKey = ([u8; 8], [u8; 8]);

#[pyclass]
pub struct NativeFragmentReassembler {
    max_active_assemblies: usize,
    max_fragments_per_assembly: usize,
    max_reassembled_bytes: usize,
    assemblies: HashMap<AssemblyKey, AssemblyBuffer>,
    lru_order: VecDeque<AssemblyKey>,
}

impl NativeFragmentReassembler {
    fn touch_lru(&mut self, key: &AssemblyKey) {
        if let Some(pos) = self.lru_order.iter().position(|k| k == key) {
            self.lru_order.remove(pos);
        }
        self.lru_order.push_back(*key);
    }

    fn remove_assembly(&mut self, key: &AssemblyKey) {
        self.assemblies.remove(key);
        if let Some(pos) = self.lru_order.iter().position(|k| k == key) {
            self.lru_order.remove(pos);
        }
    }

    fn insert_chunk_internal(
        &mut self,
        sender_id: &[u8],
        fragment_id: [u8; 8],
        index: i64,
        total: i64,
        original_message_type: u8,
        chunk_data: &[u8],
    ) -> Result<Option<Vec<u8>>, CoreError> {
        if sender_id.len() != SENDER_ID_SIZE {
            return Err(CoreError::invalid_fragment(format!(
                "sender_id must be {SENDER_ID_SIZE} bytes"
            )));
        }
        if total <= 0 {
            return Err(CoreError::invalid_fragment(format!(
                "total must be > 0, got {total}"
            )));
        }
        if (total as usize) > self.max_fragments_per_assembly {
            return Err(CoreError::fragment_limit(format!(
                "Total {total} exceeds maximum {}",
                self.max_fragments_per_assembly
            )));
        }
        if index < 0 || index >= total {
            return Err(CoreError::invalid_fragment(format!(
                "index out of bounds: index={index}, total={total}"
            )));
        }

        let mut sender_arr = [0u8; 8];
        sender_arr.copy_from_slice(sender_id);
        let key: AssemblyKey = (sender_arr, fragment_id);

        let total_u16 = total as u16;
        let index_u16 = index as u16;

        if self.assemblies.contains_key(&key) {
            self.touch_lru(&key);
            let state = self.assemblies.get_mut(&key).unwrap();
            if state.total != total_u16 {
                self.remove_assembly(&key);
                return Err(CoreError::invalid_fragment(
                    "Inconsistent total fragment count in assembly",
                ));
            }
            if state.original_message_type != original_message_type {
                self.remove_assembly(&key);
                return Err(CoreError::invalid_fragment(
                    "Inconsistent original_message_type in assembly",
                ));
            }
            if let Some(existing) = state.chunks.get(&index_u16) {
                if existing.as_slice() != chunk_data {
                    self.remove_assembly(&key);
                    return Err(CoreError::invalid_fragment(format!(
                        "Conflicting data for duplicate fragment index {index}"
                    )));
                }
                return Ok(None);
            }
            if state.total_bytes + chunk_data.len() > self.max_reassembled_bytes {
                let new_total = state.total_bytes + chunk_data.len();
                let max_bytes = self.max_reassembled_bytes;
                self.remove_assembly(&key);
                return Err(CoreError::fragment_limit(format!(
                    "Reassembled size ({new_total} bytes) exceeds limit of {max_bytes} bytes"
                )));
            }
            state.chunks.insert(index_u16, chunk_data.to_vec());
            state.total_bytes += chunk_data.len();
        } else {
            if chunk_data.len() > self.max_reassembled_bytes {
                return Err(CoreError::fragment_limit(format!(
                    "Initial fragment size ({} bytes) exceeds limit of {} bytes",
                    chunk_data.len(),
                    self.max_reassembled_bytes
                )));
            }
            while self.assemblies.len() >= self.max_active_assemblies {
                if let Some(oldest) = self.lru_order.pop_front() {
                    self.assemblies.remove(&oldest);
                } else {
                    break;
                }
            }
            let mut chunks = HashMap::with_capacity(total_u16 as usize);
            chunks.insert(index_u16, chunk_data.to_vec());
            let state = AssemblyBuffer {
                total: total_u16,
                original_message_type,
                chunks,
                total_bytes: chunk_data.len(),
                created_at: now_secs_f64(),
            };
            self.assemblies.insert(key, state);
            self.lru_order.push_back(key);
        }

        let is_complete = {
            let state = self.assemblies.get(&key).unwrap();
            state.chunks.len() == state.total as usize
        };

        if is_complete {
            let state = self.assemblies.remove(&key).unwrap();
            if let Some(pos) = self.lru_order.iter().position(|k| *k == key) {
                self.lru_order.remove(pos);
            }
            let mut full = Vec::with_capacity(state.total_bytes);
            for i in 0..state.total {
                if let Some(part) = state.chunks.get(&i) {
                    full.extend_from_slice(part);
                }
            }
            return Ok(Some(full));
        }

        Ok(None)
    }
}

#[pymethods]
impl NativeFragmentReassembler {
    #[new]
    #[pyo3(signature = (max_active_assemblies=MAX_ACTIVE_ASSEMBLIES, max_fragments_per_assembly=MAX_FRAGMENTS_PER_ASSEMBLY, max_reassembled_bytes=MAX_REASSEMBLED_BYTES))]
    pub fn new(
        max_active_assemblies: usize,
        max_fragments_per_assembly: usize,
        max_reassembled_bytes: usize,
    ) -> Self {
        Self {
            max_active_assemblies,
            max_fragments_per_assembly,
            max_reassembled_bytes,
            assemblies: HashMap::new(),
            lru_order: VecDeque::new(),
        }
    }

    #[getter]
    pub fn active_assembly_count(&self) -> usize {
        self.assemblies.len()
    }

    pub fn add_fragment_raw<'py>(
        &mut self,
        py: Python<'py>,
        message_type: u8,
        sender_id: &[u8],
        payload: &[u8],
    ) -> PyResult<Option<Bound<'py, PyBytes>>> {
        if !matches!(
            message_type,
            MSG_FRAGMENT_START | MSG_FRAGMENT_CONTINUE | MSG_FRAGMENT_END
        ) {
            return Err(CoreError::invalid_fragment(format!(
                "Packet message type {message_type:#04x} is not a fragment type"
            ))
            .into());
        }
        let (frag_id, index, total, orig_type, chunk_data) = unpack_fragment_payload(payload)?;
        if (total as usize) > self.max_fragments_per_assembly {
            return Err(CoreError::fragment_limit(format!(
                "Fragment total {total} exceeds limit of {}",
                self.max_fragments_per_assembly
            ))
            .into());
        }
        if index == 0 && message_type != MSG_FRAGMENT_START {
            return Err(CoreError::invalid_fragment(format!(
                "Fragment index 0 must use FragmentStart, got {message_type:#04x}"
            ))
            .into());
        }
        if index > 0 && index == total - 1 && message_type != MSG_FRAGMENT_END {
            return Err(CoreError::invalid_fragment(format!(
                "Final fragment index {index} must use FragmentEnd, got {message_type:#04x}"
            ))
            .into());
        }
        if index > 0 && index < total - 1 && message_type != MSG_FRAGMENT_CONTINUE {
            return Err(CoreError::invalid_fragment(format!(
                "Middle fragment index {index} must use FragmentContinue, got {message_type:#04x}"
            ))
            .into());
        }

        let res = self.insert_chunk_internal(
            sender_id,
            frag_id,
            index as i64,
            total as i64,
            orig_type,
            chunk_data,
        )?;
        Ok(res.map(|b| PyBytes::new(py, &b)))
    }

    pub fn add_fragment<'py>(
        &mut self,
        py: Python<'py>,
        sender_id: &[u8],
        fragment_payload: &[u8],
    ) -> PyResult<Option<Bound<'py, PyBytes>>> {
        let (frag_id, index, total, orig_type, chunk_data) =
            unpack_fragment_payload(fragment_payload)?;
        let res = self.insert_chunk_internal(
            sender_id,
            frag_id,
            index as i64,
            total as i64,
            orig_type,
            chunk_data,
        )?;
        Ok(res.map(|b| PyBytes::new(py, &b)))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn insert_chunk_raw<'py>(
        &mut self,
        py: Python<'py>,
        sender_id: &[u8],
        fragment_id: &[u8],
        index: i64,
        total: i64,
        original_message_type: u8,
        chunk_data: &[u8],
    ) -> PyResult<Option<Bound<'py, PyBytes>>> {
        if fragment_id.len() != FRAGMENT_ID_SIZE {
            return Err(CoreError::invalid_fragment(format!(
                "fragment_id must be {FRAGMENT_ID_SIZE} bytes"
            ))
            .into());
        }
        let mut fid = [0u8; 8];
        fid.copy_from_slice(fragment_id);
        let res = self.insert_chunk_internal(
            sender_id,
            fid,
            index,
            total,
            original_message_type,
            chunk_data,
        )?;
        Ok(res.map(|b| PyBytes::new(py, &b)))
    }

    pub fn get_assembly_stats(
        &self,
        sender_id: &[u8],
        fragment_id: &[u8],
    ) -> Option<(usize, usize, f64, u16, u8)> {
        if sender_id.len() != 8 || fragment_id.len() != 8 {
            return None;
        }
        let mut s = [0u8; 8];
        let mut f = [0u8; 8];
        s.copy_from_slice(sender_id);
        f.copy_from_slice(fragment_id);
        self.assemblies.get(&(s, f)).map(|st| {
            (
                st.chunks.len(),
                st.total_bytes,
                st.created_at,
                st.total,
                st.original_message_type,
            )
        })
    }

    pub fn set_created_at(
        &mut self,
        sender_id: &[u8],
        fragment_id: &[u8],
        created_at: f64,
    ) -> bool {
        if sender_id.len() != 8 || fragment_id.len() != 8 {
            return false;
        }
        let mut s = [0u8; 8];
        let mut f = [0u8; 8];
        s.copy_from_slice(sender_id);
        f.copy_from_slice(fragment_id);
        if let Some(st) = self.assemblies.get_mut(&(s, f)) {
            st.created_at = created_at;
            true
        } else {
            false
        }
    }

    #[pyo3(signature = (max_age_seconds=60.0, now=None))]
    pub fn prune_stale(&mut self, max_age_seconds: f64, now: Option<f64>) -> usize {
        let current = now.unwrap_or_else(now_secs_f64);
        let stale: Vec<AssemblyKey> = self
            .assemblies
            .iter()
            .filter_map(|(k, v)| {
                if (current - v.created_at) > max_age_seconds {
                    Some(*k)
                } else {
                    None
                }
            })
            .collect();
        let count = stale.len();
        for k in stale {
            self.remove_assembly(&k);
        }
        count
    }

    pub fn clear(&mut self) {
        self.assemblies.clear();
        self.lru_order.clear();
    }
}
