Task ID: P9-TEST-012
Rule ID: INV-P9-STEADY-008
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: MpegTSOutputSink
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-003

Instructions:
- Test that silence injection is disabled in steady-state
- Enter steady-state
- Empty audio queue
- Verify mux stalls (video also stalls)
- Verify NO silence frames injected

---

Rule Definition (INV-P9-STEADY-008):
MUST: Disable silence injection on steady-state entry.
MUST: Stall mux when audio unavailable (video waits).
MUST NOT: Inject silence during steady-state.

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_008_SilenceDisabled) {
    // Setup
    auto sink = CreateTestSink();

    // Fill video buffer
    for (int i = 0; i < 10; i++) {
        sink->PushVideoFrame(CreateVideoFrame());
    }

    // Ensure audio is empty
    sink->ClearAudioBuffer();
    ASSERT_EQ(sink->GetAudioBufferDepth(), 0);

    // Enter steady-state
    sink->EnterSteadyState();

    // Capture initial state
    auto initial_silence_count = sink->GetSilenceFramesInjected();
    auto initial_video_emitted = sink->GetVideoFramesEmitted();

    // Wait - mux should stall
    std::this_thread::sleep_for(500ms);

    // Get final state
    auto final_silence_count = sink->GetSilenceFramesInjected();
    auto final_video_emitted = sink->GetVideoFramesEmitted();

    // Assert: NO silence injected
    EXPECT_EQ(final_silence_count, initial_silence_count);

    // Assert: Video also stalled (no video emitted without audio)
    EXPECT_EQ(final_video_emitted, initial_video_emitted);

    // Assert: silence_injection_disabled flag is set
    EXPECT_TRUE(sink->IsSilenceInjectionDisabled());

    LOG_INFO("Silence injected: {} (should be 0), Video emitted: {} (should be 0)",
             final_silence_count - initial_silence_count,
             final_video_emitted - initial_video_emitted);
}
```

Done Criteria:
Test passes; no silence frames injected; mux stalled when audio empty; video also stalled.
