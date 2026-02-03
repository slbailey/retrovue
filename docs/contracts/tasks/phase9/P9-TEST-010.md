Task ID: P9-TEST-010
Rule ID: INV-P9-STEADY-006
Governing Law: LAW-CLOCK
Subsystem: MpegTSOutputSink
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-002

Instructions:
- Test PTS bounded to MasterClock
- Play for 60 seconds
- Compare final PTS elapsed to MasterClock elapsed
- Verify delta < 100ms

---

Rule Definition (INV-P9-STEADY-006):
MUST: Keep `|master_clock_elapsed - pts_elapsed| < 100ms`.

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_006_PTSBoundedToClock) {
    // Setup
    auto engine = CreateTestPlayoutEngine();
    engine->StartChannel("test");
    engine->EnterSteadyState();

    // Record initial state
    auto initial_master_clock = engine->GetMasterClockUs();
    auto initial_pts = engine->GetLastEmittedPTS();

    // Play for 60 seconds
    std::this_thread::sleep_for(60s);

    // Record final state
    auto final_master_clock = engine->GetMasterClockUs();
    auto final_pts = engine->GetLastEmittedPTS();

    engine->StopChannel();

    // Calculate elapsed
    auto master_clock_elapsed = final_master_clock - initial_master_clock;
    auto pts_elapsed = final_pts - initial_pts;

    // Calculate drift
    auto drift_us = std::abs(master_clock_elapsed - pts_elapsed);

    // Assert drift < 100ms (100,000 us)
    EXPECT_LT(drift_us, 100'000);

    LOG_INFO("MasterClock elapsed: {}us, PTS elapsed: {}us, Drift: {}us",
             master_clock_elapsed, pts_elapsed, drift_us);
}
```

Done Criteria:
Test passes; PTS drift from MasterClock < 100ms over 60 seconds.
