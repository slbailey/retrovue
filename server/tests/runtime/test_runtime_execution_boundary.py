from __future__ import annotations

import inspect


def test_runtime_protocols_expose_no_schedule_service_surface():
    import retrovue.runtime.protocols as protocols

    source = inspect.getsource(protocols)
    assert "class ScheduleService" not in source
    assert "def get_playout_plan_now" not in source
    assert "def get_block_at" not in source


def test_runtime_execution_modules_do_not_reference_legacy_planning_apis():
    # Phase 5C.2 (INV-BPP-RETIRED-001): BlockPlanProducer retired; ChannelManager
    # absorbs its orchestration and gets scanned in its place.
    from retrovue.runtime.channel_manager import ChannelManager
    from retrovue.runtime.test_playout_endpoint import SingleBlockExecutionReader

    forbidden_tokens = (
        "ScheduleService",
        "get_playout_plan_now",
        "get_block_at(",
        "schedule_service",
    )

    for obj in (ChannelManager, SingleBlockExecutionReader):
        source = inspect.getsource(obj)
        for token in forbidden_tokens:
            assert token not in source, f"{obj.__name__} still references {token}"
