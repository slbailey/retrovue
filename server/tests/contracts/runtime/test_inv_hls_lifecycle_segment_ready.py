"""Contract tests for INV-HLS-LIFECYCLE-SEGMENT-READY-001.

When no completed HLS segments are available, the manifest endpoint MUST
return 503 + Retry-After. It MUST NOT return an empty playlist.
"""

import ast
import inspect
import textwrap


def _get_register_endpoints_source() -> str:
    from retrovue.runtime.program_director import ProgramDirector

    method = getattr(ProgramDirector, "_register_endpoints")
    return textwrap.dedent(inspect.getsource(method))


def _extract_nested_function_source(parent_source: str, func_name: str) -> str | None:
    tree = ast.parse(parent_source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            lines = parent_source.splitlines()
            raw = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            return textwrap.dedent(raw)
    return None


class TestInvHlsLifecycleSegmentReady001:
    def test_channels_manifest_does_not_emit_empty_playlist_fallback(self):
        """/channels/{id}/live.m3u8 must not synthesize empty playlist on startup."""
        parent_src = _get_register_endpoints_source()
        func_src = _extract_nested_function_source(parent_src, "channels_hls_manifest")
        assert func_src is not None, "channels_hls_manifest() not found"

        forbidden = (
            '"#EXTM3U\\n"',
            '"#EXT-X-TARGETDURATION:1\\n"',
            '"#EXT-X-MEDIA-SEQUENCE:0\\n"',
        )
        for token in forbidden:
            assert token not in func_src, (
                "INV-HLS-LIFECYCLE-SEGMENT-READY-001 violated: "
                "channels_hls_manifest() still contains empty-playlist fallback"
            )

    def test_channels_manifest_returns_503_when_playlist_missing(self):
        """Startup path must include 503 + Retry-After before segments exist."""
        parent_src = _get_register_endpoints_source()
        func_src = _extract_nested_function_source(parent_src, "channels_hls_manifest")
        assert func_src is not None, "channels_hls_manifest() not found"

        assert "if playlist is None:" in func_src, "Missing startup guard for empty playlist"
        assert "status.HTTP_503_SERVICE_UNAVAILABLE" in func_src, (
            "INV-HLS-LIFECYCLE-SEGMENT-READY-001 violated: no 503 on empty playlist"
        )
        assert '"Retry-After": "1"' in func_src or "Retry-After" in func_src, (
            "INV-HLS-LIFECYCLE-SEGMENT-READY-001 violated: 503 must include Retry-After"
        )
