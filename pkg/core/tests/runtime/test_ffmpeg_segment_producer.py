from __future__ import annotations

from datetime import datetime, timedelta

from retrovue.runtime.producer.base import ContentSegment
from retrovue.runtime.producer.ffmpeg_segment_producer import FFmpegSegmentProducer


def _make_segment(offset: float, duration: float, segment_type: str = "content") -> ContentSegment:
    start = datetime.fromtimestamp(1_700_000_000 + offset)
    end = start + timedelta(seconds=duration)
    return ContentSegment(
        asset_id=f"asset-{offset}",
        start_time=start,
        end_time=end,
        segment_type=segment_type,
        metadata={"duration_seconds": duration},
    )


def test_ffmpeg_producer_start_mid_segment_and_emit_edges():
    segments = [
        _make_segment(0.0, 10.0),
        _make_segment(10.0, 5.0, segment_type="ad"),
    ]
    producer = FFmpegSegmentProducer(channel_id="chan-1", configuration={"output_url": "pipe:1"})
    start_time = segments[0].start_time + timedelta(seconds=5)
    assert producer.start(segments, start_time) is True

    # First tick (remain within first segment).
    producer.on_paced_tick(t_now=0.0, dt=3.0)
    assert producer.poll_segment_edges() == []

    # Second tick crosses the segment boundary.
    producer.on_paced_tick(t_now=0.0, dt=3.0)
    edges = producer.poll_segment_edges()
    assert len(edges) == 1
    edge = edges[0]
    assert edge.segment.asset_id == segments[0].asset_id
    assert edge.kind == "segment-end"

    # Next ticks should eventually reach second segment end.
    producer.on_paced_tick(t_now=0.0, dt=5.0)
    edges = producer.poll_segment_edges()
    assert len(edges) == 1
    assert edges[0].segment.asset_id == segments[1].asset_id


def test_ffmpeg_producer_tick_non_blocking_and_no_negative_dt():
    segment = _make_segment(0.0, 4.0)
    producer = FFmpegSegmentProducer(channel_id="chan-2", configuration={})
    producer.start([segment], segment.start_time)

    producer.on_paced_tick(t_now=0.0, dt=0.0)
    assert producer.poll_segment_edges() == []

    producer.on_paced_tick(t_now=0.0, dt=0.5)
    assert producer.poll_segment_edges() == []

    producer.on_paced_tick(t_now=0.0, dt=10.0)
    edges = producer.poll_segment_edges()
    assert len(edges) == 1
    assert edges[0].segment.asset_id == segment.asset_id


def test_ffmpeg_producer_segment_append_and_endpoint():
    base_segment = _make_segment(0.0, 5.0)
    producer = FFmpegSegmentProducer(channel_id="chan-3", configuration={"output_url": "pipe:1"})
    producer.start([base_segment], base_segment.start_time)

    new_segment = _make_segment(5.0, 3.0)
    assert producer.play_content(new_segment) is True
    producer.on_paced_tick(t_now=0.0, dt=5.0)
    producer.on_paced_tick(t_now=0.0, dt=5.0)
    edges = producer.poll_segment_edges()
    assert len(edges) >= 1
    assert producer.get_stream_endpoint() == "pipe:1"

    producer.stop()
    assert producer.get_stream_endpoint() is None



