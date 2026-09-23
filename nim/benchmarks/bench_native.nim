import std/[times, monotimes, strformat, random]
import ../src/bitchat_types
import ../src/bitchat_padding
import ../src/bitchat_packet
import ../src/bitchat_fragment
import ../src/bitchat_reassembly

proc formatResult(name: string, iters: int, elapsedSec: float64, totalBytes: int) =
  let opsPerSec = float64(iters) / elapsedSec
  let mbPerSec = (float64(totalBytes) / (1024.0 * 1024.0)) / elapsedSec
  let msTotal = elapsedSec * 1000.0
  echo &"| {name:<36} | {iters:>8} | {msTotal:>9.2f} ms | {opsPerSec:>11.0f} | {mbPerSec:>9.2f} MB/s |"

proc runBenchmarks*() =
  echo "| Workload                             |    Iters |   Duration  |     Ops/sec |  Throughput |"
  echo "|--------------------------------------|----------|-------------|-------------|-------------|"

  let sender: array[8, uint8] = [1'u8, 2, 3, 4, 5, 6, 7, 8]
  let emptyRecip: array[8, uint8] = [0'u8, 0, 0, 0, 0, 0, 0, 0]

  # 1. Small Packet (64B)
  block:
    let payload = newSeq[uint8](64)
    let iters = 50_000
    var dummy = 0
    # Warmup
    for _ in 0..<500:
      let enc = encodePacketRaw(1, 4, 7, 1000, 0, sender, emptyRecip, payload, @[], true)
      dummy += enc.len

    let t0 = getMonoTime()
    for _ in 0..<iters:
      let enc = encodePacketRaw(1, 4, 7, 1000, 0, sender, emptyRecip, payload, @[], true)
      dummy += enc.len
    let elapsed = (getMonoTime() - t0).inNanoseconds.float64 / 1e9
    formatResult("Small Packet Encode (64B)", iters, elapsed, iters * 64)

  # 2. Medium Packet (256B)
  block:
    let payload = newSeq[uint8](256)
    let iters = 50_000
    var dummy = 0
    let t0 = getMonoTime()
    for _ in 0..<iters:
      let enc = encodePacketRaw(1, 4, 7, 1000, 0, sender, emptyRecip, payload, @[], true)
      dummy += enc.len
    let elapsed = (getMonoTime() - t0).inNanoseconds.float64 / 1e9
    formatResult("Medium Packet Encode (256B)", iters, elapsed, iters * 256)

  # 3. Large Packet (800B)
  block:
    let payload = newSeq[uint8](800)
    let iters = 20_000
    var dummy = 0
    let t0 = getMonoTime()
    for _ in 0..<iters:
      let enc = encodePacketRaw(1, 4, 7, 1000, 0, sender, emptyRecip, payload, @[], true)
      dummy += enc.len
    let elapsed = (getMonoTime() - t0).inNanoseconds.float64 / 1e9
    formatResult("Large Packet Encode (800B)", iters, elapsed, iters * 800)

  # 4. 500-byte Boundary Check
  block:
    let iters = 200_000
    var count = 0
    let t0 = getMonoTime()
    for _ in 0..<iters:
      if shouldFragment(499): inc count
      if shouldFragment(500): inc count
      if shouldFragment(501): inc count
    let elapsed = (getMonoTime() - t0).inNanoseconds.float64 / 1e9
    formatResult("Boundary Evaluation (499/500/501B)", iters * 3, elapsed, (iters * 3) * 500)

  # 5. Fragment Packet (600B)
  block:
    let data = newSeq[uint8](600)
    let iters = 20_000
    var dummy = 0
    let t0 = getMonoTime()
    for _ in 0..<iters:
      let chunks = splitChunks(data, 150)
      dummy += chunks.len
    let elapsed = (getMonoTime() - t0).inNanoseconds.float64 / 1e9
    formatResult("Chunk Slicing (600B -> 4 frags)", iters, elapsed, iters * 600)

  # 6. Fragment Packet (1500B)
  block:
    let data = newSeq[uint8](1500)
    let iters = 10_000
    var dummy = 0
    let t0 = getMonoTime()
    for _ in 0..<iters:
      let chunks = splitChunks(data, 150)
      dummy += chunks.len
    let elapsed = (getMonoTime() - t0).inNanoseconds.float64 / 1e9
    formatResult("Chunk Slicing (1500B -> 10 frags)", iters, elapsed, iters * 1500)

  # 7. Multi-Fragment In-Order Reassembly (10 chunks)
  block:
    let iters = 5_000
    let fid: array[8, uint8] = [1'u8, 2, 3, 4, 5, 6, 7, 8]
    let chunkData = newSeq[uint8](150)
    var payloads = newSeq[seq[uint8]](10)
    for i in 0..<10:
      payloads[i] = createFragmentPayload(fid, uint16(i), 10, 4, chunkData)

    let r = newNimFragmentReassembler()
    var dummy = 0
    let t0 = getMonoTime()
    for _ in 0..<iters:
      var res: seq[uint8]
      var comp: bool
      for i in 0..<10:
        discard r.addFragment(sender, payloads[i], res, comp)
      dummy += res.len
    let elapsed = (getMonoTime() - t0).inNanoseconds.float64 / 1e9
    formatResult("Reassembly In-Order (10 chunks)", iters, elapsed, iters * 1500)

  # 8. Multi-Fragment Randomized Reassembly (10 chunks)
  block:
    let iters = 5_000
    let fid: array[8, uint8] = [1'u8, 2, 3, 4, 5, 6, 7, 8]
    let chunkData = newSeq[uint8](150)
    var payloads = newSeq[seq[uint8]](10)
    for i in 0..<10:
      payloads[i] = createFragmentPayload(fid, uint16(i), 10, 4, chunkData)

    var order = @[0, 5, 2, 8, 1, 9, 3, 7, 4, 6]
    let r = newNimFragmentReassembler()
    var dummy = 0
    let t0 = getMonoTime()
    for _ in 0..<iters:
      var res: seq[uint8]
      var comp: bool
      for idx in order:
        discard r.addFragment(sender, payloads[idx], res, comp)
      dummy += res.len
    let elapsed = (getMonoTime() - t0).inNanoseconds.float64 / 1e9
    formatResult("Reassembly Randomized (10 chunks)", iters, elapsed, iters * 1500)

when isMainModule:
  runBenchmarks()
