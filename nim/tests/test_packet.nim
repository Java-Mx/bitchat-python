import std/unittest
import ../src/bitchat_types
import ../src/bitchat_padding
import ../src/bitchat_packet

suite "Nim Packet & Padding Tests":

  test "Optimal block sizes":
    check getOptimalBlockSize(100) == 256
    check getOptimalBlockSize(240) == 256
    check getOptimalBlockSize(241) == 512
    check getOptimalBlockSize(496) == 512
    check getOptimalBlockSize(497) == 1024
    check getOptimalBlockSize(1008) == 1024
    check getOptimalBlockSize(1009) == 2048
    check getOptimalBlockSize(2032) == 2048
    check getOptimalBlockSize(2033) == 2033

  test "Pad and unpad round-trip":
    let raw = @[1'u8, 2, 3, 4, 5, 6, 7, 8]
    let padded = padPacketData(raw, 256)
    check padded.len == 256
    check padded[255] == uint8(256 - 8)
    let unpadded = unpadPacketData(padded)
    check unpadded == raw

  test "Deterministic padding":
    let raw = @[0xAA'u8, 0xBB, 0xCC]
    let padded = padPacketDataDeterministic(raw, 0x00, 10)
    check padded.len == 10
    check padded[0..2] == @[0xAA'u8, 0xBB, 0xCC]
    for i in 3..8:
      check padded[i] == 0x00
    check padded[9] == 7'u8

  test "Encode and decode raw packet without recipient or signature":
    let sender = [1'u8, 2, 3, 4, 5, 6, 7, 8]
    let emptyRecip: array[8, uint8] = [0'u8, 0, 0, 0, 0, 0, 0, 0]
    let payload = @[0x48'u8, 0x65, 0x6C, 0x6C, 0x6F] # "Hello"
    let emptySig: seq[uint8] = @[]

    let encoded = encodePacketRaw(
      version = 1,
      msgType = uint8(MessageType.Message),
      ttl = 7,
      timestamp = 1700000000000'u64,
      flags = 0,
      senderId = sender,
      recipientId = emptyRecip,
      payload = payload,
      signature = emptySig,
      addPadding = true
    )

    check encoded.len == 256 # padded to 256

    var hdr: RawPacketHeader
    var decSender: array[8, uint8]
    var decRecip: array[8, uint8]
    var pOff, pLen, sOff: int

    let status = decodePacketRaw(encoded, hdr, decSender, decRecip, pOff, pLen, sOff)
    check status == BitchatOk
    check hdr.version == 1
    check hdr.msgType == uint8(MessageType.Message)
    check hdr.ttl == 7
    check hdr.timestamp == 1700000000000'u64
    check hdr.flags == 0
    check hdr.payloadLen == 5
    check decSender == sender
    check pLen == 5
    check encoded[pOff ..< pOff + pLen] == payload
    check sOff == -1

  test "Encode and decode with recipient and signature":
    let sender = [1'u8, 1, 1, 1, 1, 1, 1, 1]
    let recip = [2'u8, 2, 2, 2, 2, 2, 2, 2]
    let payload = @[10'u8, 20, 30]
    var sig = newSeq[uint8](64)
    for i in 0..<64: sig[i] = uint8(i)

    let flags = FlagHasRecipient or FlagHasSignature

    let encoded = encodePacketRaw(
      version = 1,
      msgType = uint8(MessageType.Message),
      ttl = 5,
      timestamp = 123456789'u64,
      flags = flags,
      senderId = sender,
      recipientId = recip,
      payload = payload,
      signature = sig,
      addPadding = true
    )

    var hdr: RawPacketHeader
    var decSender: array[8, uint8]
    var decRecip: array[8, uint8]
    var pOff, pLen, sOff: int

    let status = decodePacketRaw(encoded, hdr, decSender, decRecip, pOff, pLen, sOff)
    check status == BitchatOk
    check hdr.version == 1
    check decSender == sender
    check decRecip == recip
    check pLen == 3
    check encoded[pOff ..< pOff + pLen] == payload
    check sOff >= 0
    check encoded[sOff ..< sOff + 64] == sig

  test "Reject invalid version":
    var bad = newSeq[uint8](30)
    bad[0] = 99 # bad version
    bad[1] = uint8(MessageType.Message)
    var hdr: RawPacketHeader
    var sId, rId: array[8, uint8]
    var pOff, pLen, sOff: int
    check decodePacketRaw(bad, hdr, sId, rId, pOff, pLen, sOff) == ErrBadVersion

  test "Reject invalid message type":
    var bad = newSeq[uint8](30)
    bad[0] = 1
    bad[1] = 0xFF # unknown msg type
    var hdr: RawPacketHeader
    var sId, rId: array[8, uint8]
    var pOff, pLen, sOff: int
    check decodePacketRaw(bad, hdr, sId, rId, pOff, pLen, sOff) == ErrBadMsgType

  test "Reject corrupted padding delimiter":
    let sender = [1'u8, 2, 3, 4, 5, 6, 7, 8]
    let emptyRecip: array[8, uint8] = [0'u8, 0, 0, 0, 0, 0, 0, 0]
    let payload = @[1'u8, 2, 3]
    var encoded = encodePacketRaw(
      1, uint8(MessageType.Message), 7, 1000'u64, 0,
      sender, emptyRecip, payload, @[], addPadding = true
    )
    # Corrupt last byte (padding delimiter)
    encoded[^1] = encoded[^1] + 5
    var hdr: RawPacketHeader
    var sId, rId: array[8, uint8]
    var pOff, pLen, sOff: int
    check decodePacketRaw(encoded, hdr, sId, rId, pOff, pLen, sOff) == ErrCorruptPadding
