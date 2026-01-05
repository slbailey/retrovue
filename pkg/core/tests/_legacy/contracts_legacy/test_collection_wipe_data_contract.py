"""
Data integrity contract tests for `collection wipe`.

These tests guarantee that destructive wipes:
- delete only assets that belong to the targeted SourceCollection,
- leave other collections' assets alone,
- preserve shared assets,
- clean up dependent rows (ProviderRef, ReviewQueue),
- and do not leave dangling references.

See docs/contracts/resources/CollectionWipeContract.md for the source of truth.
Behavior MUST NOT change without updating that contract first.
"""

import pytest


@pytest.mark.asyncio
async def test_wipe_removes_assets_belonging_to_collection(test_db_session, monkeypatch):
    """
    Wiping collection A MUST remove assets that belong ONLY to collection A,
    along with their ProviderRef, ReviewQueue, EpisodeAsset links.

    Belonging to collection A means:
    - Asset.collection_id == A.id
    OR
    - Asset path matches A's PathMapping.local_path

    After wipe:
    - Those assets are gone.
    - Dependent rows referring to those assets are gone.
    """
    # TODO: set up fixture data in test_db_session:
    # 1. Create SourceCollection A
    # 2. Create Asset X that clearly belongs to A (collection_id or path mapping)
    # 3. Create ProviderRef, ReviewQueue, EpisodeAsset rows for X
    # 4. Commit

    # TODO: run destructive wipe via CLI:
    # result = run_cli(["collection", "wipe", <A name or id>, "--force"])
    # assert result.exit_code == 0

    # TODO: assert post-wipe state:
    # - Asset X no longer exists
    # - ProviderRef for X no longer exists
    # - ReviewQueue for X no longer exists
    # - EpisodeAsset rows for X no longer exist
    pass


@pytest.mark.asyncio
async def test_wipe_does_not_affect_other_collections(test_db_session, monkeypatch):
    """
    Wiping collection A MUST NOT delete assets that belong to another collection B.

    After wipe(A):
    - Assets that belong to B are still present.
    - ProviderRef/ReviewQueue for B's assets still exist.
    """
    # TODO: fixture:
    # - SourceCollection A
    # - SourceCollection B
    # - Asset X belongs to A only
    # - Asset Y belongs to B only
    # Commit.

    # TODO: wipe A

    # TODO: assert:
    # - Asset X is gone
    # - Asset Y is still in entities.Asset
    # - ProviderRef/ReviewQueue for Y are still present
    pass


@pytest.mark.asyncio
async def test_wipe_does_not_delete_shared_metadata(test_db_session, monkeypatch):
    """
    If an Asset is effectively shared (e.g. mapped under both collections,
    or referenced by multiple collections through EpisodeAsset), wiping one
    collection MUST NOT delete that Asset.

    After wipe(A):
    - Shared assets remain
    - ProviderRefs/ReviewQueue for shared assets remain
    """
    # TODO: fixture:
    # - Collection A
    # - Collection B
    # - Asset S linked/attached/shared between both (e.g. same Asset appears in both)
    # - Asset U belongs only to A
    # Commit.

    # TODO: wipe A

    # TODO: assert:
    # - Asset U is gone
    # - Asset S is still present
    pass


@pytest.mark.asyncio
async def test_wipe_cleans_review_queue_entries(test_db_session, monkeypatch):
    """
    After wipe(A):
    - ReviewQueue MUST NOT contain entries for assets that were deleted.
    - No dangling ReviewQueue rows pointing to non-existent Assets.
    """
    # TODO: fixture:
    # - Collection A
    # - Asset X in A
    # - ReviewQueue entry for X
    # - Commit.

    # TODO: wipe A

    # TODO: assert:
    # - ReviewQueue no longer references X
    pass
