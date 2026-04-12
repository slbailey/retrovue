# legacy/ — Quarantined Code

**Status: QUARANTINED**

This directory contains legacy code that is no longer part of the active codebase.
Nothing in this directory should be imported or depended upon by production code.

## Contents

| Directory | Origin | Notes |
|-----------|--------|-------|
| `src_legacy/` | `server/src_legacy/` | Old source tree before hex-arch migration |
| `studio-ui/` | `server/templates/` + `server/static/` | Jinja2 templates and static assets for the old Studio UI |
| `examples/` | `server/examples/` | Example scripts (reference only) |
| `core-proto/` | `server/core/` | Early core protobuf/proto definitions |
| `static/` | `pkg/static/` | Original static assets |
| `example_session.py` | `server/example_session.py` | Example session script |
| `stream_test.py` | `server/stream_test.py` | Legacy stream test |
| `test.py` | `server/test.py` | Legacy test script |

## Policy

- Do **not** import from `legacy/` in any new code.
- The `__init__.py` guard will raise `ImportError` if you try.
- These files are preserved for reference and potential future migration only.
- Removal requires board approval (see RETA-209).
