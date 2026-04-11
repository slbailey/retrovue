"""
Stub Enricher Registry for CLI contract compliance.

This provides minimal implementations to satisfy the CLI help surface requirements.
"""


def list_enricher_types():
    """List all available enricher types."""
    return [
        {
            "type": "ingest",
            "description": "Enrichers that run during content ingestion to add value to assets",
            "available": True,
        },
        {
            "type": "playout",
            "description": "Enrichers that run during playout to add value to content being broadcast",
            "available": True,
        },
        {
            "type": "tvdb",
            "description": "TheTVDB metadata enrichment for TV shows and episodes",
            "available": True,
        },
        {
            "type": "tmdb",
            "description": "TMDB metadata enrichment for movies and TV shows",
            "available": True,
        },
        {
            "type": "watermark",
            "description": "Watermark overlay enricher for adding logos to content",
            "available": True,
        },
        {
            "type": "crossfade",
            "description": "Crossfade transition enricher for smooth content transitions",
            "available": True,
        },
        {
            "type": "llm",
            "description": "LLM-based enrichment for AI-powered content analysis",
            "available": True,
        },
        {
            "type": "ffmpeg",
            "description": "FFmpeg-based video analysis and processing",
            "available": True,
        },
        {
            "type": "ffprobe",
            "description": "FFprobe-based media analysis and metadata extraction",
            "available": True,
        },
    ]


def get_enricher_help(enricher_type):
    """Get help information for a specific enricher type."""
    help_info = {
        "ingest": {
            "description": "Enrichers that run during content ingestion to add value to assets",
            "required_params": [
                {"name": "name", "description": "Human-readable label for this enricher"}
            ],
            "optional_params": [
                {
                    "name": "config",
                    "description": "JSON configuration for the enricher",
                    "default": "{}",
                }
            ],
            "examples": [
                "retrovue enricher add --type ingest --name 'Video Analysis'",
                'retrovue enricher add --type ingest --name \'Metadata Enrichment\' --config \'{"sources": ["imdb", "tmdb"]}\'',
            ],
        },
        "playout": {
            "description": "Enrichers that run during playout to add value to content being broadcast",
            "required_params": [
                {"name": "name", "description": "Human-readable label for this enricher"}
            ],
            "optional_params": [
                {
                    "name": "config",
                    "description": "JSON configuration for the enricher",
                    "default": "{}",
                }
            ],
            "examples": [
                "retrovue enricher add --type playout --name 'Channel Branding'",
                "retrovue enricher add --type playout --name 'Overlay Processing' --config '{\"overlay_type\": \"watermark\"}'",
            ],
        },
    }

    return help_info.get(
        enricher_type,
        {
            "description": f"Unknown enricher type: {enricher_type}",
            "required_params": [],
            "optional_params": [],
            "examples": [],
        },
    )
