"""Dev harness modules — mock schedule services, stub resolvers, fake sources.

These classes support CLI dev modes (--mock-schedule-ab, --mock-schedule-grid)
and operator preview commands. They implement production protocols but are not
production services. They live here (not in runtime/) to satisfy
INV-PRODUCTION-BOUNDARY-001.
"""
