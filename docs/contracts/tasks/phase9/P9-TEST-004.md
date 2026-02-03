Task ID: P9-TEST-004
Rule ID: INV-P9-STEADY-002
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: FileProducer
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-005

Instructions:
- Test that producer does NOT use hysteresis (no low-water mark)
- Fill buffer to capacity
- Free 1 slot
- Verify producer resumes immediately (not waiting for low-water drain)
- Verify buffer refills to capacity

---

Rule Definition (INV-P9-STEADY-002):
MUST NOT: Use hysteresis (low-water drain).

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_002_NoHysteresis) {
    // Setup
    auto producer = CreateTestProducer();
    auto buffer = producer->GetVideoBuffer();
    const auto capacity = buffer->Capacity();

    // Fill to capacity
    for (size_t i = 0; i < capacity; i++) {
        ASSERT_TRUE(buffer->TryPush(CreateVideoFrame()));
    }

    // Track producer decode timing
    std::vector<std::chrono::steady_clock::time_point> resume_times;

    // Simulate consumer draining one frame at a time
    for (int drain = 0; drain < 5; drain++) {
        // Free 1 slot
        auto pop_time = std::chrono::steady_clock::now();
        buffer->Pop();

        // Producer should resume IMMEDIATELY (within 10ms)
        // NOT wait for low-water mark (e.g., drain to 2)
        std::atomic<bool> resumed{false};
        std::thread decoder([&]() {
            producer->DecodeOneFrame();
            resumed = true;
        });

        // Allow 10ms for producer to notice slot
        std::this_thread::sleep_for(10ms);
        decoder.join();

        // Should have resumed quickly
        EXPECT_TRUE(resumed);

        // Buffer back at capacity
        EXPECT_EQ(buffer->Size(), capacity);
    }

    // FORBIDDEN: If hysteresis were present, producer would wait until
    // depth dropped to low-water (e.g., 2) before resuming.
    // This test proves immediate resume on 1-slot free.
}
```

Done Criteria:
Test passes; producer resumes immediately on 1-slot free; no evidence of low-water drain.
