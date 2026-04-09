"""
Source watch workflow.

Owns the observer lifecycle, debounce timer, and re-ingest orchestration
for `retrovue source watch`. The CLI command delegates here per
INV-WATCH-DELEGATES-001.

This module MUST NOT read from stdin or write to stdout. All IO stays
in the CLI command wrapper.
"""

from __future__ import annotations

import signal
import threading
from pathlib import Path
from typing import Callable

import structlog
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = structlog.get_logger(__name__)


class SourceWatchService:
    """Debounced file-change watcher that triggers re-ingest on expiry.

    Accepts an ``ingest_fn`` callable (no args) that is invoked when the
    debounce timer expires. The service owns the timer lifecycle and
    error recovery — ingest failures are logged and swallowed so watch
    mode keeps running.

    This class does NOT own the ``watchdog.Observer``; the observer is
    managed separately by ``run_watch()`` which wires filesystem events
    into ``notify_change()``.
    """

    def __init__(
        self,
        ingest_fn: Callable[[], object],
        debounce_sec: float = 5.0,
    ) -> None:
        if debounce_sec < 1.0:
            raise ValueError(
                f"Debounce interval must be >= 1 second, got {debounce_sec}"
            )
        self._ingest_fn = ingest_fn
        self._debounce_sec = debounce_sec
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._stopped = False

    def notify_change(self) -> None:
        """Record a file change and reset the debounce timer."""
        with self._lock:
            if self._stopped:
                return
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_sec, self._on_debounce_expire)
            self._timer.daemon = True
            self._timer.start()

    def _on_debounce_expire(self) -> None:
        """Called when debounce timer expires — trigger re-ingest."""
        try:
            self._ingest_fn()
        except Exception:
            logger.exception("reingest_failed")

    def stop(self) -> None:
        """Cancel any pending timer and mark stopped."""
        with self._lock:
            self._stopped = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


class _ChangeHandler(FileSystemEventHandler):
    """Feeds filesystem events into SourceWatchService.notify_change()."""

    def __init__(self, service: SourceWatchService, source_id: str) -> None:
        self._service = service
        self._source_id = source_id

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        logger.debug(
            "file_change_detected",
            source_id=self._source_id,
            event_type=event.event_type,
            path=str(event.src_path),
        )
        self._service.notify_change()


def make_source_ingest_fn(db: object, source: object) -> Callable[[], object]:
    """Build an ingest callable for use with SourceWatchService.

    Encapsulates SourceIngestService construction so the CLI does not
    need to import it directly (INV-WATCH-DELEGATES-001).
    """
    from .source_ingest import SourceIngestService

    def _do_ingest() -> object:
        svc = SourceIngestService(db)  # type: ignore[arg-type]
        return svc.ingest_source(source)  # type: ignore[arg-type]

    return _do_ingest


def run_watch(
    source_id: str,
    source_name: str,
    watch_paths: list[Path],
    ingest_fn: Callable[[], object],
    debounce_sec: float = 5.0,
) -> None:
    """Run watch mode until SIGINT/SIGTERM.

    This is the workflow entry point called by the CLI. It:
    1. Creates a SourceWatchService with the given ingest callable.
    2. Starts a watchdog Observer on all watch_paths.
    3. Blocks until a shutdown signal is received.
    4. Cleans up observer and service.
    """
    service = SourceWatchService(ingest_fn=ingest_fn, debounce_sec=debounce_sec)
    handler = _ChangeHandler(service, source_id)
    observer = Observer()

    for wp in watch_paths:
        observer.schedule(handler, str(wp), recursive=True)

    stop_event = threading.Event()

    def _shutdown(signum: int, frame: object) -> None:
        logger.info(
            "watch_stopped",
            source_id=source_id,
            reason=f"signal {signum}",
        )
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info(
        "watch_started",
        source_id=source_id,
        source_name=source_name,
        watch_paths=[str(p) for p in watch_paths],
        debounce_sec=debounce_sec,
    )

    observer.start()
    try:
        stop_event.wait()
    finally:
        service.stop()
        observer.stop()
        observer.join(timeout=5)
