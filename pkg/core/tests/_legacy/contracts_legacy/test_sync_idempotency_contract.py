"""
Contract tests for catalog sync idempotency.

These tests MUST enforce the rules defined in docs/contracts/SyncIdempotency.md.
Do not change behavior. If behavior needs to change, update the contract first.

Implementation rules:
- Use real test DB/session fixtures (see tests/conftest.py and tests/contracts/test_collection_wipe_contract.py).
- Use run_cli(...) from tests/cli/utils.py to invoke the real CLI command.
- Do NOT mock the whole DB session. Only stub the provider boundary.
- Do NOT invent new models or new modules. If something is missing, leave a TODO.
"""

import pytest
from tests.cli.utils import run_cli

from retrovue.domain import entities


@pytest.mark.asyncio
async def test_sync_creates_asset_once(test_db_session, monkeypatch):
    """
    First-time import creates exactly one entities.Asset (a discovered media file we can eventually air)
    and exactly one entities.ProviderRef linking the provider GUID to that Asset.

    Steps:
    1. Mock provider to return one new item A.
    2. Run sync via CLI.
    3. Assert DB now has exactly one Asset row and exactly one ProviderRef row for that item.
    4. Assert the Asset is linked to a SourceCollection.
    5. If metadata is incomplete, assert it was added to ReviewQueue exactly once.

    NOTE: We currently don't have a public "fetch provider items" function exposed.
    We'll stub that with monkeypatch once that function exists.
    """

    # TODO: monkeypatch the provider-facing fetch used by the sync command
    # e.g. monkeypatch.setattr(
    #     "retrovue.ingest.plex.fetch_items_for_collection",
    #     lambda collection_id: [
    #         {
    #             "provider_key": "plex://abc123",
    #             "uri": "/mnt/media/Batman_Ep3.mkv",
    #             "duration_ms": 1320000,
    #         }
    #     ],
    #     raising=False,
    # )

    # NOTE: This assumes the sync supports --collection-id <uuid>
    # If the CLI argument name changes, update this test AND update the contract doc.
    # Run sync (first discovery)
    result = run_cli(["source", "sync", "--collection-id", "1"])
    assert result.exit_code == 0

    # Query post-sync state
    assets = list(test_db_session.query(entities.Asset).all())
    provider_refs = list(test_db_session.query(entities.ProviderRef).all())
    source_collections = list(test_db_session.query(entities.SourceCollection).all())
    review_queue = list(test_db_session.query(entities.ReviewQueue).all())

    # We expect exactly one Asset for that item
    assert len(assets) == 1

    # We expect exactly one ProviderRef pointing at that Asset
    assert len(provider_refs) == 1
    assert provider_refs[0].asset_id == assets[0].id

    # The Asset should belong to a SourceCollection
    assert assets[0].collection_id is not None
    assert source_collections, "expected at least one SourceCollection after sync"

    # ReviewQueue should contain at most one row for that Asset
    assert len(review_queue) <= 1
    if review_queue:
        assert review_queue[0].asset_id == assets[0].id


@pytest.mark.asyncio
async def test_sync_is_idempotent_without_changes(test_db_session, monkeypatch):
    """
    Running sync twice in a row with the same upstream data is a no-op.

    Steps:
    1. Mock provider to return item A.
    2. Run sync.
    3. Snapshot DB counts.
    4. Run sync again with identical mock.
    5. Assert counts did not increase.
    6. Assert we did NOT create duplicate ProviderRefs for the same provider_key.
    """

    # TODO: monkeypatch provider fetch same as above

    # First sync
    first = run_cli(["source", "sync", "--collection-id", "1"])
    assert first.exit_code == 0

    assets_after_first = list(test_db_session.query(entities.Asset).all())
    provider_refs_after_first = list(test_db_session.query(entities.ProviderRef).all())
    review_after_first = list(test_db_session.query(entities.ReviewQueue).all())

    # Second sync (no changes upstream)
    second = run_cli(["source", "sync", "--collection-id", "1"])
    assert second.exit_code == 0

    assets_after_second = list(test_db_session.query(entities.Asset).all())
    provider_refs_after_second = list(test_db_session.query(entities.ProviderRef).all())
    review_after_second = list(test_db_session.query(entities.ReviewQueue).all())

    # No new Assets or ProviderRefs or ReviewQueue rows
    assert len(assets_after_second) == len(assets_after_first)
    assert len(provider_refs_after_second) == len(provider_refs_after_first)
    assert len(review_after_second) == len(review_after_first)

    # No duplicate ProviderRefs for the same provider_key
    external_ids = [ref.provider_key for ref in provider_refs_after_second]
    assert external_ids.count("plex://abc123") == 1


@pytest.mark.asyncio
async def test_sync_updates_metadata_in_place(test_db_session, monkeypatch):
    """
    Changed upstream metadata updates the existing row, not create a new row.

    Steps:
    1. Mock provider first run: item A title = "Batman Ep3".
    2. Run sync.
    3. Mock provider second run: same provider_key, new title
       "Batman: The Animated Series S01E03".
    4. Run sync again.
    5. Assert DB still has ONE ProviderRef for that provider_key.
    6. Assert the associated Title/Episode/Asset metadata was updated in-place,
       not by creating a second Asset.
    """

    # TODO: monkeypatch provider fetch for first run returning "Batman Ep3"

    first = run_cli(["source", "sync", "--collection-id", "1"])
    assert first.exit_code == 0

    refs_before = list(test_db_session.query(entities.ProviderRef).all())
    assets_before = list(test_db_session.query(entities.Asset).all())
    # TODO: capture the asset/title/episode identity here so we can compare later

    # TODO: monkeypatch provider fetch for second run returning updated title

    second = run_cli(["source", "sync", "--collection-id", "1"])
    assert second.exit_code == 0

    refs_after = list(test_db_session.query(entities.ProviderRef).all())
    assets_after = list(test_db_session.query(entities.Asset).all())

    # Still only one ProviderRef for that provider_key
    assert len(refs_after) == len(refs_before)

    # We did not create a duplicate Asset to represent the rename
    assert len(assets_after) == len(assets_before)

    # TODO: fetch the same asset row again and assert its metadata/title/etc
    #       was updated to "Batman: The Animated Series S01E03"


@pytest.mark.asyncio
async def test_sync_marks_unavailable_but_does_not_delete(test_db_session, monkeypatch):
    """
    Missing upstream item is not hard-deleted.

    Steps:
    1. Mock provider first run: item A exists.
    2. Run sync.
    3. Mock provider second run: item A is missing.
    4. Run sync again.
    5. Assert A's Asset still exists in DB.
    6. Assert we did NOT create a second ProviderRef or second Asset to 'replace' it.
    7. (Future) Assert the Asset is marked inactive/soft-deleted/etc., not purged.
    """

    # TODO: monkeypatch provider fetch first run with item A present

    first = run_cli(["source", "sync", "--collection-id", "1"])
    assert first.exit_code == 0

    refs_before = list(test_db_session.query(entities.ProviderRef).all())
    assets_before = list(test_db_session.query(entities.Asset).all())

    # TODO: monkeypatch provider fetch second run with item A missing

    second = run_cli(["source", "sync", "--collection-id", "1"])
    assert second.exit_code == 0

    refs_after = list(test_db_session.query(entities.ProviderRef).all())
    assets_after = list(test_db_session.query(entities.Asset).all())

    # Asset from run #1 should still exist (we didn't purge it)
    assert len(assets_after) == len(assets_before)

    # We also should not have created new ProviderRefs to represent a "replacement"
    assert len(refs_after) == len(refs_before)

    # TODO: Once sync sets is_deleted / canonical=False / etc. for missing upstream items,
    # assert that here. For now we just assert it wasn't hard-deleted.
