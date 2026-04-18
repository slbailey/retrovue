"""
Consumption Adapter Model — Phase 8b

INV-SINGLE-ACTIVATION-PATH-001:
    ProgramDirector.start_channel() is the sole channel activation entry point.
    HLS and TS are consumption adapters that add consumption-model behavior
    (phantom, fanout) but do NOT own channel lifecycle.

INV-HLS-ACTIVITY-LOCK-ASYNC-SAFE-001:
    activate() is an async coroutine running on the uvicorn event loop.
    It MUST NOT acquire a threading.Lock directly — doing so blocks the
    event loop when a drain thread holds the lock, hanging all HTTP requests.
    The async check-and-reserve path uses asyncio.Lock (_hls_activity_alock).
    The sync drain path keeps threading.Lock (_hls_activity_lock).

HlsConsumptionAdapter owns:
    - Phantom session state (_hls_phantom_sessions, _hls_last_activity, _hls_activity_lock)
    - _activate_phantom(): starts/refreshes phantom viewer for a channel

TsConsumptionAdapter will own (Phase 8c):
    - Raw TS fanout wiring (_wire_fanout)
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time as _time
import uuid
from typing import TYPE_CHECKING, Any, Optional

from .clock import AuthoritativeClock

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

    def __init__(
        self,
        *,
        clock: AuthoritativeClock,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._clock = clock
        # Canonical phantom state — owned here, not in ProgramDirector.
        self._hls_phantom_sessions: dict[str, str] = {}  # channel_id -> phantom_id
        self._hls_last_activity: dict[str, float] = {}   # channel_id -> monotonic timestamp
        # INV-HLS-ACTIVITY-LOCK-ASYNC-SAFE-001:
        # Two locks guard the same phantom state dict for different callers:
        #   _hls_activity_lock   — threading.Lock for sync paths (phantom drain
        #                          thread, touch_activity, is_phantom_active).
        #   _hls_activity_alock  — asyncio.Lock for async paths (activate()).
        # The async path MUST NOT acquire a threading.Lock directly on the
        # event loop thread; doing so blocks the loop when a drain thread
        # holds the lock, causing HTTP request hangs.
        self._hls_activity_lock = threading.Lock()
        self._hls_activity_alock: "asyncio.Lock | None" = None  # lazy-init on first await

    # ------------------------------------------------------------------
    # Public interface used by ProgramDirector
    # ------------------------------------------------------------------

    def touch_activity(self, channel_id: str) -> None:
        """Record that an HLS client is still active for this channel.

        Called on every successful manifest/segment serve. Resets the idle
        timeout so the phantom drain thread does not disconnect prematurely.
        """
        with self._hls_activity_lock:
            self._hls_last_activity[channel_id] = self._clock.monotonic()

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
        pd: "Any",
    ) -> None:
        """Subscribe a phantom viewer to the fanout and start its drain thread.

        Called by ProgramDirector._ensure_channel_active_for_hls() after the
        channel is active and a fanout buffer is established.

        Phase 8 Step 6: the drain thread is a *detector only*. When it
        observes an idle/teardown condition it emits
        ``pd._on_phantom_idle(channel_id, phantom_id, reason)`` instead of
        mutating ChannelManager lifecycle directly. Fanout-subscription
        and adapter-internal phantom bookkeeping remain the adapter's
        responsibility; those are not lifecycle state.

        Args:
            channel_id: Channel being activated.
            phantom_id: Unique phantom session id (already registered in _hls_phantom_sessions).
            mgr: ChannelManager for this channel (used read-only by this
                method — looked up for LINGER_SECONDS-equivalent idle
                timeout; lifecycle mutation is PD's job).
            fanout: ChannelStream fanout (already running).
            pd: ProgramDirector; receives `_on_phantom_idle` events.
        """
        phantom_queue = fanout.subscribe(phantom_id)

        def _drain_hls_v2_phantom() -> None:
            IDLE_CHECK_INTERVAL = 5.0
            # Historical: the adapter read LINGER_SECONDS off the manager
            # for its idle timeout. Phase 8 Step 4 removed LINGER_SECONDS
            # from CM and Step 5 left the adapter with no direct source
            # for it, so we fall back to the same default (20s) that the
            # manager had previously been configured with. Policy belongs
            # to PD now; the adapter just picks a detection threshold.
            idle_timeout = 20
            # INV-HLS-PHANTOM-BYTE-FLOW-LIVENESS-001:
            # If no bytes flow through the phantom queue for > BYTE_FLOW_TIMEOUT_S,
            # the upstream ChannelStream has stopped. Exit the drain loop so
            # PD's phantom-idle handler fires and viewer_count drops —
            # allowing clean teardown and re-activation on next manifest request.
            BYTE_FLOW_TIMEOUT_S = 30.0
            last_got_data = self._clock.monotonic()
            self._logger.info(
                "[HLS-v2-phantom %s] started, idle_timeout=%ds, byte_flow_timeout=%.0fs",
                channel_id, idle_timeout, BYTE_FLOW_TIMEOUT_S,
            )
            exit_reason = "idle_timeout"
            while True:
                _time.sleep(IDLE_CHECK_INTERVAL)

                # Check fanout liveness directly (fastest path)
                if not fanout.is_running():
                    self._logger.warning(
                        "INV-HLS-PHANTOM-BYTE-FLOW-LIVENESS-001: "
                        "[HLS-v2-phantom %s] fanout is no longer running, exiting drain loop",
                        channel_id,
                    )
                    exit_reason = "fanout_dead"
                    break

                # Pull one chunk to confirm bytes are flowing (non-blocking)
                try:
                    chunk = phantom_queue.get(timeout=0.01)
                    if not chunk:
                        exit_reason = "eof"
                        break  # EOF
                    # Got real data — reset byte-flow liveness clock
                    last_got_data = self._clock.monotonic()
                except Exception:
                    pass  # queue empty or timeout — normal between segments

                # INV-HLS-PHANTOM-BYTE-FLOW-LIVENESS-001: byte-flow dead check
                byte_flow_dead_s = self._clock.monotonic() - last_got_data
                if byte_flow_dead_s > BYTE_FLOW_TIMEOUT_S:
                    self._logger.warning(
                        "INV-HLS-PHANTOM-BYTE-FLOW-LIVENESS-001: "
                        "[HLS-v2-phantom %s] no bytes for %.0fs (threshold=%.0fs), "
                        "pipeline dead — exiting drain loop",
                        channel_id, byte_flow_dead_s, BYTE_FLOW_TIMEOUT_S,
                    )
                    exit_reason = "byte_flow_dead"
                    break

                # Check if any HLS client is still active
                with self._hls_activity_lock:
                    last = self._hls_last_activity.get(channel_id, 0)
                idle_seconds = self._clock.monotonic() - last
                if idle_seconds > idle_timeout:
                    self._logger.info(
                        "[HLS-v2-phantom %s] no client activity for %.0fs, disconnecting",
                        channel_id, idle_seconds,
                    )
                    exit_reason = "idle_timeout"
                    break

            # Phase 8 Step 6: ask PD to handle lifecycle. PD decides
            # whether / how the phantom's viewer_leave should flow and
            # whether linger/teardown should be scheduled.
            self._logger.info(
                "[HLS-v2-phantom %s] tearing down phantom viewer %s reason=%s",
                channel_id, phantom_id, exit_reason,
            )
            try:
                pd._on_phantom_idle(channel_id, phantom_id, exit_reason)
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "[HLS-v2-phantom %s] pd._on_phantom_idle raised: %s",
                    channel_id, exc,
                )
            # Adapter-internal cleanup: drop the fanout subscription
            # (reader-queue bookkeeping, not lifecycle) and clear the
            # phantom-session registry on the adapter.
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
        self._hls_last_activity[channel_id] = self._clock.monotonic()
        return phantom_id

    def release_phantom_slot(self, channel_id: str) -> None:
        """Release a previously reserved phantom slot (on startup failure)."""
        with self._hls_activity_lock:
            self._hls_phantom_sessions.pop(channel_id, None)
            self._hls_last_activity.pop(channel_id, None)

    @property
    def activity_lock(self) -> threading.Lock:
        """Expose the threading lock for sync callers (drain thread, touch_activity)."""
        return self._hls_activity_lock

    def _get_activity_alock(self) -> "asyncio.Lock":
        """Return the asyncio.Lock for async callers (activate()).

        INV-HLS-ACTIVITY-LOCK-ASYNC-SAFE-001: Must only be called from the
        event loop thread.  Lazy-init so construction (which may happen off
        the loop) does not create a lock bound to the wrong loop.
        """
        import asyncio
        if self._hls_activity_alock is None:
            self._hls_activity_alock = asyncio.Lock()
        return self._hls_activity_alock

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
        self._logger.debug(
            "[HLS] PHANTOM_ACTIVATE sid=%s channel=%s",
            session_id, channel_id,
        )

        # INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001: Exactly one phantom
        # per channel. Serialized by _hls_activity_alock (asyncio.Lock) so
        # this coroutine never blocks the event loop on a threading.Lock.
        # INV-HLS-ACTIVITY-LOCK-ASYNC-SAFE-001: async path uses asyncio.Lock.
        async with self._get_activity_alock():
            if channel_id in self._hls_phantom_sessions:
                # Phantom already active — just refresh activity and return
                self.touch_activity(channel_id)
                return pd._resolve_channel_manager(channel_id)
            # Reserve the slot immediately so concurrent requests see it.
            # reserve_phantom_slot uses threading.Lock internally — safe here
            # because we're inside the asyncio.Lock which serialises async
            # callers, and the threading.Lock acquisition is instantaneous
            # (no contention from drain thread at this point: drain only holds
            # threading.Lock briefly at cleanup, not here).
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

            # INV-EARLY-DRAIN: pre-wire the fanout BEFORE tune_in kicks off
            # launch_air. AIR begins writing MPEG-TS the instant AttachStream
            # returns; if no reader is attached before then, AIR's SocketSink
            # buffer fills during the AttachStream→SwitchToLive lead window
            # (~6s) and trips POLLHUP, killing the output path. Starting the
            # fanout here — whose upstream reader patiently polls the
            # still-unwritten reader_socket_queue — guarantees continuous
            # drain from the first AIR write onward.
            from retrovue.runtime.channel_stream import ChannelStream, SocketTsSource

            _hls_seg = getattr(mgr, "hls_segmenter", None)
            _factory_clock = self._clock

            def _hls_ts_source_factory(stop_event=None, _mgr=mgr, _cid=channel_id):
                # INV-CHANNEL-STREAM-RECONNECT-001: resolve the *current*
                # producer's queue at call time so reconnect after AIR
                # restart picks up the new producer's socket — not the
                # stale socket captured at HLS activation time.
                # INV-EARLY-DRAIN: when pre-wired, the producer may not yet
                # exist; the reader loop's backoff retries this factory
                # until the producer's queue materialises.
                import queue as _q
                _deadline_s = 30.0  # covers launch_air's ~6s lead time
                _t_start = _factory_clock.monotonic()
                while _factory_clock.monotonic() - _t_start < _deadline_s:
                    if stop_event is not None and stop_event.is_set():
                        raise RuntimeError(
                            "Factory cancelled (shutdown) for %s" % _cid
                        )
                    _producer = getattr(_mgr, "active_producer", None)
                    _rq = (
                        getattr(_producer, "reader_socket_queue", None)
                        if _producer else None
                    )
                    if _rq is not None:
                        try:
                            sock = _rq.get(timeout=0.1)
                            adapter._logger.info(
                                "[HLS %s] Socket acquired from queue in %.0fms",
                                _cid,
                                (_factory_clock.monotonic() - _t_start) * 1000,
                            )
                            return SocketTsSource(sock)
                        except _q.Empty:
                            continue
                    # Producer or queue not yet present — short sleep then retry.
                    if stop_event is not None and stop_event.wait(timeout=0.1):
                        raise RuntimeError(
                            "Factory cancelled (shutdown) for %s" % _cid
                        )
                raise RuntimeError(
                    "No reader_socket_queue for %s within %.0fs" % (_cid, _deadline_s)
                )

            try:
                fanout = ChannelStream(
                    channel_id=channel_id,
                    ts_source_factory=_hls_ts_source_factory,
                    hls_segmenter=_hls_seg,
                    clock=self._clock,
                )
                # Phase 9 Step 4: PD is the sole writer of its fanout
                # registry. Route through the public command surface.
                pd.register_fanout_buffer(channel_id, fanout)
                # INV-EARLY-DRAIN: start the reader NOW so it is draining
                # bytes from the UDS the instant AIR connects.
                fanout.start()
            except Exception as exc:
                adapter._logger.warning(
                    "[HLS %s] pre-wire fanout creation failed: %s", channel_id, exc,
                )

            # Kick off the producer lifecycle — launch_air runs inside this
            # call. The pre-wired fanout above is already polling the queue,
            # so AIR's first writes are drained without buffer overflow.
            mgr.tune_in(phantom_id, {"channel_id": channel_id, "hls": True})

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

        # Wait for fanout to establish so bytes start flowing to the segmenter.
        # INV-HLS-ACTIVITY-LOCK-ASYNC-SAFE-001: _get_or_create_fanout_buffer
        # acquires _fanout_lock (threading.Lock). Run it in an executor so
        # the event loop thread is never blocked by lock contention.
        fanout = None
        for _ in range(10):
            fanout = await loop.run_in_executor(
                None, pd._get_or_create_fanout_buffer, channel_id, mgr
            )
            if fanout and fanout.is_running():
                break
            await asyncio.sleep(1)

        if fanout is None:
            # Phase 8 Step 6: startup failed — ask PD to back out the
            # phantom's tune_in via the same event path the drain thread
            # uses. The adapter does not touch CM lifecycle directly.
            adapter._logger.warning(
                "[HLS-v2 %s] activation failed (no fanout), cleaning up phantom %s",
                channel_id, phantom_id,
            )
            try:
                pd._on_phantom_idle(channel_id, phantom_id, "fanout_unavailable")
            except Exception as exc:  # noqa: BLE001
                adapter._logger.warning(
                    "[HLS-v2 %s] pd._on_phantom_idle raised on activation "
                    "cleanup: %s", channel_id, exc,
                )
            self.release_phantom_slot(channel_id)
            return None

        # Subscribe phantom to fanout and start drain thread.
        self._activate_phantom(channel_id, phantom_id, mgr, fanout, pd)
        return mgr

class TsConsumptionAdapter:
    """Owns raw TS fanout wiring.

    INV-SINGLE-ACTIVATION-PATH-001: TS viewers activate channels through
    PD.start_channel() — this adapter adds TS-specific fanout wiring
    but does not own channel lifecycle.

    Phase 8c: _wire_fanout() extracted from ProgramDirector._get_or_create_fanout_buffer().
    PD retains ownership of the fanout registry (lifecycle), but the ChannelStream
    construction logic lives here. PD calls _wire_fanout() for the actual creation.
    """

    def __init__(
        self,
        *,
        clock: AuthoritativeClock,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._clock = clock

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
        fanout is present. PD manages the fanout registry (add/remove entries);
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
        from retrovue.runtime.channel_stream import ChannelStream, SocketTsSource

        # Test mode: no real producer, use FakeTsSource from test fixtures
        if test_mode and manager is None:
            from tests.fixtures.channel_stream_fixtures import FakeTsSource
            def ts_source_factory(_stop_event=None) -> FakeTsSource:
                return FakeTsSource()
            return ChannelStream(
                channel_id=channel_id,
                ts_source_factory=ts_source_factory,
                clock=self._clock,
            )

        # Producer may be None at wire-time — we pre-wire the fanout so its
        # upstream reader is already draining the UDS by the time AIR's
        # AttachStream lands a socket in the queue (see INV-EARLY-DRAIN below).
        # The manager-driven factory re-resolves producer.reader_socket_queue
        # at each call, so it tolerates "no producer yet" and "producer
        # restarted" uniformly. We only fall through to the legacy
        # socket_path path when the caller explicitly supplies a
        # channel_stream_factory and the manager has no active_producer at all.
        producer = getattr(manager, "active_producer", None)
        reader_queue = (
            getattr(producer, "reader_socket_queue", None) if producer else None
        )

        # INV-EARLY-DRAIN: always use the manager-driven reader_socket_queue
        # factory unless we are on the legacy socket_path code path.
        use_queue_factory = reader_queue is not None or producer is None
        if use_queue_factory:
            self._logger.info(
                "TsConsumptionAdapter: using reader_socket_queue for channel %s", channel_id,
            )

            _factory_clock = self._clock

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
                    deadline = _factory_clock.monotonic() + 2.0
                    while _factory_clock.monotonic() < deadline:
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
            return ChannelStream(
                channel_id=channel_id,
                ts_source_factory=ts_source_factory,
                hls_segmenter=_hls_seg,
                clock=self._clock,
            )

        # Fallback: Producer exposes only socket_path (legacy/test); connect as client.
        socket_path = getattr(producer, "socket_path", None)
        if not socket_path:
            return None

        if channel_stream_factory:
            return channel_stream_factory(channel_id, str(socket_path))

        _hls_seg = getattr(manager, "hls_segmenter", None)
        return ChannelStream(
            channel_id=channel_id,
            socket_path=socket_path,
            hls_segmenter=_hls_seg,
            clock=self._clock,
        )
