from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def _asset(*, state: str, approved: bool, duration_ms: int | None = None):
    return SimpleNamespace(
        uuid=uuid.uuid4(),
        state=state,
        approved_for_broadcast=approved,
        duration_ms=duration_ms,
        is_deleted=False,
    )


class TestCollectionApproveContract:
    def setup_method(self):
        self.runner = CliRunner()

    def test_approve_make_ready_promotes_and_approves(self):
        collection = SimpleNamespace(uuid=uuid.uuid4(), name="commercials")
        promotable = _asset(state="new", approved=False, duration_ms=30000)
        ready_unapproved = _asset(state="ready", approved=False, duration_ms=30000)

        with patch("retrovue.cli.commands.collection.session") as session_ctx, patch(
            "retrovue.cli.commands.collection.resolve_container_selector"
        ) as resolve:
            db = MagicMock()
            session_ctx.return_value.__enter__.return_value = db
            resolve.return_value = collection

            q_promotable = MagicMock()
            q_promotable.filter.return_value.all.return_value = [promotable]

            q_approvable = MagicMock()
            q_approvable.filter.return_value.all.return_value = [ready_unapproved]

            q_skipped = MagicMock()
            q_skipped.filter.return_value.count.return_value = 0

            db.query.side_effect = [q_promotable, q_skipped, q_approvable]

            result = self.runner.invoke(
                app,
                ["container", "approve", "commercials", "--make-ready", "--json"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["collection"] == "commercials"
        assert payload["promoted_to_ready"] == 1
        assert payload["approved"] == 1
        assert promotable.state == "ready"
        assert ready_unapproved.approved_for_broadcast is True

    def test_approve_without_make_ready_does_not_promote_new_assets(self):
        collection = SimpleNamespace(uuid=uuid.uuid4(), name="commercials")
        promotable = _asset(state="new", approved=False, duration_ms=30000)
        ready_unapproved = _asset(state="ready", approved=False, duration_ms=30000)

        with patch("retrovue.cli.commands.collection.session") as session_ctx, patch(
            "retrovue.cli.commands.collection.resolve_container_selector"
        ) as resolve:
            db = MagicMock()
            session_ctx.return_value.__enter__.return_value = db
            resolve.return_value = collection

            q_promotable = MagicMock()
            q_promotable.filter.return_value.all.return_value = [promotable]

            q_approvable = MagicMock()
            q_approvable.filter.return_value.all.return_value = [ready_unapproved]

            q_skipped = MagicMock()
            q_skipped.filter.return_value.count.return_value = 1

            db.query.side_effect = [q_promotable, q_skipped, q_approvable]

            result = self.runner.invoke(
                app,
                ["container", "approve", "commercials", "--json"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["promoted_to_ready"] == 0
        assert payload["approved"] == 1
        assert promotable.state == "new"
        assert ready_unapproved.approved_for_broadcast is True

    def test_approve_make_ready_approves_promoted_assets_in_single_run(self):
        collection = SimpleNamespace(uuid=uuid.uuid4(), name="bumpers")
        promotable = _asset(state="new", approved=False, duration_ms=74210)

        with patch("retrovue.cli.commands.collection.session") as session_ctx, patch(
            "retrovue.cli.commands.collection.resolve_container_selector"
        ) as resolve:
            db = MagicMock()
            session_ctx.return_value.__enter__.return_value = db
            resolve.return_value = collection

            q_promotable = MagicMock()
            q_promotable.filter.return_value.all.return_value = [promotable]

            q_skipped = MagicMock()
            q_skipped.filter.return_value.count.return_value = 1

            # After promotion, this query should include the promoted asset.
            q_approvable = MagicMock()
            q_approvable.filter.return_value.all.return_value = [promotable]

            db.query.side_effect = [q_promotable, q_skipped, q_approvable]

            result = self.runner.invoke(
                app,
                ["container", "approve", "bumpers", "--make-ready", "--json"],
            )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["promoted_to_ready"] == 1
        assert payload["approved"] == 1
        assert promotable.state == "ready"
        assert promotable.approved_for_broadcast is True
