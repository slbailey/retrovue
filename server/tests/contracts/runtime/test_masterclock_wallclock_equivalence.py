"""Contract: SystemClock.now_utc().timestamp() is wall-clock equivalent to time.time().

Proves that the concrete SystemClock class uses a wall-clock source (e.g.
datetime.now(timezone.utc)) such that its timestamp matches time.time() within
a small bound. No sleeping; samples in a tight loop to allow for system/VM jitter.
"""

import time


def test_masterclock_now_utc_timestamp_within_250ms_of_time_time():
    """SystemClock().now_utc().timestamp() and time.time() agree within 250ms."""
    from retrovue.runtime.clock import SystemClock

    clock = SystemClock()
    for i in range(25):
        t1 = time.time()
        t2 = clock.now_utc().timestamp()
        assert abs(t2 - t1) < 0.250, (
            f"Sample {i + 1}/25: |now_utc().timestamp() - time.time()| = {abs(t2 - t1):.6f}s >= 0.250s"
        )
