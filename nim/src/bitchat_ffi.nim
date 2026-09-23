import bitchat_types
import bitchat_padding
import bitchat_packet
import bitchat_fragment
import bitchat_reassembly

proc bitchat_get_optimal_block_size*(unpaddedSize: csize_t): csize_t {.cdecl, exportc, dynlib.} =
  result = csize_t(getOptimalBlockSize(int(unpaddedSize)))

proc bitchat_pad_packet*(
    inData: ptr uint8,
    inLen: csize_t,
    outBuf: ptr uint8,
    outCap: csize_t,
    outLen: ptr csize_t,
): int32 {.cdecl, exportc, dynlib.} =
  if outBuf == nil or outLen == nil:
    return ErrInvalidInput
  if inLen > 0 and inData == nil:
    return ErrInvalidInput

  let targetSize = getOptimalBlockSize(int(inLen))
  if outCap < csize_t(targetSize):
    return ErrBufferTooSmall

  if inLen == 0:
    let emptySeq: seq[uint8] = @[]
    let padded = padPacketData(emptySeq, targetSize)
    if padded.len > 0:
      copyMem(outBuf, unsafeAddr padded[0], padded.len)
    outLen[] = csize_t(padded.len)
    return BitchatOk

  let inArr = cast[ptr UncheckedArray[uint8]](inData)
  let padded = padPacketData(toOpenArray(inArr, 0, int(inLen) - 1), targetSize)
  copyMem(outBuf, unsafeAddr padded[0], padded.len)
  outLen[] = csize_t(padded.len)
  return BitchatOk

proc bitchat_unpad_packet*(
    inData: ptr uint8,
    inLen: csize_t,
    outBuf: ptr uint8,
    outCap: csize_t,
    outLen: ptr csize_t,
): int32 {.cdecl, exportc, dynlib.} =
  if inData == nil or outBuf == nil or outLen == nil:
    return ErrInvalidInput

  if inLen == 0:
    outLen[] = 0
    return BitchatOk

  let inArr = cast[ptr UncheckedArray[uint8]](inData)
  let unpadded = unpadPacketData(toOpenArray(inArr, 0, int(inLen) - 1))

  if outCap < csize_t(unpadded.len):
    return ErrBufferTooSmall

  if unpadded.len > 0:
    copyMem(outBuf, unsafeAddr unpadded[0], unpadded.len)
  outLen[] = csize_t(unpadded.len)
  return BitchatOk

proc bitchat_encode_packet*(
    version: uint8,
    msgType: uint8,
    ttl: uint8,
    timestamp: uint64,
    flags: uint8,
    senderId: ptr uint8,
    recipientId: ptr uint8,
    payload: ptr uint8,
    payloadLen: csize_t,
    signature: ptr uint8,
    addPadding: uint8,
    outBuf: ptr uint8,
    outCap: csize_t,
    outLen: ptr csize_t,
): int32 {.cdecl, exportc, dynlib.} =
  if senderId == nil or outBuf == nil or outLen == nil:
    return ErrInvalidInput
  if payloadLen > 0 and payload == nil:
    return ErrInvalidInput

  let hasRecip = (flags and FlagHasRecipient) != 0
  if hasRecip and recipientId == nil:
    return ErrInvalidInput

  let hasSig = (flags and FlagHasSignature) != 0
  if hasSig and signature == nil:
    return ErrInvalidInput

  let encoded = encodePacketRaw(
    version, msgType, ttl, timestamp, flags,
    senderId, recipientId, payload, int(payloadLen), signature,
    addPadding = (addPadding != 0)
  )

  if outCap < csize_t(encoded.len):
    return ErrBufferTooSmall

  copyMem(outBuf, unsafeAddr encoded[0], encoded.len)
  outLen[] = csize_t(encoded.len)
  return BitchatOk

proc bitchat_decode_packet*(
    inData: ptr uint8,
    inLen: csize_t,
    outVersion: ptr uint8,
    outMsgType: ptr uint8,
    outTtl: ptr uint8,
    outTimestamp: ptr uint64,
    outFlags: ptr uint8,
    outSenderId: ptr uint8,
    outRecipientId: ptr uint8,
    outPayload: ptr uint8,
    payloadCap: csize_t,
    outPayloadLen: ptr csize_t,
    outSig: ptr uint8,
): int32 {.cdecl, exportc, dynlib.} =
  if inData == nil or outSenderId == nil:
    return ErrInvalidInput

  var hdr: RawPacketHeader
  var sId: array[8, uint8]
  var rId: array[8, uint8]
  var pOff: int
  var pLen: int
  var sOff: int

  let status = decodePacketRaw(inData, int(inLen), hdr, sId, rId, pOff, pLen, sOff)
  if status != BitchatOk:
    return status

  if outVersion != nil: outVersion[] = hdr.version
  if outMsgType != nil: outMsgType[] = hdr.msgType
  if outTtl != nil: outTtl[] = hdr.ttl
  if outTimestamp != nil: outTimestamp[] = hdr.timestamp
  if outFlags != nil: outFlags[] = hdr.flags

  copyMem(outSenderId, addr sId[0], SenderIdSize)

  if (hdr.flags and FlagHasRecipient) != 0 and outRecipientId != nil:
    copyMem(outRecipientId, addr rId[0], RecipientIdSize)

  if outPayloadLen != nil:
    outPayloadLen[] = csize_t(pLen)

  if pLen > 0:
    if outPayload != nil:
      if payloadCap < csize_t(pLen):
        return ErrBufferTooSmall
      let inArr = cast[ptr UncheckedArray[uint8]](inData)
      copyMem(outPayload, addr inArr[pOff], pLen)

  if sOff >= 0 and outSig != nil:
    let inArr = cast[ptr UncheckedArray[uint8]](inData)
    copyMem(outSig, addr inArr[sOff], SignatureSize)

  return BitchatOk

proc bitchat_create_fragment*(
    fragId: ptr uint8,
    index: uint16,
    total: uint16,
    origType: uint8,
    chunkData: ptr uint8,
    chunkLen: csize_t,
    outBuf: ptr uint8,
    outCap: csize_t,
    outLen: ptr csize_t,
): int32 {.cdecl, exportc, dynlib.} =
  if fragId == nil or outBuf == nil or outLen == nil:
    return ErrInvalidInput
  if chunkLen > 0 and chunkData == nil:
    return ErrInvalidInput

  let needed = FragmentHeaderSize + int(chunkLen)
  if outCap < csize_t(needed):
    return ErrBufferTooSmall

  let payload = createFragmentPayload(fragId, index, total, origType, chunkData, int(chunkLen))
  copyMem(outBuf, unsafeAddr payload[0], payload.len)
  outLen[] = csize_t(payload.len)
  return BitchatOk

proc bitchat_parse_fragment*(
    payload: ptr uint8,
    payloadLen: csize_t,
    outFragId: ptr uint8,
    outIndex: ptr uint16,
    outTotal: ptr uint16,
    outOrigType: ptr uint8,
    outChunk: ptr uint8,
    chunkCap: csize_t,
    outChunkLen: ptr csize_t,
): int32 {.cdecl, exportc, dynlib.} =
  if payload == nil or outFragId == nil or outIndex == nil or outTotal == nil or outOrigType == nil or outChunkLen == nil:
    return ErrInvalidInput

  var fid: array[8, uint8]
  var idx: uint16
  var tot: uint16
  var ot: uint8
  var dOff: int
  var dLen: int

  let status = parseFragmentPayload(payload, int(payloadLen), fid, idx, tot, ot, dOff, dLen)
  if status != BitchatOk:
    return status

  copyMem(outFragId, addr fid[0], FragmentIdSize)
  outIndex[] = idx
  outTotal[] = tot
  outOrigType[] = ot
  outChunkLen[] = csize_t(dLen)

  if dLen > 0 and outChunk != nil:
    if chunkCap < csize_t(dLen):
      return ErrBufferTooSmall
    let pArr = cast[ptr UncheckedArray[uint8]](payload)
    copyMem(outChunk, addr pArr[dOff], dLen)

  return BitchatOk

proc bitchat_reassembler_new*(
    maxAssemblies: int32,
    maxFragments: int32,
    maxBytes: int32,
): pointer {.cdecl, exportc, dynlib.} =
  let ma = if maxAssemblies > 0: int(maxAssemblies) else: MaxActiveAssemblies
  let mf = if maxFragments > 0: int(maxFragments) else: MaxFragmentsPerAssembly
  let mb = if maxBytes > 0: int(maxBytes) else: MaxReassembledBytes
  let r = newNimFragmentReassembler(ma, mf, mb)
  GC_ref(r)
  result = cast[pointer](r)

proc bitchat_reassembler_free*(handle: pointer) {.cdecl, exportc, dynlib.} =
  if handle != nil:
    let r = cast[NimFragmentReassembler](handle)
    GC_unref(r)

proc bitchat_reassembler_clear*(handle: pointer) {.cdecl, exportc, dynlib.} =
  if handle != nil:
    let r = cast[NimFragmentReassembler](handle)
    r.clear()

proc bitchat_reassembler_active_count*(handle: pointer): int32 {.cdecl, exportc, dynlib.} =
  if handle != nil:
    let r = cast[NimFragmentReassembler](handle)
    return int32(r.activeCount())
  return 0

proc bitchat_reassembler_add_fragment*(
    handle: pointer,
    senderId: ptr uint8,
    payload: ptr uint8,
    payloadLen: csize_t,
    outBuf: ptr uint8,
    outCap: csize_t,
    outLen: ptr csize_t,
    outIsComplete: ptr uint8,
): int32 {.cdecl, exportc, dynlib.} =
  if handle == nil or senderId == nil or payload == nil or outIsComplete == nil:
    return ErrInvalidInput

  let r = cast[NimFragmentReassembler](handle)
  var reassembled: seq[uint8]
  var complete: bool = false

  let status = r.addFragment(senderId, payload, int(payloadLen), reassembled, complete)
  if status != BitchatOk:
    outIsComplete[] = 0
    return status

  if complete:
    outIsComplete[] = 1
    if outLen != nil:
      outLen[] = csize_t(reassembled.len)
    if reassembled.len > 0:
      if outBuf == nil or outCap < csize_t(reassembled.len):
        return ErrBufferTooSmall
      copyMem(outBuf, unsafeAddr reassembled[0], reassembled.len)
  else:
    outIsComplete[] = 0
    if outLen != nil:
      outLen[] = 0

  return BitchatOk
