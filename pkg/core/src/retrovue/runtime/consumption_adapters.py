"""
Consumption Adapter Model — Phase 8b

INV-SINGLE-ACTIVATION-PATH-001:
    ProgramDirector.start_channel() is the sole channel activation entry point.
    HLS and TS are consumption adapters that add consumption-model behavior
    (phantom, fanout) but do NOT own channel lifecycle.

HlsConsumptionAdapter owns:
    - Phantom session state (_hls_phantom_sessions, _hls_last_activity, _hls_activity_lock)
    - _activate_phantom(): starts/refreshes phantom viewer for a channel

TsConsumptionAdapter will own (Phase 8c):
    - Raw TS fanout wiring (_wire_fanout)
"""
from __future__ import annotations

import logging
import threading
import time as _time
import uuid
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass


class HlsConsumptionAdapter:
    """Owns HLS phantom session lifecycle.

    INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001: Maintains exactly one
    phantom viewer per channel while HLS clients are actively polling.
    The phantom subscriber keeps the ChannelStream fanout alive between
    client segment requests.

    This adapter holds the canonical state for phantom sessions. ProgramDirector
    must not maintain inline _hls_phantom_sessions or _hls_last_activity state.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)
        # Canonical phantom state — owned here, not in ProgramDirector.
        self._hls_phantom_sessions: dict[str, str] = {}  # channel_id -> phantom_id
        self._hls_last_activity: dict[str, float] = {}   # channel_id -> monotonic timestamp
        self._hls_activity_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface used by ProgramDirector
    # ------------------------------------------------------------------

    def touch_activity(self, channel_id: str) -> None:
        """Record that an HLS client is still active for this channel.

        Called on every successful manifest/segment serve. Resets the idle
        timeout so the phantom drain thread does not disconnect prematurely.
        """
        with self._hls_activity_lock:
            self._hls_last_activity[channel_id] = _time.monotonic()

    def is_phantom_active(self, channel_id: str) -> bool:
        """Return True if a phantom viewer is already subscribed for this channel."""
        with self._hls_activity_lock:
            return channel_id in self._hls_phantom_sessions

    def _activate_phantom(
        self,
        channel_id: str,
        phantom_id: str,
        mgr: Any,
        fanout: Any,
    ) -> None:
        """Subscribe a phantom viewer to the fanout and start its drain thread.

        Called by ProgramDirector._ensure_channel_active_for_hls() after the
        channel is active and a fanout buffer is established.

        Args:
            channel_id: Channel being activated.
            phantom_id: Unique phantom session id (already registered in _hls_phantom_sessions).
            mgr: ChannelManager for this channel (needed for tune_out + LINGER_SECONDS).
            fanout: ChannelStream fanout (already running).
        """
        phantom_queue = fanout.subscribe(phantom_id)

        def _drain_hls_v2_phantom() -> None:
            IDLE_CHECK_INTERVAL = 5.0
            idle_timeout = getattr(mgr, "LINGER_SECONDS", 20)
            self._logger.info(
                "[HLS-v2-phantom %s] started, idle_timeout=%ds", channel_id, idle_timeout,
            )
            while True:
                _time.sleep(IDLE_CHECK_INTERVAL)

                # Pull one chunk to confirm stream is alive (non-blocking)
                try:
                    chunk = phantom_queue.get(timeout=0.01)
                    if not chunk:
                        break  # EOF
                except Exception:
                    pass  # queue empty or timeout — stream may be starting

                # Check if any HLS client is still active
                with self._hls_activity_lock:
                    last = self._hls_last_activity.get(channel_id, 0)
                idle_seconds = _time.monotonic() - last
                if idle_seconds > idle_timeout:
                    self._logger.info(
                        "[HLS-v2-phantom %s] no client activity for %.0fs, disconnecting",
                        channel_id, idle_seconds,
                    )
                    break

            # Cleanup
            self._logger.info(
                "[HLS-v2-phantom %s] tearing down phantom viewer %s", channel_id, phantom_id,
            )
            try:
                mgr.tune_out(phantom_id)
            except Exception:
                pass
            try:
                fanout.unsubscribe(phantom_id)
            except Exception:
                pass
            with self._hls_activity_lock:
                self._hls_phantom_sessions.pop(channel_id, None)
                self._hls_last_activity.pop(channel_id, None)

        threading.Thread(
            target=_drain_hls_v2_phantom,
            daemon=True,
            name=f"hls-v2-phantom-{channel_id}",
        ).start()

    def reserve_phantom_slot(self, channel_id: str) -> str:
        """Atomically reserve a phantom slot for this channel.

        Returns the phantom_id to use. Caller must call release_phantom_slot()
        on failure, or activate_phantom() on success.

        Must be called with _hls_activity_lock held (via with_lock_reserve).
        """
        phantom_id = f"hls-v2-phantom-{channel_id}-{uuid.uuid4().hex[:8]}"
        self._hls_phantom_sessions[channel_id] = phantom_id
        self._hls_last_activity[channel_id] = _time.monotonic()
        return phantom_id

    def release_phantom_slot(self, channel_id: str) -> None:
        """Release a previously reserved phantom slot (on startup failure)."""
        with self._hls_activity_lock:
            self._hls_phantom_sessions.pop(channel_id, None)
            self._hls_last_activity.pop(channel_id, None)

    @property
    def activity_lock(self) -> threading.Lock:
        """Expose the activity lock for ProgramDirector's atomic check-and-reserve."""
        return self._hls_activity_lock

    def get_last_activity(self, channel_id: str) -> float:
        """Return last activity timestamp for a channel (0.0 if never touched)."""
        with self._hls_activity_lock:
            return self._hls_last_activity.get(channel_id, 0)



    async def activate(self, channel_id: str, session_id: str, pd: "Any") -> "Any | None":
        """Activate a channel for HLS consumption.

        INV-SINGLE-ACTIVATION-PATH-001: Routes channel lifecycle through
        PD.start_channel() (the sole lifecycle entry point). This adapter
        adds HLS-specific phantom session behavior but does NOT own lifecycle.

        Moved from PD._ensure_channel_active_for_hls() in Phase 8d.

        Args:
            channel_id: Channel to activate.
            session_id: HLS session id for phantom viewer.
            pd: ProgramDirector instance (provides lifecycle + fanout APIs).

        Returns:
            ChannelManager on success, None on failure.
        """
        import asyncio

        # INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001: Exactly one phantom
        # per channel. Serialized by activity_lock.
        with self.activity_lock:
            if self.is_phantom_active(channel_id):
                # Phantom already active — just refresh activity and return
                self.touch_activity(channel_id)
                return pd._resolve_channel_manager(channel_id)
            # Reserve the slot immediately so concurrent requests see it
            phantom_id = self.reserve_phantom_slot(channel_id)

        loop = asyncio.get_running_loop()
        adapter = self

        def _startup() -> "Any | None":
            # INV-SINGLE-ACTIVATION-PATH-001: Use start_channel() — the sole
            # lifecycle entry point — not a parallel _resolve_or_create path.
            try:
                mgr = pd.start_channel(channel_id)
            except Exception:
                return None
            if mgr is None:
                return None

            mgr.tune_in(phantom_id, {"channel_id": channel_id, "hls": True})

            # AIR immediately writes to the UDS socket after startup.
            # If nobody reads within ~200ms, SocketSink overflows → detach
            # → session ends (reason=stopped) → crash-loop.
            # Fix: grab the accepted socket from the queue and construct
            # the ChannelStream directly with it (via SocketTsSource),
            # bypassing the slow factory retry loop.
            import time as _t
            from retrovue.runtime.channel_stream import ChannelStream, SocketTsSource

            producer = getattr(mgr, "active_producer", None)
            reader_queue = getattr(producer, "reader_socket_queue", None) if producer else None

            if reader_queue is not None:
                try:
                    t0 = _t.monotonic()
                    sock = reader_queue.get(timeout=5.0)
                    adapter._logger.info(
                        "[HLS %s] Socket acquired from queue in %.0fms",
                        channel_id, (_t.monotonic() - t0) * 1000,
                    )
                    _hls_seg = getattr(mgr, "hls_segmenter", None)
                    fanout = ChannelStream(
                        channel_id=channel_id,
                        ts_source_factory=lambda stop_event=None, s=sock: SocketTsSource(s),
                        hls_segmenter=_hls_seg,
                    )
                    pd._fanout_buffers[channel_id] = fanout
                except Exception as exc:
                    adapter._logger.warning(
                        "[HLS %s] direct fanout creation failed: %s", channel_id, exc,
                    )

            return mgr

        # INV-CHANNEL-STARTUP-CONCURRENCY-001: Acquire startup semaphore
        await pd._startup_semaphore.acquire()
        try:
            mgr = await loop.run_in_executor(pd._startup_executor, _startup)
        except Exception as exc:
            adapter._logger.warning(
                "HLS activation failed for channel %s: %s", channel_id, exc,
            )
            mgr = None
        finally:
            pd._startup_semaphore.release()

        if mgr is None:
            # Startup failed — clean up the reserved slot
            self.release_phantom_slot(channel_id)
            return None

        # Wait for fanout to establish so bytes start flowing to the segmenter
        fanout = None
        for _ in range(10):
            fanout = pd._get_or_create_fanout_buffer(channel_id, mgr)
            if fanout and fanout.is_running():
                break
            await asyncio.sleep(1)

        if fanout is None:
            # Startup failed — clean up phantom
            adapter._logger.warning(
                "[HLS-v2 %s] activation failed (no fanout), cleaning up phantom %s",
                channel_id, phantom_id,
            )
            try:
                mgr.tune_out(phantom_id)
            except Exception:
                pass
            self.release_phantom_slot(channel_id)
            return None

        # Subscribe phantom to fanout and start drain thread.
        self._activate_phantom(channel_id, phantom_id, mgr, fanout)
        return mgr

class TsConsumptionAdapter:
    """Owns raw TS fanout wiring.

    INV-SINGLE-ACTIVATION-PATH-001: TS viewers activate channels through
    PD.start_channel() — this adapter adds TS-specific fanout wiring
    but does not own channel lifecycle.

    Phase 8c: _wire_fanout() extracted from ProgramDirector._get_or_create_fanout_buffer().
    PD retains ownership of the _fanout_buffers dict (lifecycle), but the ChannelStream
    construction logic lives here. PD calls _wire_fanout() for the actual creation.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def _wire_fanout(
        self,
        channel_id: str,
        manager: Any,
        *,
        test_mode: bool = False,
        channel_stream_factory: Any = None,
    ) -> Any:
        """Construct and return a new ChannelStream for this channel.

        Called by ProgramDirector._get_or_create_fanout_buffer() when no existing
        fanout is present. PD manages the _fanout_buffers dict (add/remove entries);
        this method owns only the ChannelStream construction logic.

        Args:
            channel_id: Channel identifier.
            manager: ChannelManager for this channel (provides active_producer,
                     reader_socket_queue, hls_segmenter).
            test_mode: If True, construct a FakeTsSource-backed stream (no real AIR).
            channel_stream_factory: Optional factory callable(channel_id, socket_path)
                                    -> ChannelStream used in tests.

        Returns:
            A new ChannelStream instance, or None if the producer is not ready.
        """
        import queue as _queue
        import time as _time
        from retrovue.runtime.channel_stream import ChannelStream, FakeTsSource, SocketTsSource

        # Test mode: no real producer, use FakeTsSource
        if test_mode and manager is None:
            def ts_source_factory(_stop_event=None) -> FakeTsSource:
                return FakeTsSource()
            return ChannelStream(channel_id=channel_id, ts_source_factory=ts_source_factory)

        # Check for real producer
        producer = getattr(manager, "active_producer", None)
        if not producer:
            return None

        # AIR UDS socket path: use reader_socket_queue (server mode)
        reader_queue = getattr(producer, "reader_socket_queue", None)
        if reader_queue is not None:
            self._logger.info(
                "TsConsumptionAdapter: using reader_socket_queue for channel %s", channel_id,
            )

            def ts_source_factory(stop_event=None) -> Any:
                # INV-CHANNEL-STREAM-RECONNECT-001: Resolve the *current*
                # producer's queue at call time so reconnect after AIR
                # restart picks up the new producer's socket.
                #
                # INV-CHANNEL-STREAM-SHUTDOWN-001: stop_event is passed by
                # ChannelStream._create_ts_source so that all blocking waits
                # here can be interrupted within the 5s stop() deadline.
                import time as _t
                for attempt in range(6):
                    if stop_event is not None and stop_event.is_set():
                        raise RuntimeError(
                            "Factory cancelled (shutdown) for %s" % channel_id
                        )
                    current_producer = getattr(manager, "active_producer", None)
                    if current_producer is None:
                        self._logger.debug(
                            "Factory: no active_producer for %s (attempt %d/6)",
                            channel_id, attempt + 1,
                        )
                        if stop_event is not None:
                            if stop_event.wait(timeout=2.0):
                                raise RuntimeError(
                                    "Factory cancelled (shutdown) for %s" % channel_id
                                )
                        else:
                            _t.sleep(2.0)
                        continue
                    current_queue = getattr(current_producer, "reader_socket_queue", None)
                    if current_queue is None:
                        self._logger.debug(
                            "Factory: no reader_socket_queue for %s (attempt %d/6)",
                            channel_id, attempt + 1,
                        )
                        if stop_event is not None:
                            if stop_event.wait(timeout=2.0):
                                raise RuntimeError(
                                    "Factory cancelled (shutdown) for %s" % channel_id
                                )
                        else:
                            _t.sleep(2.0)
                        continue
                    # Poll the queue in short bursts so stop_event can interrupt.
                    deadline = _t.monotonic() + 2.0
                    while _t.monotonic() < deadline:
                        if stop_event is not None and stop_event.is_set():
                            raise RuntimeError(
                                "Factory cancelled (shutdown) for %s" % channel_id
                            )
                        try:
                            sock = current_queue.get(timeout=0.1)
                            self._logger.info(
                                "Got socket from queue for channel %s", channel_id,
                            )
                            return SocketTsSource(sock)
                        except _queue.Empty:
                            pass
                    self._logger.debug(
                        "Reader queue empty for channel %s (attempt %d/6)",
                        channel_id, attempt + 1,
                    )
                raise RuntimeError(
                    "Timed out waiting for socket from reader_socket_queue for %s"
                    % channel_id
                )

            _hls_seg = getattr(manager, "hls_segmenter", None)
            return ChannelStream(channel_id=channel_id, ts_source_factory=ts_source_factory, hls_segmenter=_hls_seg)

        # Fallback: Producer exposes only socket_path (legacy/test); connect as client.
        socket_path = getattr(producer, "socket_path", None)
        if not socket_path:
            return None

        if channel_stream_factory:
            return channel_stream_factory(channel_id, str(socket_path))

        _hls_seg = getattr(manager, "hls_segmenter", None)
        return ChannelStream(channel_id=channel_id, socket_path=socket_path, hls_segmenter=_hls_seg)
