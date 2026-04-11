"""
Logging configuration for Retrovue.

This module configures structlog for JSON logging across the application.
"""

import re
from typing import Any

import structlog

from .settings import settings


def redact_secrets(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive information from log events."""
    # List of keys that contain secrets
    secret_keys = [
        "PLEX_TOKEN",
        "plex_token",
        "token",
        "password",
        "secret",
        "api_key",
        "connection_string",
        "database_url",
    ]

    # Patterns to redact in string values
    secret_patterns = [
        r"://[^:]+:[^@]+@",  # URLs with credentials
        r"token=[^&\s]+",  # Token parameters
        r"password=[^&\s]+",  # Password parameters
    ]

    def redact_value(value: Any) -> Any:
        if isinstance(value, str):
            # Check if the key suggests this is a secret
            for pattern in secret_patterns:
                value = re.sub(pattern, lambda m: m.group(0).split("=")[0] + "=***", value)
            return value
        elif isinstance(value, dict):
            return {k: redact_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [redact_value(item) for item in value]
        return value

    # Redact based on key names
    for key in list(event_dict.keys()):
        if any(secret in key.lower() for secret in secret_keys):
            event_dict[key] = "***REDACTED***"
        else:
            event_dict[key] = redact_value(event_dict[key])

    return event_dict


def configure_logging() -> None:
    """Configure structlog for JSON logging."""
    # Configure structlog with JSON output by default
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            redact_secrets,  # Redact secrets before rendering
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a configured logger with service context."""
    logger = structlog.get_logger(name)
    return logger.bind(
        service="retrovue",
        env=settings.env,
        request_id=None,  # Will be set by middleware
    )
