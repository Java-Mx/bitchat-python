import std/unittest
import ../src/bitchat_types
import ../src/bitchat_fragment
import ../src/bitchat_reassembly

suite "Nim Fragmentation & Reassembly Tests":

  test "Threshold condition":
    check not shouldFragment(500)
    check shouldFragment(501)

  test "Chunk splitting boundaries":
    var data = newSeq[uint8](350)
    for i in 0..<350: data[i] = uint8(i and 0xFF)
    let chunks = splitChunks(data, 150)
    check chunks.len == 3
    check chunks[0].len == 150
    check chunks[1].len == 150
    check chunks[2].len == 50

  test "Fragment payload creation and parsing":
    let fid: array[8, uint8] = [1'u8, 2, 3, 4, 5, 6, 7, 8]
    let chunk = @[0xAA'u8, 0xBB, 0xCC, 0xDD]
    let payload = createFragmentPayload(fid, 0, 3, uint8(MessageType.Message), chunk)
    check payload.len == 13 + 4

    var outFid: array[8, uint8]
    var outIdx, outTot: uint16
    var outType: uint8
    var dOff, dLen: int

    let status = parseFragmentPayload(payload, outFid, outIdx, outTot, outType, dOff, dLen)
    check status == BitchatOk
    check outFid == fid
    check outIdx == 0
    check outTot == 3
    check outType == uint8(MessageType.Message)
    check dLen == 4
    check payload[dOff ..< dOff + dLen] == chunk

  test "Reassembly in order":
    let r = newNimFragmentReassembler()
    let sender: array[8, uint8] = [1'u8, 2, 3, 4, 5, 6, 7, 8]
    let fid: array[8, uint8] = [9'u8, 9, 9, 9, 9, 9, 9, 9]

    let p0 = createFragmentPayload(fid, 0, 2, uint8(MessageType.Message), @[1'u8, 2, 3])
    let p1 = createFragmentPayload(fid, 1, 2, uint8(MessageType.Message), @[4'u8, 5, 6])

    var res: seq[uint8]
    var comp: bool
    check r.addFragment(sender, p0, res, comp) == BitchatOk
    check not comp

    check r.addFragment(sender, p1, res, comp) == BitchatOk
    check comp
    check res == @[1'u8, 2, 3, 4, 5, 6]
    check r.activeCount() == 0

  test "Reassembly in reverse order":
    let r = newNimFragmentReassembler()
    let sender: array[8, uint8] = [1'u8, 2, 3, 4, 5, 6, 7, 8]
    let fid: array[8, uint8] = [7'u8, 7, 7, 7, 7, 7, 7, 7]

    let p0 = createFragmentPayload(fid, 0, 3, uint8(MessageType.Message), @[10'u8, 20])
    let p1 = createFragmentPayload(fid, 1, 3, uint8(MessageType.Message), @[30'u8, 40])
    let p2 = createFragmentPayload(fid, 2, 3, uint8(MessageType.Message), @[50'u8, 60])

    var res: seq[uint8]
    var comp: bool
    check r.addFragment(sender, p2, res, comp) == BitchatOk
    check not comp
    check r.addFragment(sender, p1, res, comp) == BitchatOk
    check not comp
    check r.addFragment(sender, p0, res, comp) == BitchatOk
    check comp
    check res == @[10'u8, 20, 30, 40, 50, 60]

  test "Duplicate chunks safely ignored":
    let r = newNimFragmentReassembler()
    let sender: array[8, uint8] = [1'u8, 1, 1, 1, 1, 1, 1, 1]
    let fid: array[8, uint8] = [2'u8, 2, 2, 2, 2, 2, 2, 2]

    let p0 = createFragmentPayload(fid, 0, 2, uint8(MessageType.Message), @[1'u8, 2])
    let p1 = createFragmentPayload(fid, 1, 2, uint8(MessageType.Message), @[3'u8, 4])

    var res: seq[uint8]
    var comp: bool
    check r.addFragment(sender, p0, res, comp) == BitchatOk
    # send duplicate p0
    check r.addFragment(sender, p0, res, comp) == BitchatOk
    check not comp
    check r.addFragment(sender, p1, res, comp) == BitchatOk
    check comp
    check res == @[1'u8, 2, 3, 4]

  test "Conflicting chunk rejects and purges assembly":
    let r = newNimFragmentReassembler()
    let sender: array[8, uint8] = [1'u8, 1, 1, 1, 1, 1, 1, 1]
    let fid: array[8, uint8] = [3'u8, 3, 3, 3, 3, 3, 3, 3]

    let p0_a = createFragmentPayload(fid, 0, 2, uint8(MessageType.Message), @[1'u8, 2])
    let p0_b = createFragmentPayload(fid, 0, 2, uint8(MessageType.Message), @[9'u8, 9])

    var res: seq[uint8]
    var comp: bool
    check r.addFragment(sender, p0_a, res, comp) == BitchatOk
    check r.addFragment(sender, p0_b, res, comp) == ErrConflictingFragment
    check r.activeCount() == 0

  test "Sender isolation":
    let r = newNimFragmentReassembler()
    let senderA: array[8, uint8] = [1'u8, 0, 0, 0, 0, 0, 0, 0]
    let senderB: array[8, uint8] = [2'u8, 0, 0, 0, 0, 0, 0, 0]
    let sameFid: array[8, uint8] = [5'u8, 5, 5, 5, 5, 5, 5, 5]

    let pA0 = createFragmentPayload(sameFid, 0, 2, uint8(MessageType.Message), @[0xAA'u8])
    let pB0 = createFragmentPayload(sameFid, 0, 2, uint8(MessageType.Message), @[0xBB'u8])

    var res: seq[uint8]
    var comp: bool
    check r.addFragment(senderA, pA0, res, comp) == BitchatOk
    check r.addFragment(senderB, pB0, res, comp) == BitchatOk
    check r.activeCount() == 2

    let pA1 = createFragmentPayload(sameFid, 1, 2, uint8(MessageType.Message), @[0xA1'u8])
    check r.addFragment(senderA, pA1, res, comp) == BitchatOk
    check comp
    check res == @[0xAA'u8, 0xA1'u8]
    check r.activeCount() == 1
