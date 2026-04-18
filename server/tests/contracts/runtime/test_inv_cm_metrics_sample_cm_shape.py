"""INV-CM-METRICS-SAMPLE-CM-SHAPE-001

After ADR-004 Phase 5C.2 retired ``BlockPlanProducer``, ``ChannelManager``
is its own producer (``self.active_producer = self``). CM MUST NOT call
BPP-era producer methods on ``self.active_producer`` in
``populate_metrics_sample`` — those raise ``AttributeError`` at runtime
once a ``MetricsPublisher`` is attached.

This is the same class of gap as INV-CM-TEARDOWN-SYNCHRONOUS-001 and
INV-CM-READER-SOCKET-QUEUE-PROXY-001 — code that used to reach into
``active_producer`` expecting BPP shape — but in a *latent* form. Today
no production caller invokes ``attach_metrics_publisher``, so the bug
doesn't crash. The first caller that does will crash immediately.

Forbidden inside ``populate_metrics_sample``:
    - ``.get_segment_progress(`` on any value derived from ``active_producer``
    - ``.get_frame_counters(`` on any value derived from ``active_producer``

Instead, ``populate_metrics_sample`` MUST derive metrics from CM-local
state (``runtime_state.producer_status``, ``viewer_sessions``, etc.) and
explicitly report ``None`` / ``0.0`` for counters CM does not track.

Runtime guarantee: invoking ``populate_metrics_sample`` on a CM whose
producer is running MUST NOT raise ``AttributeError``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
CM_PATH = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "channel_manager.py"

BPP_PRODUCER_METHODS = ("get_segment_progress", "get_frame_counters")


class TestPopulateMetricsSampleHasNoBppCalls:
    """AST scan: the body of ``populate_metrics_sample`` must contain no
    calls to BPP-era producer methods."""

    def _populate_metrics_sample_node(self) -> ast.FunctionDef:
        tree = ast.parse(CM_PATH.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "ChannelManager":
                for child in node.body:
                    if isinstance(child, ast.FunctionDef) and child.name == "populate_metrics_sample":
                        return child
        raise AssertionError(
            "populate_metrics_sample not found on ChannelManager; "
            "retire INV-CM-METRICS-SAMPLE-CM-SHAPE-001 if this method was removed"
        )

    def test_no_get_segment_progress_call(self) -> None:
        fn = self._populate_metrics_sample_node()
        offenders: list[int] = []
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "get_segment_progress":
                    offenders.append(node.lineno)
        assert not offenders, (
            "populate_metrics_sample MUST NOT call .get_segment_progress() — "
            "that is a BPP-era producer method, and active_producer is now "
            "ChannelManager itself (INV-CM-METRICS-SAMPLE-CM-SHAPE-001). "
            f"Offenders at lines: {offenders}"
        )

    def test_no_get_frame_counters_call(self) -> None:
        fn = self._populate_metrics_sample_node()
        offenders: list[int] = []
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "get_frame_counters":
                    offenders.append(node.lineno)
        assert not offenders, (
            "populate_metrics_sample MUST NOT call .get_frame_counters() — "
            "that is a BPP-era producer method "
            "(INV-CM-METRICS-SAMPLE-CM-SHAPE-001). "
            f"Offenders at lines: {offenders}"
        )


class TestPopulateMetricsSampleDoesNotRaise:
    """Runtime smoke: ``populate_metrics_sample`` on a CM with producer
    running MUST NOT raise ``AttributeError`` for BPP-era method names.
    This is the exact crash that would fire when a MetricsPublisher is
    attached post-5C.2."""

    def test_populate_metrics_sample_on_running_producer_does_not_attributerror(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager
        from retrovue.runtime.clock import SystemClock
        from retrovue.runtime.metrics import ChannelMetricsSample

        class _StubPD:
            def __init__(self) -> None:
                self._clock = SystemClock()

            def is_channel_in_linger(self, channel_id: str) -> bool:
                return False

            def get_channel_mode(self, channel_id: str) -> str:
                return "block_plan"

            def on_producer_failure(self, channel_id: str, reason: str) -> None:
                pass

            def register_fanout_buffer(self, channel_id: str, fanout) -> None:
                pass

        pd = _StubPD()
        try:
            cm = ChannelManager(
                channel_id="metrics-test",
                program_director=pd,
                clock=pd._clock,
            )
        except TypeError:
            pytest.skip(
                "ChannelManager constructor requires extra collaborators; "
                "AST-level guards above remain the primary enforcement."
            )
            return

        cm.active_producer = cm
        sample = ChannelMetricsSample()
        try:
            cm.populate_metrics_sample(sample)
        except AttributeError as exc:
            msg = str(exc)
            if any(m in msg for m in ("get_segment_progress", "get_frame_counters")):
                pytest.fail(
                    "populate_metrics_sample raised AttributeError on a "
                    f"BPP-era producer method: {exc} "
                    "(INV-CM-METRICS-SAMPLE-CM-SHAPE-001)"
                )
            raise
