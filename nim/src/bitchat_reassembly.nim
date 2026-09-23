import std/[tables, hashes]
import bitchat_types
import bitchat_fragment

type
  AssemblyKey* = object
    senderId*: array[8, uint8]
    fragmentId*: array[8, uint8]

proc hash*(k: AssemblyKey): Hash =
  var h: Hash = 0
  for b in k.senderId:
    h = h !& int(b)
  for b in k.fragmentId:
    h = h !& int(b)
  result = !$h

type
  AssemblyState* = ref object
    senderId*: array[8, uint8]
    fragmentId*: array[8, uint8]
    total*: uint16
    originalType*: uint8
    chunks*: Table[uint16, seq[uint8]]
    totalBytes*: int

  NimFragmentReassembler* = ref object
    maxActiveAssemblies*: int
    maxFragmentsPerAssembly*: int
    maxReassembledBytes*: int
    assemblies*: Table[AssemblyKey, AssemblyState]
    activeKeys*: seq[AssemblyKey]

proc newNimFragmentReassembler*(
    maxActiveAssemblies: int = MaxActiveAssemblies,
    maxFragmentsPerAssembly: int = MaxFragmentsPerAssembly,
    maxReassembledBytes: int = MaxReassembledBytes,
): NimFragmentReassembler =
  result = NimFragmentReassembler(
    maxActiveAssemblies: maxActiveAssemblies,
    maxFragmentsPerAssembly: maxFragmentsPerAssembly,
    maxReassembledBytes: maxReassembledBytes,
    assemblies: initTable[AssemblyKey, AssemblyState](),
    activeKeys: @[],
  )

proc clear*(r: NimFragmentReassembler) =
  r.assemblies.clear()
  r.activeKeys.setLen(0)

proc activeCount*(r: NimFragmentReassembler): int =
  result = r.assemblies.len

proc removeKey(r: NimFragmentReassembler, key: AssemblyKey) =
  r.assemblies.del(key)
  for i in 0 ..< r.activeKeys.len:
    if r.activeKeys[i] == key:
      r.activeKeys.delete(i)
      break

proc addFragment*(
    r: NimFragmentReassembler,
    senderId: ptr uint8,
    payload: ptr uint8,
    payloadLen: int,
    reassembledData: var seq[uint8],
    isComplete: var bool,
): int32 =
  isComplete = false
  reassembledData.setLen(0)

  if senderId == nil or payload == nil or payloadLen < FragmentHeaderSize:
    return ErrInvalidInput

  var fragId: array[8, uint8]
  var index: uint16
  var total: uint16
  var origType: uint8
  var dataOffset: int
  var dataLen: int

  let parseStatus = parseFragmentPayload(
    payload, payloadLen, fragId, index, total, origType, dataOffset, dataLen
  )
  if parseStatus != BitchatOk:
    return parseStatus

  if total > uint16(r.maxFragmentsPerAssembly):
    return ErrFragmentLimit

  var key: AssemblyKey
  copyMem(addr key.senderId[0], senderId, SenderIdSize)
  copyMem(addr key.fragmentId[0], addr fragId[0], FragmentIdSize)

  var state: AssemblyState
  if r.assemblies.hasKey(key):
    state = r.assemblies[key]
    if state.total != total or state.originalType != origType:
      r.removeKey(key)
      return ErrInvalidInput
  else:
    if r.assemblies.len >= r.maxActiveAssemblies:
      if r.activeKeys.len > 0:
        let oldest = r.activeKeys[0]
        r.removeKey(oldest)

    state = AssemblyState(
      senderId: key.senderId,
      fragmentId: key.fragmentId,
      total: total,
      originalType: origType,
      chunks: initTable[uint16, seq[uint8]](),
      totalBytes: 0,
    )
    r.assemblies[key] = state
    r.activeKeys.add(key)

  let pArr = cast[ptr UncheckedArray[uint8]](payload)
  var chunkSlice = newSeq[uint8](dataLen)
  if dataLen > 0:
    copyMem(addr chunkSlice[0], addr pArr[dataOffset], dataLen)

  if state.chunks.hasKey(index):
    let existing = state.chunks[index]
    if existing != chunkSlice:
      r.removeKey(key)
      return ErrConflictingFragment
  else:
    let newTotalBytes = state.totalBytes + dataLen
    if newTotalBytes > r.maxReassembledBytes:
      r.removeKey(key)
      return ErrFragmentLimit

    state.chunks[index] = chunkSlice
    state.totalBytes = newTotalBytes

  if state.chunks.len == int(state.total):
    var complete = true
    for idx in 0 ..< int(state.total):
      if not state.chunks.hasKey(uint16(idx)):
        complete = false
        break

    if complete:
      reassembledData = newSeq[uint8](state.totalBytes)
      var writeOffset = 0
      for idx in 0 ..< int(state.total):
        let c = state.chunks[uint16(idx)]
        if c.len > 0:
          copyMem(addr reassembledData[writeOffset], unsafeAddr c[0], c.len)
          writeOffset += c.len

      r.removeKey(key)
      isComplete = true

  return BitchatOk

proc addFragment*(
    r: NimFragmentReassembler,
    senderId: openArray[uint8],
    payload: openArray[uint8],
    reassembledData: var seq[uint8],
    isComplete: var bool,
): int32 =
  if senderId.len != SenderIdSize or payload.len < FragmentHeaderSize:
    return ErrInvalidInput
  return addFragment(
    r, unsafeAddr senderId[0], unsafeAddr payload[0], payload.len,
    reassembledData, isComplete
  )
