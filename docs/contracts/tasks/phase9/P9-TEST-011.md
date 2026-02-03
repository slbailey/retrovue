Task ID: P9-TEST-011
Rule ID: INV-P9-STEADY-007
Governing Law: LAW-TIMELINE
Subsystem: MpegTSOutputSink
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-004

Instructions:
- Test that CT is NOT reset on output attach
- Set producer CT to 1 hour (3,600,000,000 µs)
- Attach output
- Verify first muxed frame PTS = 3,600,000,000 µs (not 0)

---

Rule Definition (INV-P9-STEADY-007):
MUST: Use `audio_frame.pts_us` and `video_frame.ct_us` directly.
MUST NOT: Reset CT on attach.

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_007_NoCTResetOnAttach) {
    // Setup
    auto producer = CreateTestProducer();
    auto sink = CreateTestSink();

    // Producer CT starts at 1 hour
    constexpr int64_t kOneHourUs = 3'600'000'000LL;
    producer->SetBaseCT(kOneHourUs);

    // Push frame with CT = 1 hour
    auto frame = CreateVideoFrame();
    frame.ct_us = kOneHourUs;
    producer->PushVideoFrame(frame);

    // Attach sink (this is where a buggy impl would reset CT)
    sink->Attach();
    sink->EnterSteadyState();

    // Wait for emission
    auto emitted = sink->WaitForEmission(1s);

    // Assert CT was NOT reset
    ASSERT_TRUE(emitted.has_value());
    EXPECT_EQ(emitted->pts_us, kOneHourUs);

    // Explicitly verify NOT 0
    EXPECT_NE(emitted->pts_us, 0);

    LOG_INFO("First emitted PTS: {}us (expected {}us)",
             emitted->pts_us, kOneHourUs);
}
```

Done Criteria:
Test passes; first emitted PTS = producer CT (1 hour); no CT reset to 0.
