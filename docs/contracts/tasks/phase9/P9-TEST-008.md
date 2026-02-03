Task ID: P9-TEST-008
Rule ID: INV-P9-STEADY-005
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: FrameRingBuffer, ProgramOutput
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-008

Instructions:
- Test buffer equilibrium over 60 seconds
- Sample buffer depth every second
- Verify all samples in range [1, 2N] where N = target depth (3)
- Verify no monotonic growth or drain

---

Rule Definition (INV-P9-STEADY-005):
MUST: Maintain depth in [1, 2N] range.
MUST NOT: Grow unboundedly (memory leak).
MUST NOT: Drain to zero during normal playback.

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_005_BufferEquilibrium60s) {
    // Setup
    auto engine = CreateTestPlayoutEngine();
    engine->StartChannel("test");
    engine->EnterSteadyState();

    constexpr int kTargetDepth = 3;
    constexpr int kMinDepth = 1;
    constexpr int kMaxDepth = 2 * kTargetDepth;  // 6

    std::vector<int> depth_samples;

    // Sample for 60 seconds
    auto start = std::chrono::steady_clock::now();
    while (std::chrono::steady_clock::now() - start < 60s) {
        auto depth = engine->GetVideoBufferDepth();
        depth_samples.push_back(depth);
        std::this_thread::sleep_for(1s);
    }

    engine->StopChannel();

    // Assert all samples in equilibrium range
    for (size_t i = 0; i < depth_samples.size(); i++) {
        EXPECT_GE(depth_samples[i], kMinDepth)
            << "Sample " << i << " below minimum";
        EXPECT_LE(depth_samples[i], kMaxDepth)
            << "Sample " << i << " above maximum";
    }

    // Assert no monotonic growth
    int growth_streak = 0;
    for (size_t i = 1; i < depth_samples.size(); i++) {
        if (depth_samples[i] > depth_samples[i-1]) {
            growth_streak++;
        } else {
            growth_streak = 0;
        }
        EXPECT_LT(growth_streak, 10)
            << "Monotonic growth detected at sample " << i;
    }

    // Assert no monotonic drain
    int drain_streak = 0;
    for (size_t i = 1; i < depth_samples.size(); i++) {
        if (depth_samples[i] < depth_samples[i-1]) {
            drain_streak++;
        } else {
            drain_streak = 0;
        }
        EXPECT_LT(drain_streak, 10)
            << "Monotonic drain detected at sample " << i;
    }
}
```

Done Criteria:
Test passes; all samples in [1, 6]; no monotonic growth or drain over 60 seconds.
