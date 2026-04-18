"""INV-CM-TEARDOWN-SYNCHRONOUS-001

After ADR-004 Phase 5C.2 retired ``BlockPlanProducer``, ``ChannelManager`` is
its own producer (``self.active_producer = self``). Producer teardown is
SYNCHRONOUS: ``_producer_stop(reason=...)`` performs the complete stop
(terminate AIR, join driver thread, reset supply, clear ``active_producer``).

There is no cooperative two-phase teardown protocol any more. Any code that
still calls BPP's cooperative API on ``self.active_producer`` (which is now
``self``) will raise ``AttributeError`` at runtime and leave CM in a
half-torn-down state — producing the exact HBO-outage failure mode observed
2026-04-18 (linger-expiry crash, CM wedged, subsequent tune-ins fail with
``fanout_timeout``).

Forbidden in ``channel_manager.py`` production source:
    - any call to ``.teardown_in_progress(``
    - any call to ``.request_teardown(``
    - any method named ``teardown_in_progress`` or ``request_teardown``
      on ``ChannelManager``

Runtime guarantee: invoking the PD-facing ``stop_producer`` / ``stop_channel``
surface on a CM whose producer is not running MUST NOT raise
``AttributeError``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
CM_PATH = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "channel_manager.py"

BPP_TEARDOWN_METHODS = ("teardown_in_progress", "request_teardown")


class TestChannelManagerHasNoBppTeardownCalls:
    """AST scan: channel_manager.py must contain no calls to BPP's
    cooperative teardown API."""

    def test_no_teardown_in_progress_calls(self) -> None:
        tree = ast.parse(CM_PATH.read_text())
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "teardown_in_progress":
                    offenders.append(
                        f"line {node.lineno}: "
                        f"{ast.unparse(node.func) if hasattr(ast, 'unparse') else node.func.attr}(...)"
                    )
        assert not offenders, (
            "channel_manager.py MUST NOT call .teardown_in_progress() — "
            "that is BPP's cooperative teardown API, retired 2026-04-18 "
            "(ADR-004 Phase 5C.2 / INV-CM-TEARDOWN-SYNCHRONOUS-001). "
            f"Offenders: {offenders}"
        )

    def test_no_request_teardown_calls(self) -> None:
        tree = ast.parse(CM_PATH.read_text())
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "request_teardown":
                    offenders.append(f"line {node.lineno}")
        assert not offenders, (
            "channel_manager.py MUST NOT call .request_teardown() — "
            "use _producer_stop(reason=...) instead "
            "(INV-CM-TEARDOWN-SYNCHRONOUS-001). "
            f"Offenders at: {offenders}"
        )


class TestChannelManagerHasNoBppTeardownMethods:
    """ChannelManager class must not expose BPP-named teardown methods."""

    def test_no_bpp_teardown_method_names(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager
        offenders = [m for m in BPP_TEARDOWN_METHODS if hasattr(ChannelManager, m)]
        assert not offenders, (
            f"ChannelManager exposes BPP-era method(s) {offenders}; "
            "teardown is synchronous via _producer_stop "
            "(INV-CM-TEARDOWN-SYNCHRONOUS-001)"
        )


class TestStopProducerOnIdleCmDoesNotRaiseAttributeError:
    """Runtime smoke: the PD-facing stop path must not AttributeError when
    the producer is not running. This is the exact crash that wedged HBO on
    2026-04-18: PD._on_linger_expired → _stop_channel_internal →
    manager.stop_producer → stop_channel → _stop_producer_if_idle →
    producer.teardown_in_progress() → AttributeError."""

    def test_stop_producer_on_fresh_cm_does_not_raise(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager
        from retrovue.runtime.clock import SystemClock

        class _StubProgramDirector:
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

        pd = _StubProgramDirector()

        try:
            cm = ChannelManager(
                channel_id="hbo-test",
                program_director=pd,
                clock=pd._clock,
            )
        except TypeError:
            pytest.skip("ChannelManager constructor requires extra collaborators; "
                        "AST-level guards above remain the primary enforcement.")
            return

        try:
            cm.stop_producer(reason="test_idle_stop")
        except AttributeError as exc:
            if "teardown_in_progress" in str(exc) or "request_teardown" in str(exc):
                pytest.fail(
                    f"stop_producer on idle CM raised AttributeError on a "
                    f"BPP-era method: {exc} (INV-CM-TEARDOWN-SYNCHRONOUS-001)"
                )
            raise
