"""
Application layer exports for retrovue_core.

This module provides convenient imports for common services and components.
When PYTHONPATH includes retrovue_core/src and retrovue_core/src_legacy, 
these imports will resolve correctly.
"""

# Re-export ScheduleService
# Prefer the concrete implementation from legacy, fallback to protocol
try:
    # Try the concrete implementation first (from src_legacy)
    from retrovue.schedule_manager.schedule_service import ScheduleService
except ImportError:
    # Fallback to the protocol (from src)
    from retrovue.runtime.channel_manager import ScheduleService

__all__ = ["ScheduleService"]

