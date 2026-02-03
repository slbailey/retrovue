Task ID: P9-TEST-006
Rule ID: INV-P9-STEADY-003
Governing Law: LAW-AUDIO-FORMAT
Subsystem: FileProducer
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-006

Instructions:
- Test coordinated A/V stall
- Block video at decode gate
- Verify audio also blocks
- Verify both resume together when capacity available

---

Rule Definition (INV-P9-STEADY-003):
MUST NOT: Audio decode while video blocked.
MUST NOT: Video decode while audio blocked.

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_003_CoordinatedStall) {
    // Setup
    auto producer = CreateTestProducer();
    auto video_buffer = producer->GetVideoBuffer();
    auto audio_buffer = producer->GetAudioBuffer();

    // Fill video to capacity, leave audio with room
    while (video_buffer->Size() < video_buffer->Capacity()) {
        video_buffer->TryPush(CreateVideoFrame());
    }
    ASSERT_EQ(video_buffer->Size(), video_buffer->Capacity());
    ASSERT_LT(audio_buffer->Size(), audio_buffer->Capacity());

    // Track decode attempts
    std::atomic<int> video_decode_attempts{0};
    std::atomic<int> audio_decode_attempts{0};

    // Start producer - should block
    std::thread decoder([&]() {
        // This should block because video is full
        // Audio MUST NOT continue while video is blocked
        producer->DecodeOneIteration();
        video_decode_attempts++;
        audio_decode_attempts++;
    });

    // Wait - decode should NOT complete
    std::this_thread::sleep_for(100ms);
    EXPECT_EQ(video_decode_attempts, 0);
    EXPECT_EQ(audio_decode_attempts, 0);  // Audio also blocked!

    // Free video slot
    video_buffer->Pop();

    // Now both should proceed
    decoder.join();
    EXPECT_EQ(video_decode_attempts, 1);
    EXPECT_EQ(audio_decode_attempts, 1);  // Resumed together
}
```

Done Criteria:
Test passes; audio blocked when video blocked; both resume together.
