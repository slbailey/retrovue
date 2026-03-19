"""Contract test for HLS timebase authority.

Hypothesis under investigation:
- HLS active-block timebase is updated from FEED/SEED events only.
- It is not updated from authoritative block activation (BlockStarted).
- Therefore active block window can go stale while playout continues.
"""

import inspect
import textwrap


def test_hls_timebase_must_be_advanced_on_block_started_authority():
    """INV-HLS-TIMEBASE-AUTHORITY-001 (new):

    Active block window for HLS MUST advance from authoritative runtime
    activation (BlockStarted/activation callback), not only from feed-time
    events. Otherwise window can freeze under feed stall/queue-full.
    """
    from retrovue.runtime.channel_manager import BlockPlanProducer

    src = textwrap.dedent(inspect.getsource(BlockPlanProducer._on_block_started))

    assert "set_blockplan_timebase" in src, (
        "INV-HLS-TIMEBASE-AUTHORITY-001 violated: _on_block_started() does not "
        "advance HLS timebase. Timebase currently advances only on feed/seed, "
        "which can go stale while blocks continue to start."
    )
