Task ID: P9-TEST-003
Rule ID: INV-P9-STEADY-002
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: FileProducer
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-005

Instructions:
- Test that producer blocks when buffer at capacity
- Fill buffer to capacity
- Attempt decode
- Verify producer thread blocks
- Verify producer resumes when exactly 1 slot frees

---

Rule Definition (INV-P9-STEADY-002):
MUST: Block at decode gate when buffer full.
MUST: Resume when exactly one slot frees.

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_002_SlotBasedBlocking) {
    // Setup
    auto producer = CreateTestProducer();
    auto buffer = producer->GetVideoBuffer();
    const auto capacity = buffer->Capacity();

    // Fill to capacity
    for (size_t i = 0; i < capacity; i++) {
        auto frame = CreateVideoFrame();
        ASSERT_TRUE(buffer->TryPush(frame));
    }
    ASSERT_EQ(buffer->Size(), capacity);

    // Start decode in background thread
    std::atomic<bool> decode_completed{false};
    std::thread decoder([&]() {
        producer->DecodeOneFrame();  // Should block
        decode_completed = true;
    });

    // Wait briefly - decode should NOT complete
    std::this_thread::sleep_for(100ms);
    EXPECT_FALSE(decode_completed);  // Still blocked

    // Free exactly 1 slot
    auto _ = buffer->Pop();
    EXPECT_EQ(buffer->Size(), capacity - 1);

    // Wait for decode to complete
    decoder.join();
    EXPECT_TRUE(decode_completed);  // Now unblocked

    // Buffer should be back at capacity
    EXPECT_EQ(buffer->Size(), capacity);
}
```

Done Criteria:
Test passes; producer demonstrably blocks at capacity; resumes after exactly 1 slot freed.
