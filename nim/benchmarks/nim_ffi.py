"""Isolated ctypes wrapper for Nim prototype dynamic library."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

_DLL_NAME = "bitchat_nim.dll" if os.name == "nt" else "libbitchat_nim.so"
_DLL_PATH = Path(__file__).resolve().parent.parent / "bin" / _DLL_NAME

_lib: ctypes.CDLL | None = None

if _DLL_PATH.exists():
    try:
        _lib = ctypes.CDLL(str(_DLL_PATH))
    except Exception:
        _lib = None


def is_nim_available() -> bool:
    """Return True if the native Nim library was located and loaded."""
    return _lib is not None


if _lib is not None:
    # 1. bitchat_get_optimal_block_size
    _lib.bitchat_get_optimal_block_size.argtypes = [ctypes.c_size_t]
    _lib.bitchat_get_optimal_block_size.restype = ctypes.c_size_t

    # 2. bitchat_pad_packet
    _lib.bitchat_pad_packet.argtypes = [
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _lib.bitchat_pad_packet.restype = ctypes.c_int32

    # 3. bitchat_unpad_packet
    _lib.bitchat_unpad_packet.argtypes = [
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _lib.bitchat_unpad_packet.restype = ctypes.c_int32

    # 4. bitchat_encode_packet
    _lib.bitchat_encode_packet.argtypes = [
        ctypes.c_uint8,  # version
        ctypes.c_uint8,  # msgType
        ctypes.c_uint8,  # ttl
        ctypes.c_uint64,  # timestamp
        ctypes.c_uint8,  # flags
        ctypes.c_char_p,  # senderId
        ctypes.c_char_p,  # recipientId
        ctypes.c_char_p,  # payload
        ctypes.c_size_t,  # payloadLen
        ctypes.c_char_p,  # signature
        ctypes.c_uint8,  # addPadding
        ctypes.c_char_p,  # outBuf
        ctypes.c_size_t,  # outCap
        ctypes.POINTER(ctypes.c_size_t),  # outLen
    ]
    _lib.bitchat_encode_packet.restype = ctypes.c_int32

    # 5. bitchat_decode_packet
    _lib.bitchat_decode_packet.argtypes = [
        ctypes.c_char_p,  # inData
        ctypes.c_size_t,  # inLen
        ctypes.POINTER(ctypes.c_uint8),  # outVersion
        ctypes.POINTER(ctypes.c_uint8),  # outMsgType
        ctypes.POINTER(ctypes.c_uint8),  # outTtl
        ctypes.POINTER(ctypes.c_uint64),  # outTimestamp
        ctypes.POINTER(ctypes.c_uint8),  # outFlags
        ctypes.c_char_p,  # outSenderId
        ctypes.c_char_p,  # outRecipientId
        ctypes.c_char_p,  # outPayload
        ctypes.c_size_t,  # payloadCap
        ctypes.POINTER(ctypes.c_size_t),  # outPayloadLen
        ctypes.c_char_p,  # outSig
    ]
    _lib.bitchat_decode_packet.restype = ctypes.c_int32

    # 6. bitchat_create_fragment
    _lib.bitchat_create_fragment.argtypes = [
        ctypes.c_char_p,  # fragId
        ctypes.c_uint16,  # index
        ctypes.c_uint16,  # total
        ctypes.c_uint8,  # origType
        ctypes.c_char_p,  # chunkData
        ctypes.c_size_t,  # chunkLen
        ctypes.c_char_p,  # outBuf
        ctypes.c_size_t,  # outCap
        ctypes.POINTER(ctypes.c_size_t),  # outLen
    ]
    _lib.bitchat_create_fragment.restype = ctypes.c_int32

    # 7. bitchat_parse_fragment
    _lib.bitchat_parse_fragment.argtypes = [
        ctypes.c_char_p,  # payload
        ctypes.c_size_t,  # payloadLen
        ctypes.c_char_p,  # outFragId
        ctypes.POINTER(ctypes.c_uint16),  # outIndex
        ctypes.POINTER(ctypes.c_uint16),  # outTotal
        ctypes.POINTER(ctypes.c_uint8),  # outOrigType
        ctypes.c_char_p,  # outChunk
        ctypes.c_size_t,  # chunkCap
        ctypes.POINTER(ctypes.c_size_t),  # outChunkLen
    ]
    _lib.bitchat_parse_fragment.restype = ctypes.c_int32

    # 8. Reassembler handles
    _lib.bitchat_reassembler_new.argtypes = [
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.c_int32,
    ]
    _lib.bitchat_reassembler_new.restype = ctypes.c_void_p

    _lib.bitchat_reassembler_free.argtypes = [ctypes.c_void_p]
    _lib.bitchat_reassembler_free.restype = None

    _lib.bitchat_reassembler_clear.argtypes = [ctypes.c_void_p]
    _lib.bitchat_reassembler_clear.restype = None

    _lib.bitchat_reassembler_active_count.argtypes = [ctypes.c_void_p]
    _lib.bitchat_reassembler_active_count.restype = ctypes.c_int32

    _lib.bitchat_reassembler_add_fragment.argtypes = [
        ctypes.c_void_p,  # handle
        ctypes.c_char_p,  # senderId
        ctypes.c_char_p,  # payload
        ctypes.c_size_t,  # payloadLen
        ctypes.c_char_p,  # outBuf
        ctypes.c_size_t,  # outCap
        ctypes.POINTER(ctypes.c_size_t),  # outLen
        ctypes.POINTER(ctypes.c_uint8),  # outIsComplete
    ]
    _lib.bitchat_reassembler_add_fragment.restype = ctypes.c_int32


def nim_pad_packet(data: bytes) -> bytes:
    if _lib is None:
        raise RuntimeError("Nim library not loaded")
    target_cap = _lib.bitchat_get_optimal_block_size(len(data))
    out_cap = max(target_cap + 256, 4096)
    out_buf = ctypes.create_string_buffer(out_cap)
    out_len = ctypes.c_size_t(0)
    status = _lib.bitchat_pad_packet(
        data, len(data), out_buf, out_cap, ctypes.byref(out_len)
    )
    if status != 0:
        raise RuntimeError(f"bitchat_pad_packet failed with code {status}")
    return out_buf.raw[: out_len.value]


def nim_unpad_packet(data: bytes) -> bytes:
    if _lib is None:
        raise RuntimeError("Nim library not loaded")
    out_buf = ctypes.create_string_buffer(len(data))
    out_len = ctypes.c_size_t(0)
    status = _lib.bitchat_unpad_packet(
        data, len(data), out_buf, len(data), ctypes.byref(out_len)
    )
    if status != 0:
        raise RuntimeError(f"bitchat_unpad_packet failed with code {status}")
    return out_buf.raw[: out_len.value]


def nim_encode_packet(
    version: int,
    msg_type: int,
    ttl: int,
    timestamp: int,
    flags: int,
    sender_id: bytes,
    recipient_id: bytes | None,
    payload: bytes,
    signature: bytes | None,
    add_padding: bool = True,
) -> bytes:
    if _lib is None:
        raise RuntimeError("Nim library not loaded")
    out_cap = 4096
    out_buf = ctypes.create_string_buffer(out_cap)
    out_len = ctypes.c_size_t(0)
    status = _lib.bitchat_encode_packet(
        version,
        msg_type,
        ttl,
        timestamp,
        flags,
        sender_id,
        recipient_id if recipient_id else None,
        payload,
        len(payload),
        signature if signature else None,
        1 if add_padding else 0,
        out_buf,
        out_cap,
        ctypes.byref(out_len),
    )
    if status != 0:
        raise RuntimeError(f"bitchat_encode_packet failed with code {status}")
    return out_buf.raw[: out_len.value]


def nim_decode_packet(data: bytes) -> dict:
    if _lib is None:
        raise RuntimeError("Nim library not loaded")
    version = ctypes.c_uint8(0)
    msg_type = ctypes.c_uint8(0)
    ttl = ctypes.c_uint8(0)
    timestamp = ctypes.c_uint64(0)
    flags = ctypes.c_uint8(0)
    sender_id = ctypes.create_string_buffer(8)
    recipient_id = ctypes.create_string_buffer(8)
    payload_cap = 4096
    payload_buf = ctypes.create_string_buffer(payload_cap)
    payload_len = ctypes.c_size_t(0)
    sig_buf = ctypes.create_string_buffer(64)

    status = _lib.bitchat_decode_packet(
        data,
        len(data),
        ctypes.byref(version),
        ctypes.byref(msg_type),
        ctypes.byref(ttl),
        ctypes.byref(timestamp),
        ctypes.byref(flags),
        sender_id,
        recipient_id,
        payload_buf,
        payload_cap,
        ctypes.byref(payload_len),
        sig_buf,
    )
    if status != 0:
        raise ValueError(f"bitchat_decode_packet failed with code {status}")

    has_recipient = (flags.value & 0x01) != 0
    has_sig = (flags.value & 0x02) != 0

    return {
        "version": version.value,
        "msg_type": msg_type.value,
        "ttl": ttl.value,
        "timestamp": timestamp.value,
        "flags": flags.value,
        "sender_id": sender_id.raw[:8],
        "recipient_id": recipient_id.raw[:8] if has_recipient else None,
        "payload": payload_buf.raw[: payload_len.value],
        "signature": sig_buf.raw[:64] if has_sig else None,
    }


def nim_create_fragment(
    frag_id: bytes,
    index: int,
    total: int,
    orig_type: int,
    chunk_data: bytes,
) -> bytes:
    if _lib is None:
        raise RuntimeError("Nim library not loaded")
    out_cap = 13 + len(chunk_data) + 64
    out_buf = ctypes.create_string_buffer(out_cap)
    out_len = ctypes.c_size_t(0)
    status = _lib.bitchat_create_fragment(
        frag_id,
        index,
        total,
        orig_type,
        chunk_data,
        len(chunk_data),
        out_buf,
        out_cap,
        ctypes.byref(out_len),
    )
    if status != 0:
        raise RuntimeError(f"bitchat_create_fragment failed with code {status}")
    return out_buf.raw[: out_len.value]


def nim_parse_fragment(payload: bytes) -> tuple[bytes, int, int, int, bytes]:
    if _lib is None:
        raise RuntimeError("Nim library not loaded")
    out_fid = ctypes.create_string_buffer(8)
    out_idx = ctypes.c_uint16(0)
    out_tot = ctypes.c_uint16(0)
    out_type = ctypes.c_uint8(0)
    chunk_cap = max(len(payload), 1024)
    out_chunk = ctypes.create_string_buffer(chunk_cap)
    out_chunk_len = ctypes.c_size_t(0)

    status = _lib.bitchat_parse_fragment(
        payload,
        len(payload),
        out_fid,
        ctypes.byref(out_idx),
        ctypes.byref(out_tot),
        ctypes.byref(out_type),
        out_chunk,
        chunk_cap,
        ctypes.byref(out_chunk_len),
    )
    if status != 0:
        raise ValueError(f"bitchat_parse_fragment failed with code {status}")
    return (
        out_fid.raw[:8],
        out_idx.value,
        out_tot.value,
        out_type.value,
        out_chunk.raw[: out_chunk_len.value],
    )


class NimReassembler:
    """Python wrapper for Nim's FragmentReassembler handle."""

    def __init__(
        self,
        max_assemblies: int = 100,
        max_fragments: int = 1000,
        max_bytes: int = 150_000,
    ) -> None:
        if _lib is None:
            raise RuntimeError("Nim library not loaded")
        self._handle = _lib.bitchat_reassembler_new(
            max_assemblies, max_fragments, max_bytes
        )
        if not self._handle:
            raise MemoryError("Failed to allocate Nim FragmentReassembler")

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        if self._handle and _lib is not None:
            _lib.bitchat_reassembler_free(self._handle)
            self._handle = None

    def clear(self) -> None:
        if self._handle and _lib is not None:
            _lib.bitchat_reassembler_clear(self._handle)

    @property
    def active_count(self) -> int:
        if self._handle and _lib is not None:
            return _lib.bitchat_reassembler_active_count(self._handle)
        return 0

    def add_fragment(
        self, sender_id: bytes, payload: bytes, max_reassembled_cap: int = 200_000
    ) -> bytes | None:
        if not self._handle or _lib is None:
            raise RuntimeError("Reassembler is closed")
        out_buf = ctypes.create_string_buffer(max_reassembled_cap)
        out_len = ctypes.c_size_t(0)
        out_complete = ctypes.c_uint8(0)

        status = _lib.bitchat_reassembler_add_fragment(
            self._handle,
            sender_id,
            payload,
            len(payload),
            out_buf,
            max_reassembled_cap,
            ctypes.byref(out_len),
            ctypes.byref(out_complete),
        )
        if status != 0:
            raise ValueError(
                f"bitchat_reassembler_add_fragment failed with code {status}"
            )

        if out_complete.value != 0:
            return out_buf.raw[: out_len.value]
        return None
