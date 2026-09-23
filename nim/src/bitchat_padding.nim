import std/sysrand
import bitchat_types

proc getOptimalBlockSize*(unpaddedSize: int): int =
  let totalSize = unpaddedSize + PaddingOverheadEstimate
  for bs in BlockSizes:
    if totalSize <= bs:
      return bs
  return unpaddedSize

proc padPacketData*(data: openArray[uint8], targetSize: int = 0): seq[uint8] =
  let target = if targetSize > 0: targetSize else: getOptimalBlockSize(data.len)
  if data.len >= target:
    result = @data
    return

  let paddingNeeded = target - data.len
  if paddingNeeded > MaxPaddingSize:
    result = @data
    return

  result = newSeq[uint8](target)
  if data.len > 0:
    copyMem(addr result[0], unsafeAddr data[0], data.len)

  if paddingNeeded > 1:
    let randBytes = urandom(paddingNeeded - 1)
    copyMem(addr result[data.len], unsafeAddr randBytes[0], paddingNeeded - 1)

  result[target - 1] = uint8(paddingNeeded)

proc padPacketDataDeterministic*(data: openArray[uint8], fillByte: uint8, targetSize: int = 0): seq[uint8] =
  let target = if targetSize > 0: targetSize else: getOptimalBlockSize(data.len)
  if data.len >= target:
    result = @data
    return

  let paddingNeeded = target - data.len
  if paddingNeeded > MaxPaddingSize:
    result = @data
    return

  result = newSeq[uint8](target)
  if data.len > 0:
    copyMem(addr result[0], unsafeAddr data[0], data.len)

  for i in data.len ..< (target - 1):
    result[i] = fillByte

  result[target - 1] = uint8(paddingNeeded)

proc unpadPacketData*(data: openArray[uint8]): seq[uint8] =
  if data.len == 0:
    return @[]

  let paddingLength = int(data[^1])
  if paddingLength == 0 or paddingLength > data.len or paddingLength > MaxPaddingSize:
    return @data

  result = newSeq[uint8](data.len - paddingLength)
  if result.len > 0:
    copyMem(addr result[0], unsafeAddr data[0], result.len)
