# P1-MS-003 Verification Complete — LAW-VIDEO-DECODABILITY

**Task ID:** P1-MS-003  
**Rule ID:** LAW-VIDEO-DECODABILITY  
**Subsystem:** MpegTSOutputSink  
**Result:** **PASS**

---

## Rule Definition (recap)

Every segment starts with IDR; real content gates pad; AIR owns keyframes. The TS output must be decodable by standard players (VLC, ffplay).

---

## Verification Checklist

| # | Requirement | Location | Status |
|---|-------------|----------|--------|
| 1 | Locate existing tests for video decodability / IDR-first | Phase84PersistentMpegTsMuxTests.cpp; MpegTSPlayoutSinkContractTests.cpp | ✅ |
| 2 | Confirm test verifies first video frame in TS is IDR | Phase84: `INV_AIR_IDR_BEFORE_OUTPUT_FirstVideoPacketIsIdr` | ✅ |
| 3 | Confirm test verifies TS packets have valid sync byte (0x47) | Phase84: `TsValidity_188AndSync`; Contract: FE-023, helpers | ✅ |
| 4 | Confirm test verifies TS packet size is 188 bytes | Phase84: `TsValidity_188AndSync`; Contract: FE-023 | ✅ |
| 5 | Confirm test parses PAT/PMT successfully | Phase84: `TsValidity_ParsePatAndPmtSuccessfully` | ✅ |

---

## Evidence

### Phase84PersistentMpegTsMuxTests.cpp

- **TsValidity_PacketSize188AndSyncByte0x47**  
  - Asserts every packet has sync byte 0x47 and size 188 (`TsValidity_188AndSync`).  
  - Capture callback sets `bad_sync` if any byte at packet start is not 0x47; test asserts `!bad_sync`.

- **TsValidity_ParsePatAndPmtSuccessfully**  
  - Asserts `ParsePatAndPmt(ts, &psi)` and that `psi.pat_parsed`, `psi.pmt_parsed`, and at least one video PID are present.

- **INV_AIR_IDR_BEFORE_OUTPUT_FirstVideoPacketIsIdr**  
  - Uses `FirstVideoPacketIsKeyframe(ts)` (FFmpeg: first video packet has `AV_PKT_FLAG_KEY`).  
  - Asserts first video packet is keyframe/IDR.

- **INV_AIR_IDR_BEFORE_OUTPUT_GateResetsOnSegmentSwitch**  
  - Uses `FirstAndSecondSegmentStartWithKeyframe(ts)` to assert both segment 1 and segment 2 start with a keyframe (IDR at segment boundary).

### MpegTSPlayoutSinkContractTests.cpp

- **FE-023_TSPacketAlignmentPreserved**  
  - Asserts each 188-byte boundary has sync byte 0x47.  
  - Covers TS validity (188, 0x47) on live sink output.

- **FE-015_OutputIsReadableByFFprobe**  
  - Asserts output is decodable by FFmpeg (`avformat_open_input` / `avformat_find_stream_info`), implying PAT/PMT and stream structure are valid.

- Helpers `ExtractContinuityCounter`, `ExtractPID`, `HasPCR`, `ParseTSPackets` assume 188-byte packets and 0x47 sync; FE-013 uses `ContainsMpegTSPackets` (0x47 at 188-byte boundaries).

---

## Done Criteria

**Confirmed:** A test asserts IDR present at segment boundary, and TS is valid with 0x47 sync.

- **IDR at segment start:** `INV_AIR_IDR_BEFORE_OUTPUT_FirstVideoPacketIsIdr` and `FirstVideoPacketIsKeyframe()`.
- **IDR at segment boundary:** `INV_AIR_IDR_BEFORE_OUTPUT_GateResetsOnSegmentSwitch` and `FirstAndSecondSegmentStartWithKeyframe()`.
- **TS validity (0x47, 188):** `TsValidity_PacketSize188AndSyncByte0x47` and FE-023.
- **PAT/PMT:** `TsValidity_ParsePatAndPmtSuccessfully`.

---

## Conclusion

Verification **passes**. No follow-up task is required. Existing tests in `Phase84PersistentMpegTsMuxTests.cpp` and `MpegTSPlayoutSinkContractTests.cpp` satisfy LAW-VIDEO-DECODABILITY for TS validity (188-byte packets, 0x47 sync), PAT/PMT parsing, and IDR-first at stream and segment boundaries.
