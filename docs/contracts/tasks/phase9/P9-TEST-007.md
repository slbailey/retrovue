Task ID: P9-TEST-007
Rule ID: INV-P9-STEADY-004
Governing Law: LAW-OUTPUT-LIVENESS
Subsystem: ProgramOutput
Task Type: TEST
File(s) to Create: pkg/air/tests/contracts/SteadyStateContractTests.cpp
Owner: AIR
Blocked By: P9-CORE-007

Instructions:
- Test pad-while-depth-high violation detection
- Set buffer depth to 15 frames
- Force pad emission
- Verify violation logged
- Verify counter incremented

---

Rule Definition (INV-P9-STEADY-004):
MUST: Log `INV-P9-STEADY-004 VIOLATION` if pad emitted with depth ≥ 10.

Test Implementation:

```cpp
TEST(SteadyStateContractTests, INV_P9_STEADY_004_ViolationDetection) {
    // Setup
    auto output = CreateTestProgramOutput();
    auto buffer = output->GetVideoBuffer();

    // Fill buffer with 15 frames
    for (int i = 0; i < 15; i++) {
        buffer->TryPush(CreateVideoFrame());
    }
    ASSERT_EQ(buffer->Size(), 15);
    ASSERT_GE(buffer->Size(), 10);  // Above violation threshold

    // Capture logs
    auto log_capture = StartLogCapture();

    // Initial violation count
    auto initial_violations = output->GetPadWhileDepthHighCount();
    EXPECT_EQ(initial_violations, 0);

    // Force pad emission (simulating CT mismatch or flow bug)
    output->ForceEmitPad();

    // Assert violation logged
    auto logs = log_capture.GetLogs();
    EXPECT_TRUE(ContainsLog(logs, "INV-P9-STEADY-004 VIOLATION"));
    EXPECT_TRUE(ContainsLog(logs, "depth=15"));

    // Assert counter incremented
    EXPECT_EQ(output->GetPadWhileDepthHighCount(), 1);
}
```

Done Criteria:
Test passes; violation logged with correct depth; counter incremented; distinguishable from legitimate starvation.
