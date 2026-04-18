"""INV-CM-READER-SOCKET-QUEUE-PROXY-001

After ADR-004 Phase 5C.2 retired ``BlockPlanProducer``, ``ChannelManager`` is
its own producer (``self.active_producer = self``). The pre-existing
TsConsumptionAdapter factory reads the per-channel UDS reader queue via:

    current_producer = getattr(manager, "active_producer", None)
    current_queue = getattr(current_producer, "reader_socket_queue", None)

This works only if ``active_producer`` exposes ``reader_socket_queue``. In the
pre-retirement model, ``active_producer`` was a BPP instance that did.
Post-retirement, ``active_producer`` is ``self`` (CM) — and if CM does NOT
expose ``reader_socket_queue``, the factory never resolves a queue, never
picks up AIR's accepted UDS socket, and AIR's writes eventually EPIPE.

This was the root cause of the 2026-04-18 "HBO black screen" regression: AIR
spawned and wrote ~37KB into a kernel buffer, found no reader, and shut down
with ``SessionEnded(reason=stopped)``.

Invariant: while a producer is active, ``ChannelManager.reader_socket_queue``
MUST resolve to the same ``queue.Queue`` object held by the channel's active
``AirBridge``. This preserves the adapter's attribute-path call site
(``active_producer.reader_socket_queue``) without leaking AirBridge internals
into adapters.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
CM_PATH = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "channel_manager.py"


class TestChannelManagerExposesReaderSocketQueue:
    """ChannelManager class exposes ``reader_socket_queue`` by name."""

    def test_reader_socket_queue_is_defined_on_channel_manager(self) -> None:
        from retrovue.runtime.channel_manager import ChannelManager

        assert hasattr(ChannelManager, "reader_socket_queue"), (
            "ChannelManager MUST expose reader_socket_queue because the "
            "TsConsumptionAdapter factory (consumption_adapters.py) reads "
            "active_producer.reader_socket_queue, and post-ADR-004 Phase "
            "5C.2, active_producer is self (CM) — not a BlockPlanProducer. "
            "(INV-CM-READER-SOCKET-QUEUE-PROXY-001)"
        )

    def test_channel_manager_source_defines_reader_socket_queue(self) -> None:
        """Source-level AST check: reader_socket_queue is defined as a property
        or attribute on ChannelManager itself (not merely inherited)."""
        tree = ast.parse(CM_PATH.read_text())
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "ChannelManager":
                for child in ast.walk(node):
                    if isinstance(child, ast.FunctionDef) and child.name == "reader_socket_queue":
                        found = True
                        break
                    if isinstance(child, ast.Assign):
                        for t in child.targets:
                            if isinstance(t, ast.Attribute) and t.attr == "reader_socket_queue":
                                found = True
                                break
                break
        assert found, (
            "channel_manager.py MUST define reader_socket_queue on "
            "ChannelManager (property or attribute). "
            "(INV-CM-READER-SOCKET-QUEUE-PROXY-001)"
        )


class TestFactoryAttributePathUnchanged:
    """Contract snapshot: the adapter's attribute-path call site is unchanged.
    If this test fails, either the factory shape changed (and this invariant
    may need restatement) or the adapter was edited without coordinating."""

    def test_factory_reads_active_producer_reader_socket_queue(self) -> None:
        adapter = REPO_ROOT / "server" / "src" / "retrovue" / "runtime" / "consumption_adapters.py"
        text = adapter.read_text()
        assert 'getattr(current_producer, "reader_socket_queue"' in text, (
            "The TsConsumptionAdapter factory is expected to read the queue "
            "via current_producer.reader_socket_queue. If that shape changed, "
            "update or retire INV-CM-READER-SOCKET-QUEUE-PROXY-001."
        )
