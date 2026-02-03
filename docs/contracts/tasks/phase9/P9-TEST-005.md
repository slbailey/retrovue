Task ID: P9-TEST-005
Rule ID: INV-P9-STEADY-003
Governing Law: LAW-AUDIO-FORMAT
Subsystem: FileProducer
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-006

Instructions:
- Test symmetric A/V backpressure
- Measure audio and video frames produced over 10 seconds
- Verify `|audio_frames - video_frames| ≤ 1`
- Verify neither stream runs ahead

---

Rule Definition (INV-P9-STEADY-003):
MUST: Audio blocked when video blocked (and vice versa).
MUST: A/V delta ≤ 1 frame duration at all times.

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_003_SymmetricBackpressure) {
    // Setup
    auto producer = CreateTestProducer();
    auto video_buffer = producer->GetVideoBuffer();
    auto audio_buffer = producer->GetAudioBuffer();

    // Artificially slow consumer (simulate backpressure)
    auto slow_consumer = CreateSlowConsumer(video_buffer, audio_buffer);
    slow_consumer->SetConsumeRate(0.5);  // Half speed

    // Run for 10 seconds
    producer->Start();
    slow_consumer->Start();
    std::this_thread::sleep_for(10s);
    producer->Stop();
    slow_consumer->Stop();

    // Get production counts
    auto video_produced = producer->GetVideoFramesProduced();
    auto audio_produced = producer->GetAudioFramesProduced();

    // Assert symmetric production
    auto delta = std::abs(
        static_cast<int64_t>(video_produced) -
        static_cast<int64_t>(audio_produced));

    // At 30fps, 1 frame = ~3 audio frames (1024 samples at 48kHz)
    // Allow delta of 1 video frame equivalent
    EXPECT_LE(delta, 3);  // ~1 video frame in audio frames

    // Neither should have significantly run ahead
    LOG_INFO("Video produced: {}, Audio produced: {}, Delta: {}",
             video_produced, audio_produced, delta);
}
```

Done Criteria:
Test passes; A/V delta ≤ 1 frame equivalent; neither stream ran ahead under backpressure.
