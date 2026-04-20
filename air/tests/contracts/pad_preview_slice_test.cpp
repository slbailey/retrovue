// AIR vNext — first-slice contract test.
//
// Validates: PadSourceProducer → IdentityNormalizer → VideoPreviewBuffer
//          + AudioPreviewBuffer end-to-end for a single segment.
//
// Vault invariants exercised:
//   - INV-NORMALIZER-PER-PRODUCER-001 (single producer → single normalizer
//     → single preview pair)
//   - INV-NORMALIZER-SHARED-CHANNEL-ORIGIN-001 (audio + video resolve
//     against the same origin)
//   - INV-NORMALIZER-OUTPUT-CHANNEL-TIME-001 (preview entries carry
//     channel-time PTS as decision-relevant value)
//   - INV-NORMALIZER-OUTPUT-CHANNEL-FORMAT-001 (preview entries are
//     channel-canonical format)
//   - INV-NORMALIZER-AV-SYNC-AT-OUTPUT-001 (A/V fronts match at same
//     source-time instant — trivially true for identity normalizer)
//   - INV-NORMALIZER-REANCHOR-BOUNDED-001 (re-anchor tiers behave as
//     declared)
//   - INV-PREVIEW-CHANNEL-CANONICAL-001 (preview holds only channel-
//     canonical content)
//   - INV-PREVIEW-DESTINATION-PTS-CONTIGUOUS-001 (preview PTS is
//     monotonic and origin-anchored)
//   - INV-BUFFERSTORE-SOLE-WRITER-001 (preview buffer writes only via
//     Push; test never mutates internal state)
//   - INV-BUFFERSTORE-BOUNDED-CAPACITY-001 (preview refuses push at
//     capacity; overflow observable)
//   - INV-BUFFERSTORE-FRONTIER-OBSERVABLE-001 (front/back PTS + depth
//     readable)
//   - INV-BUFFERSTORE-UNDERFLOW-OBSERVABLE-001 (pop-on-empty returns
//     nullopt and increments counter)
//   - INV-DOWNSTREAM-SOURCE-PTS-OPAQUE-001 (source PTS metadata is
//     present on entries but not required for correctness)

#include <gtest/gtest.h>

#include <optional>
#include <utility>

#include "channel_canonical.hpp"
#include "identity_normalizer.hpp"
#include "pad_source_producer.hpp"
#include "preview_buffer.hpp"

namespace retrovue::air {
namespace {

// NTSC canonical (matches cheers-24-7.yaml).
ChannelCanonical NtscCanonical() {
  return ChannelCanonical{
      .video = VideoCanonical{.width = 968,
                              .height = 720,
                              .frame_rate = {30000, 1001},
                              .pixel_format = PixelFormat::kYuv420p},
      .audio = AudioCanonical{.sample_rate = 48000, .channels = 2}};
}

// Build a prepared + activated pad source.
PadSourceProducer MakeActivePad(ChannelCanonical canonical) {
  PadSourceProducer pad(canonical);
  EXPECT_TRUE(pad.Prepare());
  EXPECT_TRUE(pad.Activate());
  return pad;
}

// ---------------------------------------------------------------------------
// Channel canonical sanity.
// ---------------------------------------------------------------------------

TEST(ChannelCanonical, NtscParametersValid) {
  const auto c = NtscCanonical();
  EXPECT_TRUE(c.IsValid());
  EXPECT_TRUE(c.video.frame_rate.IsValid());
  // Period: 1e6 * 1001 / 30000 ≈ 33366us (integer division; 33366 exact).
  EXPECT_EQ(c.video.frame_rate.PeriodMicros(), 33366);
}

// ---------------------------------------------------------------------------
// Pad source lifecycle and format.
// ---------------------------------------------------------------------------

TEST(PadSourceProducer, LifecycleTransitionsAreValid) {
  PadSourceProducer pad(NtscCanonical());
  EXPECT_EQ(pad.Lifecycle(), ProducerLifecycle::kConstructed);

  EXPECT_TRUE(pad.Prepare());
  EXPECT_EQ(pad.Lifecycle(), ProducerLifecycle::kPrepared);

  EXPECT_TRUE(pad.Activate());
  EXPECT_EQ(pad.Lifecycle(), ProducerLifecycle::kActivated);

  pad.Retire();
  EXPECT_EQ(pad.Lifecycle(), ProducerLifecycle::kRetired);
}

TEST(PadSourceProducer, DoublePrepareRejected) {
  PadSourceProducer pad(NtscCanonical());
  EXPECT_TRUE(pad.Prepare());
  EXPECT_FALSE(pad.Prepare());  // Second prepare illegal.
}

TEST(PadSourceProducer, PullBeforeActivateReturnsNullopt) {
  PadSourceProducer pad(NtscCanonical());
  pad.Prepare();
  EXPECT_FALSE(pad.PullVideo().has_value());
  EXPECT_FALSE(pad.PullAudio().has_value());
}

TEST(PadSourceProducer, VideoFrameIsChannelFormatYuv420pBlack) {
  auto pad = MakeActivePad(NtscCanonical());
  auto frame = pad.PullVideo();
  ASSERT_TRUE(frame.has_value());

  EXPECT_EQ(frame->width, 968);
  EXPECT_EQ(frame->height, 720);

  const int y_size = 968 * 720;
  const int uv_size = (968 / 2) * (720 / 2);
  ASSERT_EQ(static_cast<int>(frame->data.size()), y_size + 2 * uv_size);

  // Y plane: broadcast black 0x10.
  EXPECT_EQ(frame->data[0], 0x10);
  EXPECT_EQ(frame->data[y_size - 1], 0x10);
  // Chroma: neutral 0x80.
  EXPECT_EQ(frame->data[y_size], 0x80);
  EXPECT_EQ(frame->data[y_size + 2 * uv_size - 1], 0x80);
}

TEST(PadSourceProducer, AudioBlockIsChannelFormatSilence) {
  auto pad = MakeActivePad(NtscCanonical());
  auto block = pad.PullAudio();
  ASSERT_TRUE(block.has_value());

  EXPECT_EQ(block->sample_rate, 48000);
  EXPECT_EQ(block->channels, 2);
  EXPECT_GT(block->nb_samples, 0);
  EXPECT_EQ(static_cast<int>(block->data.size()),
            block->nb_samples * block->channels);

  for (int16_t s : block->data) EXPECT_EQ(s, 0);
}

TEST(PadSourceProducer, SourcePtsAdvancesMonotonicallyVideo) {
  auto pad = MakeActivePad(NtscCanonical());
  int64_t prev = -1;
  for (int i = 0; i < 10; ++i) {
    auto f = pad.PullVideo();
    ASSERT_TRUE(f.has_value());
    EXPECT_GT(f->source_pts_us, prev);
    prev = f->source_pts_us;
  }
}

// ---------------------------------------------------------------------------
// Identity normalizer → preview buffer end-to-end.
// ---------------------------------------------------------------------------

TEST(IdentityNormalizer, PreservesChannelCanonicalAndOrigin) {
  auto canonical = NtscCanonical();
  PadSourceProducer pad(canonical);
  ASSERT_TRUE(pad.Prepare());
  ASSERT_TRUE(pad.Activate());

  ChannelOrigin origin{.source_pts_anchor_us = 0,
                       .channel_pts_anchor_us = 0};
  IdentityNormalizer norm(canonical, &pad, origin);

  EXPECT_EQ(norm.Canonical().video.width, 968);
  EXPECT_EQ(norm.Canonical().video.height, 720);
  EXPECT_EQ(norm.Canonical().audio.sample_rate, 48000);
  EXPECT_EQ(norm.Origin().source_pts_anchor_us, 0);
  EXPECT_EQ(norm.Origin().channel_pts_anchor_us, 0);
}

TEST(IdentityNormalizerEndToEnd, VideoPreviewHasChannelTimePts) {
  auto canonical = NtscCanonical();
  PadSourceProducer pad(canonical);
  pad.Prepare();
  pad.Activate();

  IdentityNormalizer norm(canonical, &pad,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0});
  VideoPreviewBuffer preview(/*capacity_frames=*/60);

  // Fill 30 frames from pad through identity normalizer into preview.
  for (int i = 0; i < 30; ++i) {
    auto vf = norm.PullVideo();
    ASSERT_TRUE(vf.has_value()) << "PullVideo failed at i=" << i;
    // INV-NORMALIZER-OUTPUT-CHANNEL-TIME-001: PTS is derived from the
    // Normalizer's own channel frame index via the canonical formula —
    // NOT from source PTS. Source PTS survives as opaque metadata.
    EXPECT_EQ(vf->pts_us_relative,
              canonical.video.frame_rate.NthStepPtsUs(i))
        << "channel-time PTS must come from channel frame index, not "
           "from source PTS, at i=" << i;
    // Opaque source PTS metadata is present.
    EXPECT_NE(vf->source_pts_us_opaque, kSourcePtsUnknown);
    ASSERT_TRUE(preview.Push(*vf));
  }

  EXPECT_EQ(preview.Depth(), 30);
  // Front is the first-pushed frame's relative PTS (= 0).
  ASSERT_TRUE(preview.FrontPtsUsRelative().has_value());
  EXPECT_EQ(*preview.FrontPtsUsRelative(), 0);
  // Back is the 30th frame's relative PTS, computed via the canonical
  // round-to-nearest step formula (NOT linear period multiplication,
  // which would drift).
  ASSERT_TRUE(preview.BackPtsUsRelative().has_value());
  EXPECT_EQ(*preview.BackPtsUsRelative(),
            canonical.video.frame_rate.NthStepPtsUs(29));
}

TEST(IdentityNormalizerEndToEnd, AudioPreviewHasChannelTimePts) {
  auto canonical = NtscCanonical();
  PadSourceProducer pad(canonical);
  pad.Prepare();
  pad.Activate();

  IdentityNormalizer norm(canonical, &pad,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0});
  AudioPreviewBuffer preview(/*capacity_blocks=*/60);

  int64_t expected_cumulative_sample = 0;
  for (int i = 0; i < 30; ++i) {
    auto ab = norm.PullAudio();
    ASSERT_TRUE(ab.has_value()) << "PullAudio failed at i=" << i;
    // Channel-time PTS of the block's first sample, derived from the
    // Normalizer's cumulative channel sample index — not from source PTS.
    const int64_t rate = canonical.audio.sample_rate;
    const int64_t expected_pts =
        (expected_cumulative_sample * 1'000'000 + rate / 2) / rate;
    EXPECT_EQ(ab->pts_us_relative, expected_pts) << "i=" << i;
    expected_cumulative_sample += ab->nb_samples;
    ASSERT_TRUE(preview.Push(*ab));
  }

  EXPECT_EQ(preview.Depth(), 30);
  ASSERT_TRUE(preview.FrontPtsUsRelative().has_value());
  EXPECT_EQ(*preview.FrontPtsUsRelative(), 0);
}

// ---------------------------------------------------------------------------
// Buffer bound + underflow.
// ---------------------------------------------------------------------------

TEST(PreviewBuffer, VideoOverflowRefusesPushAndIncrementsCounter) {
  VideoPreviewBuffer preview(/*capacity_frames=*/3);
  VideoFrame f;
  f.pts_us_relative = 0;
  f.data.assign(16, 0x10);

  EXPECT_TRUE(preview.Push(f));
  EXPECT_TRUE(preview.Push(f));
  EXPECT_TRUE(preview.Push(f));

  EXPECT_FALSE(preview.Push(f));  // Fourth push hits bound.

  EXPECT_EQ(preview.Depth(), 3);
  EXPECT_EQ(preview.Observability().overflow_count, 1);
  EXPECT_EQ(preview.Observability().total_pushed, 3);
}

TEST(PreviewBuffer, VideoUnderflowReturnsNulloptAndIncrementsCounter) {
  VideoPreviewBuffer preview(/*capacity_frames=*/4);
  auto popped = preview.Pop();
  EXPECT_FALSE(popped.has_value());
  EXPECT_EQ(preview.Observability().underflow_count, 1);
}

TEST(PreviewBuffer, AudioOverflowRefusesPushAndIncrementsCounter) {
  AudioPreviewBuffer preview(/*capacity_blocks=*/2);
  AudioBlock b;
  b.pts_us_relative = 0;
  b.nb_samples = 1;
  b.data = {0, 0};

  EXPECT_TRUE(preview.Push(b));
  EXPECT_TRUE(preview.Push(b));
  EXPECT_FALSE(preview.Push(b));

  EXPECT_EQ(preview.Depth(), 2);
  EXPECT_EQ(preview.Observability().overflow_count, 1);
}

// ---------------------------------------------------------------------------
// Re-anchor tiers.
// ---------------------------------------------------------------------------

TEST(IdentityNormalizerReanchor, SubFramePeriodIsNoop) {
  auto canonical = NtscCanonical();
  PadSourceProducer pad(canonical);
  pad.Prepare();
  pad.Activate();

  IdentityNormalizer norm(canonical, &pad,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 1'000'000});

  // 1/2 of a frame period — below noop threshold.
  const int64_t half_frame = canonical.video.frame_rate.PeriodMicros() / 2;
  const int64_t new_anchor = 1'000'000 + half_frame;
  EXPECT_EQ(norm.Reanchor(new_anchor), ReanchorTier::kNoop);
  EXPECT_EQ(norm.Origin().channel_pts_anchor_us, 1'000'000);
}

TEST(IdentityNormalizerReanchor, SubSecondAdjusts) {
  auto canonical = NtscCanonical();
  PadSourceProducer pad(canonical);
  pad.Prepare();
  pad.Activate();

  IdentityNormalizer norm(canonical, &pad,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 1'000'000});

  // 500ms — above noop, below re-prep.
  const int64_t new_anchor = 1'500'000;
  EXPECT_EQ(norm.Reanchor(new_anchor), ReanchorTier::kAdjusted);
  EXPECT_EQ(norm.Origin().channel_pts_anchor_us, 1'500'000);
}

TEST(IdentityNormalizerReanchor, MultiSecondRequiresRePrep) {
  auto canonical = NtscCanonical();
  PadSourceProducer pad(canonical);
  pad.Prepare();
  pad.Activate();

  IdentityNormalizer norm(canonical, &pad,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 1'000'000});

  // 2 seconds — at or above re-prep threshold.
  const int64_t new_anchor = 3'000'000;
  EXPECT_EQ(norm.Reanchor(new_anchor), ReanchorTier::kRePrepRequired);
  // Origin unchanged — caller handles re-prep.
  EXPECT_EQ(norm.Origin().channel_pts_anchor_us, 1'000'000);
}

// ---------------------------------------------------------------------------
// A/V sync at normalizer output (identity case).
//
// Same source-time instant produces same channel-time PTS on audio and
// video. In identity, source_pts == channel_pts_relative (with origin 0).
// ---------------------------------------------------------------------------

TEST(IdentityNormalizerAVSync, FirstPullsShareChannelPtsRelativeOrigin) {
  auto canonical = NtscCanonical();
  PadSourceProducer pad(canonical);
  pad.Prepare();
  pad.Activate();

  IdentityNormalizer norm(canonical, &pad,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0});

  auto first_video = norm.PullVideo();
  auto first_audio = norm.PullAudio();
  ASSERT_TRUE(first_video.has_value());
  ASSERT_TRUE(first_audio.has_value());

  // Both originate at source PTS 0 → channel PTS relative 0.
  EXPECT_EQ(first_video->pts_us_relative, 0);
  EXPECT_EQ(first_audio->pts_us_relative, 0);
}

}  // namespace
}  // namespace retrovue::air
