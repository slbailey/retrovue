# Channel manager (redirect)

This document has been consolidated into:

- [Channel manager](channel_manager.md)
3. Last viewer leaving triggers:
   - Graceful teardown of ffmpeg.
   - ChannelManager remains idle, but the Channel timeline itself keeps logically advancing in the database.

**Asset State Enforcement**: The Producer only considers assets with `state='ready'` and `approved_for_broadcast=true` when building playout plans. Assets in other states are invisible to the runtime layer.

## Failure / fallback behavior

- If a playout enricher fails, ChannelManager uses the last valid version of the playout plan without that enricher.
- If ffmpeg crashes mid-stream, ChannelManager can attempt to rebuild the current playout plan and relaunch.
- Failure to launch should be logged and surfaced to operators.

## Naming rules

- "Channel" is the persistent logical feed.
- "ChannelManager" is the runtime controller for that Channel.
- "viewer count" means connected consumers for that Channel right now, not general audience metrics.

See also:

- [Playout pipeline](../domain/PlayoutPipeline.md)
- [Producer lifecycle](ProducerLifecycle.md)
- [As-run logging](AsRunLogging.md)
  \_For CLI commands, refer to the [CLI contract](../contracts/resources/README.md).
