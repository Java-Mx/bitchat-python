import bitchat_types
import bitchat_padding

proc writeBigEndian64*(buf: var openArray[uint8], offset: int, val: uint64) =
  buf[offset] = uint8((val shr 56) and 0xFF)
  buf[offset + 1] = uint8((val shr 48) and 0xFF)
  buf[offset + 2] = uint8((val shr 40) and 0xFF)
  buf[offset + 3] = uint8((val shr 32) and 0xFF)
  buf[offset + 4] = uint8((val shr 24) and 0xFF)
  buf[offset + 5] = uint8((val shr 16) and 0xFF)
  buf[offset + 6] = uint8((val shr 8) and 0xFF)
  buf[offset + 7] = uint8(val and 0xFF)

proc readBigEndian64*(buf: openArray[uint8], offset: int): uint64 =
  result = (uint64(buf[offset]) shl 56) or
           (uint64(buf[offset + 1]) shl 48) or
           (uint64(buf[offset + 2]) shl 40) or
           (uint64(buf[offset + 3]) shl 32) or
           (uint64(buf[offset + 4]) shl 24) or
           (uint64(buf[offset + 5]) shl 16) or
           (uint64(buf[offset + 6]) shl 8) or
           uint64(buf[offset + 7])

proc writeBigEndian16*(buf: var openArray[uint8], offset: int, val: uint16) =
  buf[offset] = uint8((val shr 8) and 0xFF)
  buf[offset + 1] = uint8(val and 0xFF)

proc readBigEndian16*(buf: openArray[uint8], offset: int): uint16 =
  result = (uint16(buf[offset]) shl 8) or uint16(buf[offset + 1])

type
  RawPacketHeader* = object
    version*: uint8
    msgType*: uint8
    ttl*: uint8
    timestamp*: uint64
    flags*: uint8
    payloadLen*: uint16

proc encodePacketRaw*(
    version: uint8,
    msgType: uint8,
    ttl: uint8,
    timestamp: uint64,
    flags: uint8,
    senderId: ptr uint8,
    recipientId: ptr uint8,
    payload: ptr uint8,
    payloadLen: int,
    signature: ptr uint8,
    addPadding: bool = true,
): seq[uint8] =
  let hasRecipient = (flags and FlagHasRecipient) != 0
  let hasSig = (flags and FlagHasSignature) != 0

  let unpaddedSize = FixedHeaderSize + SenderIdSize +
    (if hasRecipient: RecipientIdSize else: 0) +
    payloadLen +
    (if hasSig: SignatureSize else: 0)

  var unpadded = newSeq[uint8](unpaddedSize)

  unpadded[0] = version
  unpadded[1] = msgType
  unpadded[2] = ttl
  writeBigEndian64(unpadded, 3, timestamp)
  unpadded[11] = flags
  writeBigEndian16(unpadded, 12, uint16(payloadLen))

  var offset = FixedHeaderSize
  copyMem(addr unpadded[offset], senderId, SenderIdSize)
  offset += SenderIdSize

  if hasRecipient and recipientId != nil:
    copyMem(addr unpadded[offset], recipientId, RecipientIdSize)
    offset += RecipientIdSize

  if payloadLen > 0 and payload != nil:
    copyMem(addr unpadded[offset], payload, payloadLen)
    offset += payloadLen

  if hasSig and signature != nil:
    copyMem(addr unpadded[offset], signature, SignatureSize)
    offset += SignatureSize

  if addPadding:
    result = padPacketData(unpadded)
  else:
    result = unpadded

proc encodePacketRaw*(
    version: uint8,
    msgType: uint8,
    ttl: uint8,
    timestamp: uint64,
    flags: uint8,
    senderId: openArray[uint8],
    recipientId: openArray[uint8],
    payload: openArray[uint8],
    signature: openArray[uint8],
    addPadding: bool = true,
): seq[uint8] =
  let sPtr = if senderId.len > 0: unsafeAddr senderId[0] else: nil
  let rPtr = if recipientId.len > 0: unsafeAddr recipientId[0] else: nil
  let pPtr = if payload.len > 0: unsafeAddr payload[0] else: nil
  let sigPtr = if signature.len > 0: unsafeAddr signature[0] else: nil
  return encodePacketRaw(
    version, msgType, ttl, timestamp, flags,
    sPtr, rPtr, pPtr, payload.len, sigPtr, addPadding
  )

proc decodePacketRaw*(
    data: ptr uint8,
    dataLen: int,
    header: var RawPacketHeader,
    senderId: var array[8, uint8],
    recipientId: var array[8, uint8],
    payloadOffset: var int,
    payloadLen: var int,
    sigOffset: var int,
): int32 =
  if dataLen < MinimumPacketSize:
    return ErrPacketTooSmall

  let arr = cast[ptr UncheckedArray[uint8]](data)

  header.version = arr[0]
  if header.version != CurrentProtocolVersion:
    return ErrBadVersion

  header.msgType = arr[1]
  if not isValidMessageType(header.msgType):
    return ErrBadMsgType

  header.ttl = arr[2]
  header.timestamp = (uint64(arr[3]) shl 56) or
                     (uint64(arr[4]) shl 48) or
                     (uint64(arr[5]) shl 40) or
                     (uint64(arr[6]) shl 32) or
                     (uint64(arr[7]) shl 24) or
                     (uint64(arr[8]) shl 16) or
                     (uint64(arr[9]) shl 8) or
                     uint64(arr[10])

  header.flags = arr[11]
  header.payloadLen = (uint16(arr[12]) shl 8) or uint16(arr[13])

  let hasRecipient = (header.flags and FlagHasRecipient) != 0
  let hasSig = (header.flags and FlagHasSignature) != 0

  let unpaddedExpected = FixedHeaderSize + SenderIdSize +
    (if hasRecipient: RecipientIdSize else: 0) +
    int(header.payloadLen) +
    (if hasSig: SignatureSize else: 0)

  if dataLen < unpaddedExpected:
    return ErrPacketTooSmall

  if dataLen > unpaddedExpected:
    let paddingNeeded = dataLen - unpaddedExpected
    if paddingNeeded > MaxPaddingSize or paddingNeeded <= 0:
      return ErrCorruptPadding
    if arr[dataLen - 1] != uint8(paddingNeeded):
      return ErrCorruptPadding

  var offset = FixedHeaderSize
  copyMem(addr senderId[0], addr arr[offset], SenderIdSize)
  offset += SenderIdSize

  if hasRecipient:
    copyMem(addr recipientId[0], addr arr[offset], RecipientIdSize)
    offset += RecipientIdSize
  else:
    zeroMem(addr recipientId[0], RecipientIdSize)

  payloadOffset = offset
  payloadLen = int(header.payloadLen)
  offset += payloadLen

  if hasSig:
    sigOffset = offset
  else:
    sigOffset = -1

  return BitchatOk

proc decodePacketRaw*(
    data: openArray[uint8],
    header: var RawPacketHeader,
    senderId: var array[8, uint8],
    recipientId: var array[8, uint8],
    payloadOffset: var int,
    payloadLen: var int,
    sigOffset: var int,
): int32 =
  if data.len == 0:
    return ErrPacketTooSmall
  return decodePacketRaw(
    unsafeAddr data[0], data.len, header, senderId, recipientId,
    payloadOffset, payloadLen, sigOffset
  )
