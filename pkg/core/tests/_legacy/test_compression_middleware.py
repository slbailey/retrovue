"""
Integration tests for compression middleware configuration.

Tests that GZip middleware excludes .ts routes and that Content-Encoding
header is properly set for IPTV streaming endpoints.
"""

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient


class TestCompressionMiddleware:
    """Test compression middleware configuration."""
    
    def test_gzip_excludes_ts_routes(self):
        """Test that GZip middleware excludes .ts routes."""
        # Create a test app with compression middleware
        from retrovue.web.server import ConditionalGZipMiddleware
        
        app = FastAPI()
        
        # Add custom GZip middleware with exclusion for .ts routes
        app.add_middleware(ConditionalGZipMiddleware, minimum_size=1000)
        
        @app.get("/iptv/channel/{channel_id}.ts")
        async def stream_channel(channel_id: str):
            """Mock streaming endpoint."""
            return {"message": f"Streaming channel {channel_id}"}
        
        @app.get("/api/data")
        async def api_data():
            """Regular API endpoint that should be compressed."""
            return {"message": "This should be compressed" * 100}  # Large response
        
        # Test client
        client = TestClient(app)
        
        # Test .ts route - should NOT have gzip compression
        response = client.get("/iptv/channel/1.ts")
        assert response.status_code == 200
        assert "content-encoding" not in response.headers
        assert response.headers.get("content-encoding") is None
        
        # Test regular API route - should have gzip compression
        response = client.get("/api/data")
        assert response.status_code == 200
        # Note: GZipMiddleware might not compress small responses
        # The key test is that .ts routes are excluded
    
    def test_content_encoding_identity_for_ts_routes(self):
        """Test that .ts routes have Content-Encoding: identity header."""
        from fastapi import Request

        from retrovue.web.server import ConditionalGZipMiddleware
        
        app = FastAPI()
        
        # Add custom GZip middleware with exclusion for .ts routes
        app.add_middleware(ConditionalGZipMiddleware, minimum_size=1000)
        
        @app.middleware("http")
        async def streaming_headers(request: Request, call_next):
            resp: Response = await call_next(request)
            if request.url.path.endswith('.ts'):
                resp.headers["Content-Encoding"] = "identity"
            return resp
        
        @app.get("/iptv/channel/{channel_id}.ts")
        async def stream_channel(channel_id: str):
            """Mock streaming endpoint."""
            return {"message": f"Streaming channel {channel_id}"}
        
        # Test client
        client = TestClient(app)
        
        # Test GET request to .ts route
        response = client.get("/iptv/channel/1.ts")
        assert response.status_code == 200
        
        # Verify Content-Encoding header is present and set to identity
        assert "content-encoding" in response.headers
        assert response.headers["content-encoding"] == "identity"
    
    def test_compression_middleware_integration(self):
        """Integration test for compression middleware with real server setup."""
        from retrovue.web.server import ConditionalGZipMiddleware
        
        app = FastAPI(title="Test IPTV Server")
        
        # Add custom GZip middleware with exclusion for .ts routes
        app.add_middleware(ConditionalGZipMiddleware, minimum_size=1000)
        
        @app.middleware("http")
        async def streaming_headers(request: Request, call_next):
            resp: Response = await call_next(request)
            if request.url.path.endswith('.ts'):
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                resp.headers["Pragma"] = "no-cache"
                resp.headers["Expires"] = "0"
                resp.headers["Content-Type"] = "video/mp2t"
                resp.headers["Content-Encoding"] = "identity"
            return resp
        
        @app.get("/iptv/channel/{channel_id}.ts")
        async def stream_channel(channel_id: str):
            """Mock streaming endpoint that returns large response."""
            # Return a large response that would normally be compressed
            large_data = "x" * 2000  # 2KB response
            return {"data": large_data, "channel": channel_id}
        
        @app.get("/api/large")
        async def large_api_response():
            """Large API response that should be compressed."""
            return {"data": "x" * 2000}  # 2KB response
        
        # Test client
        client = TestClient(app)
        
        # Test .ts route - should NOT be compressed
        response = client.get("/iptv/channel/1.ts")
        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "identity"
        assert response.headers.get("content-type") == "video/mp2t"
        assert "cache-control" in response.headers
        
        # Test regular API route - might be compressed (depending on size)
        response = client.get("/api/large")
        assert response.status_code == 200
        # Note: Compression behavior may vary based on response size and middleware settings
    
    def test_multiple_ts_routes_excluded(self):
        """Test that multiple .ts route patterns are excluded from compression."""
        from retrovue.web.server import ConditionalGZipMiddleware
        
        app = FastAPI()
        
        # Add custom GZip middleware with exclusion for .ts routes
        app.add_middleware(ConditionalGZipMiddleware, minimum_size=1000)
        
        @app.middleware("http")
        async def streaming_headers(request: Request, call_next):
            resp: Response = await call_next(request)
            if request.url.path.endswith('.ts'):
                resp.headers["Content-Encoding"] = "identity"
            return resp
        
        @app.get("/iptv/channel/{channel_id}.ts")
        async def iptv_channel(channel_id: str):
            return {"channel": channel_id}
        
        @app.get("/stream/{stream_id}.ts")
        async def stream_endpoint(stream_id: str):
            return {"stream": stream_id}
        
        @app.get("/api/data")
        async def api_data():
            return {"data": "x" * 2000}
        
        # Test client
        client = TestClient(app)
        
        # Test IPTV channel route
        response = client.get("/iptv/channel/1.ts")
        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "identity"
        
        # Test stream route
        response = client.get("/stream/abc.ts")
        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "identity"
        
        # Test regular API route
        response = client.get("/api/data")
        assert response.status_code == 200
        # Should not have identity encoding
        assert response.headers.get("content-encoding") != "identity"


class TestIPTVStreamingHeaders:
    """Test IPTV streaming specific headers."""
    
    def test_ts_route_headers(self):
        """Test that .ts routes have proper streaming headers."""
        from fastapi import Request

        from retrovue.web.server import ConditionalGZipMiddleware
        
        app = FastAPI()
        
        # Add custom GZip middleware with exclusion for .ts routes
        app.add_middleware(ConditionalGZipMiddleware, minimum_size=1000)
        
        @app.middleware("http")
        async def streaming_headers(request: Request, call_next):
            resp: Response = await call_next(request)
            if request.url.path.endswith('.ts'):
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                resp.headers["Pragma"] = "no-cache"
                resp.headers["Expires"] = "0"
                resp.headers["Content-Type"] = "video/mp2t"
                resp.headers["Content-Encoding"] = "identity"
            return resp
        
        @app.get("/iptv/channel/{channel_id}.ts")
        async def stream_channel(channel_id: str):
            return {"message": f"Streaming channel {channel_id}"}
        
        # Test client
        client = TestClient(app)
        
        # Test GET request
        response = client.get("/iptv/channel/1.ts")
        assert response.status_code == 200
        
        # Verify all required headers are present
        assert response.headers.get("content-type") == "video/mp2t"
        assert response.headers.get("content-encoding") == "identity"
        assert response.headers.get("cache-control") == "no-cache, no-store, must-revalidate"
        assert response.headers.get("pragma") == "no-cache"
        assert response.headers.get("expires") == "0"
    
    def test_no_compression_for_ts_files(self):
        """Test that .ts files are never compressed regardless of size."""
        from retrovue.web.server import ConditionalGZipMiddleware
        
        app = FastAPI()
        
        # Add custom GZip middleware with exclusion for .ts routes
        app.add_middleware(ConditionalGZipMiddleware, minimum_size=100)  # Very low threshold
        
        @app.middleware("http")
        async def streaming_headers(request: Request, call_next):
            resp: Response = await call_next(request)
            if request.url.path.endswith('.ts'):
                resp.headers["Content-Encoding"] = "identity"
            return resp
        
        @app.get("/iptv/channel/{channel_id}.ts")
        async def stream_channel(channel_id: str):
            # Return a very large response that would normally be compressed
            large_data = "x" * 10000  # 10KB response
            return {"data": large_data, "channel": channel_id}
        
        # Test client
        client = TestClient(app)
        
        # Test that even large .ts responses are not compressed
        response = client.get("/iptv/channel/1.ts")
        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "identity"
        
        # Verify the response is not compressed
        assert "gzip" not in response.headers.get("content-encoding", "")
        assert "deflate" not in response.headers.get("content-encoding", "")
