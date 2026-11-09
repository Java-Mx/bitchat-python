use pyo3::prelude::*;

pub mod errors;
pub mod fragmentation;
pub mod framing;
pub mod mesh;
pub mod protocol;

#[pyfunction]
fn native_core_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pymodule]
fn _bitchat_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(native_core_version, m)?)?;

    // Protocol functions
    m.add_function(wrap_pyfunction!(protocol::get_optimal_block_size, m)?)?;
    m.add_function(wrap_pyfunction!(protocol::pad_packet_data, m)?)?;
    m.add_function(wrap_pyfunction!(protocol::unpad_packet_data, m)?)?;
    m.add_function(wrap_pyfunction!(protocol::peer_id_to_hex, m)?)?;
    m.add_function(wrap_pyfunction!(protocol::peer_id_from_hex, m)?)?;
    m.add_function(wrap_pyfunction!(protocol::encode_packet_raw, m)?)?;
    m.add_function(wrap_pyfunction!(protocol::decode_packet_raw, m)?)?;

    // Fragmentation and reassembly
    m.add_function(wrap_pyfunction!(fragmentation::should_fragment_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(fragmentation::split_chunks, m)?)?;
    m.add_function(wrap_pyfunction!(fragmentation::create_fragment_payload, m)?)?;
    m.add_function(wrap_pyfunction!(fragmentation::parse_fragment_payload, m)?)?;
    m.add_function(wrap_pyfunction!(
        fragmentation::fragment_encoded_packet_raw,
        m
    )?)?;
    m.add_class::<fragmentation::NativeFragmentReassembler>()?;

    // Network framing
    m.add_function(wrap_pyfunction!(framing::encode_frame_bytes, m)?)?;
    m.add_class::<framing::NativeStreamFramer>()?;

    // Mesh deduplication and rate limiting
    m.add_function(wrap_pyfunction!(mesh::compute_packet_id_raw, m)?)?;
    m.add_class::<mesh::NativePacketDeduplicator>()?;
    m.add_class::<mesh::NativePeerRateLimiter>()?;

    Ok(())
}
