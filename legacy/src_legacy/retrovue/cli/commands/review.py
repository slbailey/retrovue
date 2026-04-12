"""
Review command group.

Surfaces review queue management capabilities including listing, approval, and rejection.
Calls LibraryService under the hood for all review operations.
"""

from __future__ import annotations

from uuid import UUID

import typer

from ...api.schemas import ReviewQueueListResponse, ReviewQueueSummary
from ...content_manager.library_service import LibraryService
from ...infra.uow import session

app = typer.Typer(name="review", help="Review queue operations using LibraryService")


@app.command("list")
def list_reviews(
    json: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    List items in the review queue.

    Examples:
        retrovue review list
        retrovue review list --json
    """
    with session() as db:
        library_service = LibraryService(db)

        try:
            # Get review queue items
            reviews = library_service.list_review_queue()

            # Convert to response models
            review_summaries = [ReviewQueueSummary.from_orm(review) for review in reviews]
            response = ReviewQueueListResponse(
                reviews=review_summaries, total=len(review_summaries), status_filter=None
            )

            if json:
                import json

                typer.echo(json.dumps(response.model_dump(), indent=2))
            else:
                typer.echo(f"Found {len(review_summaries)} items in review queue")
                for review in review_summaries:
                    typer.echo(
                        f"  {review.id} - Asset {review.asset_id} - {review.reason} (confidence: {review.confidence:.2f})"
                    )

        except Exception as e:
            typer.echo(f"Error listing reviews: {e}", err=True)
            raise typer.Exit(1)


@app.command("resolve")
def resolve_review(
    review_id: str = typer.Argument(..., help="Review ID to resolve"),
    episode_id: str = typer.Argument(..., help="Episode ID to associate"),
    notes: str | None = typer.Option(None, "--notes", help="Resolution notes"),
    json: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Resolve a review queue item.

    Examples:
        retrovue review resolve <review-id> <episode-id>
        retrovue review resolve <review-id> <episode-id> --notes "Manually verified"
    """
    try:
        review_uuid = UUID(review_id)
        episode_uuid = UUID(episode_id)
    except ValueError as e:
        typer.echo(f"Invalid UUID format: {e}", err=True)
        raise typer.Exit(1)

    with session() as db:
        library_service = LibraryService(db)

        try:
            # Resolve the review
            result = library_service.resolve_review(review_uuid, episode_uuid, notes)

            if json:
                import json

                response = {
                    "review_id": str(review_uuid),
                    "episode_id": str(episode_uuid),
                    "notes": notes,
                    "resolved": result,
                }
                typer.echo(json.dumps(response, indent=2))
            else:
                if result:
                    typer.echo(
                        f"Successfully resolved review {review_id} with episode {episode_id}"
                    )
                    if notes:
                        typer.echo(f"Notes: {notes}")
                else:
                    typer.echo(f"Failed to resolve review {review_id}", err=True)
                    raise typer.Exit(1)

        except Exception as e:
            typer.echo(f"Error resolving review: {e}", err=True)
            raise typer.Exit(1)
