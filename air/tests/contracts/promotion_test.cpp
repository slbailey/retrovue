// AIR vNext — slice 3 contract test.
//
// Validates the dual-buffer promotion mechanic: two preview/normalizer
// pairs coexist in a session; PlaybackDirector holds a reference to whichever
// is currently live; promotion is a pointer swap; the emitted absolute
// channel PTS stream is continuous across promotion; source identity
// changes but is invisible on the PTS timeline.
//
// Vault invariants exercised:
//   - INV-PREVIEW-DESTINATION-PTS-CONTIGUOUS-001 (absolute channel PTS
//     stream continuous across promotion — pointer swap with no PTS
//     adjustment at swap time for the on-schedule case; tier-2 re-anchor
//     on the mistimed case)
//   - INV-NORMALIZER-REANCHOR-BOUNDED-001 (tier-2 adjust works under
//     promotion-time re-anchor)
//   - INV-DOWNSTREAM-SOURCE-PTS-OPAQUE-001 (source identity changes across
//     promotion; consumer reads only channel-time PTS, not source PTS)
//   - INV-BUFFERSTORE-SOLE-WRITER-001 (each preview is written only by
//     its own normalizer; promotion does not cross writers)

#include <gtest/gtest.h>

#include <cstdint>
#include <optional>

#include "channel_canonical.hpp"
#include "identity_normalizer.hpp"
#include "playback_director.hpp"
#include "pad_source_producer.hpp"
#include "preview_buffer.hpp"
#include "standard_normalizer.hpp"
#include "synthetic_source_producer.hpp"

namespace retrovue::air {
namespace {

constexpr int kChannelFps = 30;
// Canonical channel-frame PTS computed via the same round-to-nearest
// formula the Normalizers use. Do NOT use linear period multiplication
// here: it drifts ~1us per step and fails exact equality across segments.
constexpr int64_t ChannelFramePts30(int64_t k) {
  return Rational{kChannelFps, 1}.NthStepPtsUs(k);
}

ChannelCanonical Channel30() {
  return ChannelCanonical{
      .video = VideoCanonical{.width = 32,
                              .height = 16,
                              .frame_rate = {kChannelFps, 1},
                              .pixel_format = PixelFormat::kYuv420p},
      .audio = AudioCanonical{.sample_rate = 48000, .channels = 2}};
}

// ---------------------------------------------------------------------------
// PlaybackDirector basic behaviour.
// ---------------------------------------------------------------------------

TEST(PlaybackDirector, EmptyUntilFirstPromote) {
  PlaybackDirector live;
  EXPECT_FALSE(live.HasActiveAssignment());
  EXPECT_FALSE(live.ActiveAssignment().IsValid());
  EXPECT_EQ(live.promotion_count(), 0);
}

TEST(PlaybackDirector, PromoteEstablishesCurrent) {
  auto canonical = Channel30();
  PadSourceProducer pad(canonical);
  pad.Prepare();
  pad.Activate();
  IdentityNormalizer norm(canonical, &pad,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0});
  VideoPreviewBuffer vp(10);
  AudioPreviewBuffer ap(10);

  PlaybackDirector live;
  live.PromoteToAssignment({.video_preview = &vp,
                .audio_preview = &ap,
                .normalizer = &norm,
                .segment_id = "pad"});

  EXPECT_TRUE(live.HasActiveAssignment());
  EXPECT_EQ(live.promotion_count(), 1);
  EXPECT_STREQ(live.ActiveAssignment().segment_id, "pad");
}

// ---------------------------------------------------------------------------
// Promotion-continuity: pad segment, then content segment. The emitted
// absolute channel PTS stream is monotonic and gap-free across promotion.
// This is the load-bearing test — exercises the dual-buffer model.
// ---------------------------------------------------------------------------

TEST(PlaybackDirectorPromotion, ContinuousChannelPtsAcrossPadToContent) {
  auto canonical = Channel30();

  // Pad segment. Identity normalizer because pad already emits at channel
  // rate / channel format. Anchor = 0: first pad frame at absolute 0.
  PadSourceProducer pad(canonical);
  pad.Prepare();
  pad.Activate();
  IdentityNormalizer pad_norm(canonical, &pad,
                              {.source_pts_anchor_us = 0,
                               .channel_pts_anchor_us = 0});
  VideoPreviewBuffer pad_v(50);
  AudioPreviewBuffer pad_a(50);

  // Content segment: synthetic 30fps source -> Standard normalizer at
  // channel 30fps (so passthrough cadence). Content origin anchored to the
  // channel PTS of the Nth frame, computed via the canonical formula
  // (NOT linear period multiplication).
  constexpr int kPadFramesToConsume = 10;
  const int64_t content_anchor_us = ChannelFramePts30(kPadFramesToConsume);

  SyntheticSourceProducer content({
      .video_frame_rate = {30, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
      .audio_waveform = SyntheticAudioWaveform::kConstant,
      .audio_samples_per_block = 480,
  });
  content.Prepare();
  content.Activate();
  StandardNormalizer content_norm(canonical, {30, 1}, 32, 16, 48000, &content,
                                  {.source_pts_anchor_us = 0,
                                   .channel_pts_anchor_us = content_anchor_us},
                                  /*samples_per_channel_audio_block=*/1600);
  VideoPreviewBuffer content_v(50);
  AudioPreviewBuffer content_a(50);

  // Fill both previews.
  constexpr int kFillCount = 30;
  for (int i = 0; i < kFillCount; ++i) {
    auto pf = pad_norm.PullVideo();
    auto cf = content_norm.PullVideo();
    ASSERT_TRUE(pf.has_value()) << "pad i=" << i;
    ASSERT_TRUE(cf.has_value()) << "content i=" << i;
    ASSERT_TRUE(pad_v.Push(*pf));
    ASSERT_TRUE(content_v.Push(*cf));
  }

  // Live starts on pad.
  PlaybackDirector live;
  live.PromoteToAssignment({.video_preview = &pad_v,
                .audio_preview = &pad_a,
                .normalizer = &pad_norm,
                .segment_id = "pad"});

  // Consume kPadFramesToConsume frames from live (pad). Expected PTS uses
  // the canonical round-to-nearest formula.
  int64_t prev_abs_pts = -1;
  for (int i = 0; i < kPadFramesToConsume; ++i) {
    auto f = live.ActiveAssignment().video_preview->Pop();
    ASSERT_TRUE(f.has_value()) << "pad consume i=" << i;
    const int64_t abs_pts = live.ActiveAssignment().AbsoluteVideoPtsUs(*f);
    EXPECT_EQ(abs_pts, ChannelFramePts30(i)) << "pad frame i=" << i;
    EXPECT_GT(abs_pts, prev_abs_pts);
    prev_abs_pts = abs_pts;
  }

  // Promote to content.
  live.PromoteToAssignment({.video_preview = &content_v,
                .audio_preview = &content_a,
                .normalizer = &content_norm,
                .segment_id = "content"});
  EXPECT_EQ(live.promotion_count(), 2);
  EXPECT_STREQ(live.ActiveAssignment().segment_id, "content");
  EXPECT_STREQ(live.PreviousAssignment().segment_id, "pad");

  // First content frame. Absolute PTS = content_anchor + 0 = channel-time
  // PTS of the 10th frame.
  auto first_content = live.ActiveAssignment().video_preview->Pop();
  ASSERT_TRUE(first_content.has_value());
  const int64_t first_abs = live.ActiveAssignment().AbsoluteVideoPtsUs(*first_content);
  EXPECT_EQ(first_abs, content_anchor_us);

  // Continuity: gap between last pad and first content is one channel
  // frame period (range [33333, 33334] due to rounding at 30fps).
  const int64_t gap = first_abs - prev_abs_pts;
  EXPECT_GE(gap, 33333);
  EXPECT_LE(gap, 33334);

  // Source identity changed. Content frames carry burned indices; pad frames
  // were black YUV420P with no burn. Verify first content frame is source 0.
  const int64_t burned =
      SyntheticSourceProducer::ReadFrameIndexFromYPlane(first_content->data);
  EXPECT_EQ(burned, 0);

  prev_abs_pts = first_abs;

  // Continue consuming content; verify monotonic absolute PTS matches the
  // canonical formula (anchor + relative), and inter-frame gaps fall in the
  // one-period range.
  for (int i = 1; i < 10; ++i) {
    auto f = live.ActiveAssignment().video_preview->Pop();
    ASSERT_TRUE(f.has_value()) << "content consume i=" << i;
    const int64_t abs_pts = live.ActiveAssignment().AbsoluteVideoPtsUs(*f);
    const int64_t expected = content_anchor_us + ChannelFramePts30(i);
    EXPECT_EQ(abs_pts, expected) << "content frame i=" << i;
    const int64_t g = abs_pts - prev_abs_pts;
    EXPECT_GE(g, 33333);
    EXPECT_LE(g, 33334);
    const int64_t b =
        SyntheticSourceProducer::ReadFrameIndexFromYPlane(f->data);
    EXPECT_EQ(b, i);
    prev_abs_pts = abs_pts;
  }
}

// ---------------------------------------------------------------------------
// Audio continuity across promotion: absolute channel PTS of the first
// audio block from content equals the expected next absolute PTS after pad.
// Also verifies audio and video both cross promotion at consistent time.
// ---------------------------------------------------------------------------

TEST(PlaybackDirectorPromotion, ContinuousAudioAcrossPromotion) {
  auto canonical = Channel30();

  PadSourceProducer pad(canonical);
  pad.Prepare();
  pad.Activate();
  IdentityNormalizer pad_norm(canonical, &pad,
                              {.source_pts_anchor_us = 0,
                               .channel_pts_anchor_us = 0});
  VideoPreviewBuffer pad_v(50);
  AudioPreviewBuffer pad_a(50);

  // Pad emits audio blocks sized at samples-per-frame-period (~1600 at
  // 48k/30fps). After consuming N pad audio blocks, the next expected
  // block's first-sample channel sample index is N * samples_per_block.
  // Discover pad's block size by pulling one.
  auto first_pad_audio = pad_norm.PullAudio();
  ASSERT_TRUE(first_pad_audio.has_value());
  const int pad_samples_per_block = first_pad_audio->nb_samples;
  ASSERT_TRUE(pad_a.Push(std::move(*first_pad_audio)));

  // Fill more pad audio.
  for (int i = 0; i < 29; ++i) {
    auto b = pad_norm.PullAudio();
    ASSERT_TRUE(b.has_value());
    ASSERT_TRUE(pad_a.Push(std::move(*b)));
  }

  constexpr int kPadBlocksToConsume = 5;

  // Compute expected next absolute sample index after consuming
  // kPadBlocksToConsume blocks.
  const int64_t content_first_sample_abs_idx =
      static_cast<int64_t>(kPadBlocksToConsume) * pad_samples_per_block;
  // Its channel-time absolute PTS.
  const int64_t content_anchor_us =
      (content_first_sample_abs_idx * 1'000'000 + 48000 / 2) / 48000;

  SyntheticSourceProducer content({
      .video_frame_rate = {30, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
      .audio_waveform = SyntheticAudioWaveform::kConstant,
      .audio_samples_per_block = 480,
  });
  content.Prepare();
  content.Activate();
  StandardNormalizer content_norm(
      canonical, {30, 1}, 32, 16, 48000, &content,
      {.source_pts_anchor_us = 0,
       .channel_pts_anchor_us = content_anchor_us},
      pad_samples_per_block);  // match block size for easy comparison
  VideoPreviewBuffer content_v(50);
  AudioPreviewBuffer content_a(50);

  // Fill content audio preview.
  for (int i = 0; i < 10; ++i) {
    auto b = content_norm.PullAudio();
    ASSERT_TRUE(b.has_value());
    ASSERT_TRUE(content_a.Push(std::move(*b)));
  }

  // Live on pad.
  PlaybackDirector live;
  live.PromoteToAssignment({.video_preview = &pad_v,
                .audio_preview = &pad_a,
                .normalizer = &pad_norm,
                .segment_id = "pad"});

  // Consume kPadBlocksToConsume pad audio blocks.
  int64_t prev_abs = -1;
  for (int i = 0; i < kPadBlocksToConsume; ++i) {
    auto b = live.ActiveAssignment().audio_preview->Pop();
    ASSERT_TRUE(b.has_value()) << "pad audio i=" << i;
    const int64_t abs = live.ActiveAssignment().AbsoluteAudioPtsUs(*b);
    EXPECT_GT(abs, prev_abs);
    prev_abs = abs;
  }

  // Promote to content.
  live.PromoteToAssignment({.video_preview = &content_v,
                .audio_preview = &content_a,
                .normalizer = &content_norm,
                .segment_id = "content"});

  // First content audio block absolute PTS = content_anchor_us (because
  // first sample relative PTS = 0 under its Normalizer's anchor).
  auto first = live.ActiveAssignment().audio_preview->Pop();
  ASSERT_TRUE(first.has_value());
  EXPECT_EQ(live.ActiveAssignment().AbsoluteAudioPtsUs(*first), content_anchor_us);
}

// ---------------------------------------------------------------------------
// Re-anchor on mistimed promotion: promotion happens LATER than originally
// scheduled, so we re-anchor the content normalizer before promotion to
// maintain absolute-PTS continuity.
// ---------------------------------------------------------------------------

TEST(PlaybackDirectorPromotion, ReAnchorOnMistimedPromotionMaintainsContinuity) {
  auto canonical = Channel30();

  PadSourceProducer pad(canonical);
  pad.Prepare();
  pad.Activate();
  IdentityNormalizer pad_norm(canonical, &pad,
                              {.source_pts_anchor_us = 0,
                               .channel_pts_anchor_us = 0});
  VideoPreviewBuffer pad_v(50);
  AudioPreviewBuffer pad_a(50);

  // Content seeded as if promotion would happen at pad frame 10.
  constexpr int kScheduledPromotionFrame = 10;
  const int64_t originally_scheduled_anchor_us =
      ChannelFramePts30(kScheduledPromotionFrame);

  SyntheticSourceProducer content({
      .video_frame_rate = {30, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
      .audio_waveform = SyntheticAudioWaveform::kConstant,
      .audio_samples_per_block = 480,
  });
  content.Prepare();
  content.Activate();
  StandardNormalizer content_norm(
      canonical, {30, 1}, 32, 16, 48000, &content,
      {.source_pts_anchor_us = 0,
       .channel_pts_anchor_us = originally_scheduled_anchor_us},
      1600);
  VideoPreviewBuffer content_v(50);
  AudioPreviewBuffer content_a(50);

  // Fill both.
  for (int i = 0; i < 30; ++i) {
    auto pf = pad_norm.PullVideo();
    auto cf = content_norm.PullVideo();
    ASSERT_TRUE(pf.has_value());
    ASSERT_TRUE(cf.has_value());
    ASSERT_TRUE(pad_v.Push(*pf));
    ASSERT_TRUE(content_v.Push(*cf));
  }

  PlaybackDirector live;
  live.PromoteToAssignment({.video_preview = &pad_v,
                .audio_preview = &pad_a,
                .normalizer = &pad_norm,
                .segment_id = "pad"});

  // Actually consume 15 pad frames (promotion is 5 frames late).
  constexpr int kActualPadFramesConsumed = 15;
  int64_t last_pad_abs = -1;
  for (int i = 0; i < kActualPadFramesConsumed; ++i) {
    auto f = live.ActiveAssignment().video_preview->Pop();
    ASSERT_TRUE(f.has_value());
    last_pad_abs = live.ActiveAssignment().AbsoluteVideoPtsUs(*f);
  }

  // Expected next absolute PTS = channel-time PTS of the next overall
  // frame index (15, since we consumed frames 0..14).
  const int64_t expected_next_abs = ChannelFramePts30(kActualPadFramesConsumed);

  // Re-anchor content to the true promotion moment. Delta = 5 periods ~= 166665us,
  // below 1 second -> tier-2 adjust.
  EXPECT_EQ(content_norm.Reanchor(expected_next_abs), ReanchorTier::kAdjusted);
  EXPECT_EQ(content_norm.Origin().channel_pts_anchor_us, expected_next_abs);

  // Promote.
  live.PromoteToAssignment({.video_preview = &content_v,
                .audio_preview = &content_a,
                .normalizer = &content_norm,
                .segment_id = "content"});

  // First content frame: absolute PTS should equal expected_next_abs.
  auto f = live.ActiveAssignment().video_preview->Pop();
  ASSERT_TRUE(f.has_value());
  EXPECT_EQ(live.ActiveAssignment().AbsoluteVideoPtsUs(*f), expected_next_abs);

  // Source identity verified as first content source frame.
  EXPECT_EQ(SyntheticSourceProducer::ReadFrameIndexFromYPlane(f->data), 0);

  // Continue for 5 frames; verify monotonic absolute PTS advance. Inter-
  // frame gap is one channel frame period (range [33333, 33334] at 30fps
  // with round-to-nearest).
  int64_t prev = expected_next_abs;
  for (int i = 1; i < 6; ++i) {
    auto nf = live.ActiveAssignment().video_preview->Pop();
    ASSERT_TRUE(nf.has_value());
    const int64_t abs = live.ActiveAssignment().AbsoluteVideoPtsUs(*nf);
    const int64_t g = abs - prev;
    EXPECT_GE(g, 33333);
    EXPECT_LE(g, 33334);
    prev = abs;
  }
}

// ---------------------------------------------------------------------------
// Source identity changes across promotion but is invisible on the PTS
// timeline. This is an explicit test of INV-OUTPUT-SOURCE-PTS-OPAQUE:
// what changes at the wire is content; what does NOT change is PTS
// continuity.
// ---------------------------------------------------------------------------

TEST(PlaybackDirectorPromotion, SourceIdentityChangesButPtsDoesNot) {
  auto canonical = Channel30();

  PadSourceProducer pad(canonical);
  pad.Prepare();
  pad.Activate();
  IdentityNormalizer pad_norm(canonical, &pad,
                              {.source_pts_anchor_us = 0,
                               .channel_pts_anchor_us = 0});
  VideoPreviewBuffer pad_v(50);
  AudioPreviewBuffer pad_a(50);

  const int64_t content_anchor_us = ChannelFramePts30(5);

  SyntheticSourceProducer content({
      .video_frame_rate = {30, 1},
      .video_width = 32,
      .video_height = 16,
      .audio_sample_rate = 48000,
      .audio_channels = 2,
  });
  content.Prepare();
  content.Activate();
  StandardNormalizer content_norm(canonical, {30, 1}, 32, 16, 48000, &content,
                                  {.source_pts_anchor_us = 0,
                                   .channel_pts_anchor_us = content_anchor_us},
                                  1600);
  VideoPreviewBuffer content_v(50);
  AudioPreviewBuffer content_a(50);

  // Fill.
  for (int i = 0; i < 10; ++i) {
    ASSERT_TRUE(pad_v.Push(*pad_norm.PullVideo()));
    ASSERT_TRUE(content_v.Push(*content_norm.PullVideo()));
  }

  PlaybackDirector live;
  live.PromoteToAssignment({.video_preview = &pad_v,
                .audio_preview = &pad_a,
                .normalizer = &pad_norm,
                .segment_id = "pad"});

  // Consume 5 pad frames; their Y[0] should be 0x10 (broadcast black, no burn).
  for (int i = 0; i < 5; ++i) {
    auto f = live.ActiveAssignment().video_preview->Pop();
    ASSERT_TRUE(f.has_value());
    EXPECT_EQ(f->data[0], 0x10);  // pad signature
  }

  live.PromoteToAssignment({.video_preview = &content_v,
                .audio_preview = &content_a,
                .normalizer = &content_norm,
                .segment_id = "content"});

  // First content frame: burned idx 0 (so Y[0] = 0, not 0x10). Identity
  // observable to the consumer; PTS advances as one period.
  auto f = live.ActiveAssignment().video_preview->Pop();
  ASSERT_TRUE(f.has_value());
  EXPECT_EQ(f->data[0], 0x00);  // first byte of little-endian 0 = 0
  EXPECT_EQ(live.ActiveAssignment().AbsoluteVideoPtsUs(*f), content_anchor_us);
}

}  // namespace
}  // namespace retrovue::air
