import bitchat_types

proc shouldFragment*(dataLen: int): bool =
  result = dataLen > FragmentationThreshold

proc splitChunks*(data: openArray[uint8], chunkSize: int = FragmentChunkSize): seq[seq[uint8]] =
  if data.len == 0:
    return @[]
  let sz = if chunkSize >= 1: chunkSize else: FragmentChunkSize
  var i = 0
  while i < data.len:
    let endIdx = min(i + sz, data.len)
    var chunk = newSeq[uint8](endIdx - i)
    copyMem(addr chunk[0], unsafeAddr data[i], endIdx - i)
    result.add(chunk)
    i += sz

proc createFragmentPayload*(
    fragId: ptr uint8,
    index: uint16,
    total: uint16,
    origType: uint8,
    chunkData: ptr uint8,
    chunkLen: int,
): seq[uint8] =
  let totalLen = FragmentHeaderSize + chunkLen
  result = newSeq[uint8](totalLen)
  copyMem(addr result[0], fragId, FragmentIdSize)
  result[8] = uint8((index shr 8) and 0xFF)
  result[9] = uint8(index and 0xFF)
  result[10] = uint8((total shr 8) and 0xFF)
  result[11] = uint8(total and 0xFF)
  result[12] = origType
  if chunkLen > 0 and chunkData != nil:
    copyMem(addr result[FragmentHeaderSize], chunkData, chunkLen)

proc createFragmentPayload*(
    fragId: openArray[uint8],
    index: uint16,
    total: uint16,
    origType: uint8,
    chunkData: openArray[uint8],
): seq[uint8] =
  let fPtr = if fragId.len > 0: unsafeAddr fragId[0] else: nil
  let cPtr = if chunkData.len > 0: unsafeAddr chunkData[0] else: nil
  return createFragmentPayload(fPtr, index, total, origType, cPtr, chunkData.len)

proc parseFragmentPayload*(
    payload: ptr uint8,
    payloadLen: int,
    fragmentId: var array[8, uint8],
    index: var uint16,
    total: var uint16,
    originalType: var uint8,
    dataOffset: var int,
    dataLen: var int,
): int32 =
  if payloadLen < FragmentHeaderSize or payload == nil:
    return ErrPacketTooSmall

  let arr = cast[ptr UncheckedArray[uint8]](payload)
  copyMem(addr fragmentId[0], addr arr[0], FragmentIdSize)
  index = (uint16(arr[8]) shl 8) or uint16(arr[9])
  total = (uint16(arr[10]) shl 8) or uint16(arr[11])
  originalType = arr[12]

  if total == 0 or total > uint16(MaxFragmentsPerAssembly):
    return ErrFragmentLimit

  if index >= total:
    return ErrInvalidInput

  dataOffset = FragmentHeaderSize
  dataLen = payloadLen - FragmentHeaderSize

  return BitchatOk

proc parseFragmentPayload*(
    payload: openArray[uint8],
    fragmentId: var array[8, uint8],
    index: var uint16,
    total: var uint16,
    originalType: var uint8,
    dataOffset: var int,
    dataLen: var int,
): int32 =
  if payload.len == 0:
    return ErrPacketTooSmall
  return parseFragmentPayload(
    unsafeAddr payload[0], payload.len, fragmentId, index, total,
    originalType, dataOffset, dataLen
  )
