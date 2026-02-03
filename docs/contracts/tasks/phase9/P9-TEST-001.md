Task ID: P9-TEST-001
Rule ID: INV-P9-STEADY-001
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: MpegTSOutputSink
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-002

Instructions:
- Test that mux waits for frame CT before dequeue
- Push frame with `ct_us = now + 100ms`
- Verify mux does not dequeue until wall_clock reaches ct_us
- Verify frame emission timestamp matches ct_us ± 1ms

---

Rule Definition (INV-P9-STEADY-001):
After output attach, the mux loop MUST be the sole pacing authority. Frame emission occurs when the output clock (PCR-paced wall clock) reaches frame CT, not when frames become available.

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_001_MuxWaitsForCT) {
    // Setup
    auto sink = CreateTestSink();
    sink->EnterSteadyState();

    auto now = GetWallClockUs();
    auto frame = CreateVideoFrame();
    frame.ct_us = now + 100'000;  // CT is 100ms in future

    // Act
    auto push_time = GetWallClockUs();
    sink->PushVideoFrame(frame);

    // Wait for emission
    auto emitted_frame = sink->WaitForEmission(200ms);

    // Assert
    ASSERT_TRUE(emitted_frame.has_value());

    auto emit_time = emitted_frame->emit_timestamp_us;
    auto delta = emit_time - frame.ct_us;

    // Mux waited for CT
    EXPECT_GE(emit_time, frame.ct_us);

    // Emission within 1ms of CT
    EXPECT_LE(std::abs(delta), 1000);  // 1ms tolerance

    // Did not emit immediately on push
    EXPECT_GE(emit_time - push_time, 99'000);  // ~100ms wait
}
```

Done Criteria:
Test passes; mux demonstrably waits for CT; emission timestamp matches CT within tolerance.
