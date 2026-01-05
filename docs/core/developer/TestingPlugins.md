_Related: [Plugin authoring](PluginAuthoring.md) • [Registry API](RegistryAPI.md) • [Runtime: Producer lifecycle](../runtime/ProducerLifecycle.md)_

# Testing plugins

## Purpose

Give plugin authors a repeatable way to verify their plugin works before deploying it in a real RetroVue environment.

## Testing importer (Source) plugins

- Call the importer's `list_collections()` with a known config and confirm it returns stable identifiers and paths.
- Call `discover()` and confirm it returns DiscoveredItem objects with enough metadata for ingest.
- Run `retrovue source add --type <yourtype> --help` and confirm your parameter spec renders correctly.

## Testing enricher plugins

- Feed a representative DiscoveredItem (for ingest scope) or playout plan (for playout scope) into your `apply()` method.
- Confirm:
  - You return the modified object.
  - You do not persist anywhere.
  - You tolerate missing fields gracefully.
- Intentionally throw an error in `apply()` and confirm the orchestration layer logs the failure and continues.

## Testing producer plugins

- Call your `build_playout_plan(now, channel_config, schedule_context)` with:
  - A simulated schedule_context that represents "show is already halfway through."
  - Edge case: no scheduled content.
- Confirm:
  - You generate ordered segments with offsets.
  - You do not launch ffmpeg.
  - You do not apply channel branding; that's a playout enricher job.

## Integration smoke test

- Configure a Source, Collection, Enricher, Producer, and Channel using the CLI against a dev environment.
- Tune in to the Channel and confirm:
  - The Producer gets called.
  - The playout enrichers run in priority order.
  - ChannelManager launches ffmpeg with your final plan.
  - Nothing crashes if you disconnect the only viewer.

See also:

- [Registry API](RegistryAPI.md)
- [Producer lifecycle](../runtime/ProducerLifecycle.md)
- [Channel manager](../runtime/ChannelManager.md)
