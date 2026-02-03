Task ID: P9-TEST-002
Rule ID: INV-P9-STEADY-001
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: MpegTSOutputSink
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-002

Instructions:
- Test that mux emits at most 1 frame per pacing period
- Fill buffer with 10 frames
- Run steady-state playout for 10 seconds
- Verify output rate matches target FPS exactly
- Verify no burst consumption

---

Rule Definition (INV-P9-STEADY-001):
MUST NOT: Mux consume frames as fast as they are produced.

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_001_NoBurstConsumption) {
    // Setup
    auto sink = CreateTestSink();
    sink->SetTargetFPS(30);
    sink->EnterSteadyState();

    // Fill buffer with 10 frames
    auto base_ct = GetWallClockUs();
    for (int i = 0; i < 10; i++) {
        auto frame = CreateVideoFrame();
        frame.ct_us = base_ct + i * 33'333;  // 30fps spacing
        sink->PushVideoFrame(frame);
    }

    // Record emissions for 10 seconds
    std::vector<int64_t> emission_times;
    auto start = std::chrono::steady_clock::now();

    while (std::chrono::steady_clock::now() - start < 10s) {
        auto emitted = sink->WaitForEmission(100ms);
        if (emitted) {
            emission_times.push_back(emitted->emit_timestamp_us);
        }
    }

    // Assert: frame count matches target
    // 10 seconds at 30fps = 300 frames ± 1
    EXPECT_GE(emission_times.size(), 299);
    EXPECT_LE(emission_times.size(), 301);

    // Assert: no burst (max 1 frame per ~33ms period)
    for (size_t i = 1; i < emission_times.size(); i++) {
        auto delta = emission_times[i] - emission_times[i-1];
        // Allow ± 10% jitter on frame period
        EXPECT_GE(delta, 30'000);  // >= 30ms
        EXPECT_LE(delta, 36'666);  // <= 36.6ms
    }
}
```

Done Criteria:
Test passes; output rate matches target FPS; no burst consumption detected; frame spacing consistent.
