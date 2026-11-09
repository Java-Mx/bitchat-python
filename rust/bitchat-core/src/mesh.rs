use std::collections::{HashMap, VecDeque};

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use sha2::{Digest, Sha256};

use crate::protocol::hex_encode_lower;

pub fn compute_packet_id_bytes(
    sender_id: &[u8],
    timestamp: u64,
    message_type: u8,
    recipient_id: Option<&[u8]>,
    payload: &[u8],
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(sender_id);
    hasher.update(timestamp.to_be_bytes());
    hasher.update([message_type]);
    if let Some(rcpt) = recipient_id {
        hasher.update(rcpt);
    }
    hasher.update(payload);
    let digest = hasher.finalize();
    hex_encode_lower(&digest[..16])
}

#[pyfunction]
#[pyo3(signature = (sender_id, timestamp, message_type, recipient_id, payload))]
pub fn compute_packet_id_raw(
    sender_id: &[u8],
    timestamp: u64,
    message_type: u8,
    recipient_id: Option<&[u8]>,
    payload: &[u8],
) -> String {
    compute_packet_id_bytes(sender_id, timestamp, message_type, recipient_id, payload)
}

#[pyclass]
pub struct NativePacketDeduplicator {
    max_entries: usize,
    entry_ttl_seconds: f64,
    entries: HashMap<String, (f64, u64)>,
    order: VecDeque<(String, u64)>,
    next_gen: u64,
}

impl NativePacketDeduplicator {
    fn clean_front(&mut self) {
        while let Some((front_key, front_gen)) = self.order.front() {
            match self.entries.get(front_key) {
                Some(&(_, current_gen)) if current_gen == *front_gen => break,
                _ => {
                    self.order.pop_front();
                }
            }
        }
    }

    fn compact_order_if_needed(&mut self) {
        if self.order.len() > self.entries.len().saturating_mul(2).saturating_add(64) {
            let entries = &self.entries;
            self.order.retain(|(k, g)| {
                entries
                    .get(k)
                    .map(|&(_, cur_g)| cur_g == *g)
                    .unwrap_or(false)
            });
        }
    }

    fn evict_oldest(&mut self) {
        self.clean_front();
        if let Some((oldest_key, _)) = self.order.pop_front() {
            self.entries.remove(&oldest_key);
        }
    }
}

#[pymethods]
impl NativePacketDeduplicator {
    #[new]
    #[pyo3(signature = (max_entries=2000, entry_ttl_seconds=300.0))]
    pub fn new(max_entries: isize, entry_ttl_seconds: f64) -> PyResult<Self> {
        if max_entries <= 0 {
            return Err(PyValueError::new_err(
                "max_entries must be greater than zero",
            ));
        }
        if entry_ttl_seconds <= 0.0 {
            return Err(PyValueError::new_err(
                "entry_ttl_seconds must be greater than zero",
            ));
        }
        let cap = max_entries as usize;
        Ok(Self {
            max_entries: cap,
            entry_ttl_seconds,
            entries: HashMap::with_capacity(cap.min(2048)),
            order: VecDeque::with_capacity(cap.min(2048)),
            next_gen: 0,
        })
    }

    #[getter]
    pub fn max_entries(&self) -> usize {
        self.max_entries
    }

    #[getter]
    pub fn entry_ttl_seconds(&self) -> f64 {
        self.entry_ttl_seconds
    }

    pub fn is_id_duplicate(&mut self, packet_id: &str, now: f64) -> bool {
        if let Some(&(recorded_time, _)) = self.entries.get(packet_id) {
            if now - recorded_time > self.entry_ttl_seconds {
                self.entries.remove(packet_id);
                self.compact_order_if_needed();
                return false;
            }
            true
        } else {
            false
        }
    }

    pub fn record_id(&mut self, packet_id: String, now: f64) {
        if !self.entries.contains_key(&packet_id) && self.entries.len() >= self.max_entries {
            self.evict_oldest();
        }
        self.next_gen = self.next_gen.wrapping_add(1);
        let gen = self.next_gen;
        self.entries.insert(packet_id.clone(), (now, gen));
        self.order.push_back((packet_id, gen));
        self.compact_order_if_needed();
    }

    pub fn check_and_record_id(&mut self, packet_id: String, now: f64) -> bool {
        if self.is_id_duplicate(&packet_id, now) {
            return true;
        }
        self.record_id(packet_id, now);
        false
    }

    #[pyo3(signature = (sender_id, timestamp, message_type, recipient_id, payload, now))]
    pub fn check_and_record_raw(
        &mut self,
        sender_id: &[u8],
        timestamp: u64,
        message_type: u8,
        recipient_id: Option<&[u8]>,
        payload: &[u8],
        now: f64,
    ) -> bool {
        let packet_id =
            compute_packet_id_bytes(sender_id, timestamp, message_type, recipient_id, payload);
        self.check_and_record_id(packet_id, now)
    }

    pub fn prune_expired(&mut self, now: f64) -> usize {
        let mut pruned_count = 0usize;
        loop {
            self.clean_front();
            let should_evict = match self.order.front() {
                Some((front_key, _)) => match self.entries.get(front_key) {
                    Some(&(recorded_time, _)) => now - recorded_time > self.entry_ttl_seconds,
                    None => false,
                },
                None => false,
            };
            if should_evict {
                if let Some((key, _)) = self.order.pop_front() {
                    self.entries.remove(&key);
                    pruned_count += 1;
                }
            } else {
                break;
            }
        }
        self.compact_order_if_needed();
        pruned_count
    }

    pub fn clear(&mut self) {
        self.entries.clear();
        self.order.clear();
    }

    pub fn size(&self) -> usize {
        self.entries.len()
    }
}

#[pyclass]
pub struct NativePeerRateLimiter {
    rate_limit_per_peer: usize,
    buckets: HashMap<String, VecDeque<f64>>,
}

#[pymethods]
impl NativePeerRateLimiter {
    #[new]
    #[pyo3(signature = (rate_limit_per_peer=50))]
    pub fn new(rate_limit_per_peer: usize) -> Self {
        Self {
            rate_limit_per_peer,
            buckets: HashMap::new(),
        }
    }

    #[getter]
    pub fn rate_limit_per_peer(&self) -> usize {
        self.rate_limit_per_peer
    }

    #[setter]
    pub fn set_rate_limit_per_peer(&mut self, value: usize) {
        self.rate_limit_per_peer = value;
    }

    pub fn prune(&mut self, max_age: f64, now: f64) -> usize {
        let before = self.buckets.len();
        self.buckets
            .retain(|_, timestamps| match timestamps.back() {
                Some(&latest) => now - latest <= max_age,
                None => false,
            });
        before.saturating_sub(self.buckets.len())
    }

    pub fn is_rate_limited(&mut self, sender_hex: &str, now: f64) -> bool {
        if self.buckets.len() > 1000 {
            self.prune(1.0, now);
        }

        let queue = self
            .buckets
            .entry(sender_hex.to_string())
            .or_insert_with(|| VecDeque::with_capacity(self.rate_limit_per_peer.min(64)));

        while let Some(&oldest) = queue.front() {
            if now - oldest > 1.0 {
                queue.pop_front();
            } else {
                break;
            }
        }

        if queue.len() >= self.rate_limit_per_peer {
            return true;
        }

        queue.push_back(now);
        false
    }

    pub fn peer_count(&self) -> usize {
        self.buckets.len()
    }

    pub fn clear(&mut self) {
        self.buckets.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_packet_id_deterministic() {
        let sender = [0x11u8; 8];
        let rcpt = [0x22u8; 8];
        let payload = b"hello mesh";
        let id1 = compute_packet_id_bytes(&sender, 123456, 0x01, Some(&rcpt), payload);
        let id2 = compute_packet_id_bytes(&sender, 123456, 0x01, Some(&rcpt), payload);
        assert_eq!(id1, id2);
        assert_eq!(id1.len(), 32);
    }

    #[test]
    fn test_deduplicator_lru_and_ttl() {
        let mut dedup = NativePacketDeduplicator::new(2, 10.0).unwrap();
        assert!(!dedup.check_and_record_id("pkt1".to_string(), 100.0));
        assert!(dedup.check_and_record_id("pkt1".to_string(), 105.0));
        assert!(!dedup.check_and_record_id("pkt2".to_string(), 106.0));
        // Refresh pkt1 so pkt2 becomes oldest
        dedup.record_id("pkt1".to_string(), 107.0);
        // Adding pkt3 should evict pkt2
        assert!(!dedup.check_and_record_id("pkt3".to_string(), 108.0));
        assert!(!dedup.is_id_duplicate("pkt2", 108.0));
        assert!(dedup.is_id_duplicate("pkt1", 108.0));
        assert!(dedup.is_id_duplicate("pkt3", 108.0));
        // Expire pkt1 at t=118.0
        assert!(!dedup.is_id_duplicate("pkt1", 118.0));
    }

    #[test]
    fn test_rate_limiter() {
        let mut limiter = NativePeerRateLimiter::new(3);
        assert!(!limiter.is_rate_limited("peer1", 10.0));
        assert!(!limiter.is_rate_limited("peer1", 10.1));
        assert!(!limiter.is_rate_limited("peer1", 10.2));
        assert!(limiter.is_rate_limited("peer1", 10.3));
        assert!(!limiter.is_rate_limited("peer1", 11.1));
    }
}
