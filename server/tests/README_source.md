Source Tests — Patch Points (Post-Refactor)

Context: Source CLI no longer uses the legacy SourceService. All source commands are now thin wrappers over usecases in src/retrovue/usecases/. Tests must patch those usecases directly.

1. What NOT to patch anymore

❌ retrovue.content_manager.source_service.SourceService
❌ retrovue.cli.commands.source.SourceService
❌ any ...persist_collections() on a service

These were part of the legacy service layer that’s now quarantined.

2. What to patch now (authoritative)

Add

patch("retrovue.usecases.source_add.add_source")

List

patch("retrovue.usecases.source_list.list_sources")

Discover

patch("retrovue.usecases.source_discover.discover_collections")

All CLI tests for source should use one of those three.

3. Assertions to use
   A. source add
   mock_add.assert_called_once()
   mock_add.assert_called_once_with(ANY, source_type="plex", name="My Plex", config=ANY, enrichers=ANY)

And very important:

with patch("retrovue.usecases.source_discover.discover_collections") as mock_discover: # run `source add ...`
mock_discover.assert_not_called()

That enforces “no auto-discovery in add.”

CLI output expectation (adjust to your actual text):

Successfully created plex source: My Plex

or JSON variant.

B. source list
mock_list.assert_called_once_with(ANY, source_type=None)

# or with filter:

mock_list.assert_called_once_with(ANY, source_type="plex")

Then assert on what CLI printed:

rows

headers

or JSON structure if --json

C. source discover
mock_discover.assert_called_once_with(ANY, source_id="123e4567-e89b-12d3-a456-426614174000")

Then assert CLI shows discovered collections, but not that they were persisted.

If you need to test persistence later, that’s a separate usecase (e.g. source_persist_collections.py), not the CLI discover.

4. Quick before/after for tests

Before (legacy):

with patch("retrovue.cli.commands.source.SourceService") as mock_service:
result = runner.invoke(cli, ["source", "add", ...])
mock_service.return_value.discover_collections.assert_called_once()

After (current):

from unittest.mock import ANY, patch

with patch("retrovue.usecases.source_add.add_source") as mock_add, \
 patch("retrovue.usecases.source_discover.discover_collections") as mock_discover:
result = runner.invoke(cli, ["source", "add", "--type", "plex", "--name", "My Plex"])

mock_add.assert_called_once()
mock_discover.assert_not_called()
assert result.exit_code == 0
assert "Successfully created plex source: My Plex" in result.stdout

5. Notes for future tests

Discovery + persistence = 2 nouns → 2 usecases → 2 tests.

Do not hide discovery behind add.

Do not reintroduce SourceService just to make mocks happy — fix the test instead.
