"""
CUN Synthesis Worker: claim, render, cache Coming Up Next segments.

This worker claims pending CUN render requests from the queue, renders them
using ffmpeg (drawtext on looped background), and caches the output as
content-addressed .mp4 files.

Pipeline: schedule-scoped synthesis (INV-CUN-SCHEDULE-SCOPED-001).
Not an ingest enricher. Not a ProcessorJob.

Invariants enforced:
- INV-CUN-RENDER-DEADLINE-001: skip if past deadline
- INV-CUN-DEDUP-BEFORE-RENDER-001: reuse existing completed render
- INV-CUN-PRIORITY-PLAYOUT-001: soonest playout first (via claim_next)
- INV-CUN-CACHE-DEDUP-001: content-addressed cache by hash(template_id, title)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

from ..infra.uow import session
from .cun_queue import (
    claim_next,
    complete,
    content_hash_for,
    fail,
    find_completed_by_hash,
    skip,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CunTemplateConfig:
    """Template configuration for CUN rendering.

    Resolved from channel YAML continuity.coming_up_next.templates[].
    """

    id: str
    background: str  # path to looping background video
    text_area_x: int
    text_area_y: int
    text_area_width: int
    text_area_height: int
    font: str  # path to font file
    font_size: int
    font_color: str
    fade_in_ms: int
    fade_out_ms: int


def _build_ffmpeg_cmd(
    template: CunTemplateConfig,
    title: str,
    duration_ms: int,
    output_path: str,
) -> list[str]:
    """Build ffmpeg command for CUN segment rendering.

    Loops the background video, overlays title text using drawtext filter,
    and outputs a fixed-duration .mp4.
    """
    duration_s = duration_ms / 1000.0
    fade_in_s = template.fade_in_ms / 1000.0
    fade_out_s = template.fade_out_ms / 1000.0
    fade_out_start = max(0, duration_s - fade_out_s)

    # Escape drawtext special characters
    escaped_title = title.replace("'", "\\'").replace(":", "\\:")

    drawtext_filter = (
        f"drawtext="
        f"text='{escaped_title}':"
        f"fontfile='{template.font}':"
        f"fontsize={template.font_size}:"
        f"fontcolor={template.font_color}:"
        f"x={template.text_area_x}:"
        f"y={template.text_area_y}:"
        f"alpha='if(lt(t,{fade_in_s}),t/{fade_in_s},"
        f"if(gt(t,{fade_out_start}),(1-(t-{fade_out_start})/{fade_out_s}),1))'"
    )

    return [
        "ffmpeg",
        "-y",
        "-stream_loop", "-1",
        "-i", template.background,
        "-vf", drawtext_filter,
        "-t", f"{duration_s:.3f}",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]


def _render_ffmpeg(cmd: list[str]) -> None:
    """Execute ffmpeg command. Raises on non-zero exit."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exited {result.returncode}: {result.stderr[-500:]}"
        )


def run_once(
    cache_dir: str,
    template_resolver: callable,
    duration_ms: int = 10_000,
    deadline_margin_ms: int = 30_000,
    render_fn: callable = _render_ffmpeg,
) -> bool:
    """Claim one pending CUN request, render it, cache the output.

    Args:
        cache_dir: Directory for content-addressed cache files.
        template_resolver: Callable(channel_id, template_id) -> CunTemplateConfig.
            Resolves template config from channel YAML. Provided by caller
            so the worker stays decoupled from config loading.
        duration_ms: CUN segment duration in milliseconds.
        deadline_margin_ms: Safety margin before segment_start_utc.
            INV-CUN-RENDER-DEADLINE-001.
        render_fn: Callable that executes the ffmpeg command list.
            Default is _render_ffmpeg; injectable for testing.

    Returns:
        True if a request was processed (completed, skipped, or failed).
        False if the queue is empty.
    """
    # Step 1: Claim next pending request
    req_id = None
    channel_id = None
    title = None
    template_id = None
    segment_start = None

    with session() as db:
        req = claim_next(db)
        if req is None:
            return False
        req_id = req.id
        channel_id = req.channel_id
        title = req.next_program_title
        template_id = req.template_id
        segment_start = req.segment_start_utc

    log = logger.bind(
        cun_request_id=str(req_id),
        channel_id=str(channel_id),
        title=title,
        template_id=template_id,
    )

    # Step 2: Deadline check — INV-CUN-RENDER-DEADLINE-001
    now = datetime.now(UTC)
    deadline = segment_start - _ms_to_timedelta(deadline_margin_ms)
    if now >= deadline:
        log.info(
            "cun_render_skipped_deadline",
            segment_start=segment_start.isoformat(),
            deadline=deadline.isoformat(),
        )
        with session() as db:
            skip(db, req_id, f"past render deadline: now={now.isoformat()} >= deadline={deadline.isoformat()}")
        return True

    # Step 3: Pre-render dedup — INV-CUN-DEDUP-BEFORE-RENDER-001
    h = content_hash_for(template_id, title)
    cache_path = str(Path(cache_dir) / f"{h}.mp4")

    with session() as db:
        existing = find_completed_by_hash(db, h)
        if existing is not None:
            log.info(
                "cun_render_dedup_reuse",
                content_hash=h,
                reused_path=existing.rendered_asset_path,
            )
            complete(db, req_id, existing.rendered_asset_path, h)
            return True

    # Step 4: Render — ffmpeg drawtext on looped background
    try:
        template = template_resolver(channel_id, template_id)
        if template is None:
            with session() as db:
                fail(db, req_id, f"template not found: {template_id}")
            log.error("cun_render_template_not_found", template_id=template_id)
            return True

        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        cmd = _build_ffmpeg_cmd(template, title, duration_ms, cache_path)
        log.debug("cun_render_start", cmd=" ".join(cmd))
        render_fn(cmd)
    except Exception as e:
        log.exception("cun_render_failed", error=str(e))
        with session() as db:
            fail(db, req_id, str(e)[:500])
        return True

    # Step 5: Complete — mark done with path and hash
    with session() as db:
        complete(db, req_id, cache_path, h)

    log.info("cun_render_completed", content_hash=h, path=cache_path)
    return True


def run_loop(
    cache_dir: str,
    template_resolver: callable,
    duration_ms: int = 10_000,
    deadline_margin_ms: int = 30_000,
    iterations: int | None = None,
    render_fn: callable = _render_ffmpeg,
) -> int:
    """Process CUN render requests until queue is empty or iterations reached.

    Returns the number of requests processed.
    """
    count = 0
    while True:
        if iterations is not None and count >= iterations:
            break
        if not run_once(
            cache_dir=cache_dir,
            template_resolver=template_resolver,
            duration_ms=duration_ms,
            deadline_margin_ms=deadline_margin_ms,
            render_fn=render_fn,
        ):
            break
        count += 1
    return count


def _ms_to_timedelta(ms: int):
    """Convert milliseconds to timedelta."""
    from datetime import timedelta
    return timedelta(milliseconds=ms)
