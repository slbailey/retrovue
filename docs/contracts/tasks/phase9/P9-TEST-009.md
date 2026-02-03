Task ID: P9-TEST-009
Rule ID: INV-P9-STEADY-006
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: MpegTSOutputSink
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-002

Instructions:
- Test frame rate accuracy over 60 seconds
- Play at 30fps for 60 seconds
- Count total frames emitted
- Verify count = 1800 ± 1 frames

---

Rule Definition (INV-P9-STEADY-006):
MUST: Emit at target FPS ± 1%.

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_006_FrameRateAccuracy) {
    // Setup
    auto engine = CreateTestPlayoutEngine();
    constexpr int kTargetFPS = 30;
    constexpr int kDurationSeconds = 60;
    constexpr int kExpectedFrames = kTargetFPS * kDurationSeconds;  // 1800

    engine->SetTargetFPS(kTargetFPS);
    engine->StartChannel("test");
    engine->EnterSteadyState();

    // Play for 60 seconds
    auto start = std::chrono::steady_clock::now();
    std::this_thread::sleep_for(std::chrono::seconds(kDurationSeconds));
    engine->StopChannel();
    auto elapsed = std::chrono::steady_clock::now() - start;

    // Get frame count
    auto frames_emitted = engine->GetFramesEmittedTotal();

    // Assert frame count within ± 1 frame
    EXPECT_GE(frames_emitted, kExpectedFrames - 1);
    EXPECT_LE(frames_emitted, kExpectedFrames + 1);

    // Calculate actual FPS
    auto elapsed_seconds = std::chrono::duration<double>(elapsed).count();
    auto actual_fps = frames_emitted / elapsed_seconds;

    // Assert within 1% of target
    EXPECT_GE(actual_fps, kTargetFPS * 0.99);
    EXPECT_LE(actual_fps, kTargetFPS * 1.01);

    LOG_INFO("Frames emitted: {} (expected {}), FPS: {:.3f} (target {})",
             frames_emitted, kExpectedFrames, actual_fps, kTargetFPS);
}
```

Done Criteria:
Test passes; frame count = 1800 ± 1; actual FPS within 1% of target.
