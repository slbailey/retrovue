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


class TsConsumptionAdapter:
    """Owns raw TS fanout wiring (Phase 8c stub).

    INV-SINGLE-ACTIVATION-PATH-001: TS viewers activate channels through
    PD.start_channel() — this adapter adds TS-specific fanout wiring
    but does not own channel lifecycle.

    Phase 8c will extract _wire_fanout() from ProgramDirector here.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    # Phase 8c: _wire_fanout(channel_id, mgr) will be added here.
