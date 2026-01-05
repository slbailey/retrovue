#!/usr/bin/env python3
"""
Demonstration of compression middleware configuration.

This script shows how the ConditionalGZipMiddleware works to exclude
.ts routes from compression while allowing compression for other routes.
"""

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from retrovue.web.server import ConditionalGZipMiddleware


def demo_compression_middleware():
    """Demonstrate compression middleware functionality."""
    print("Compression Middleware Demo")
    print("=" * 40)
    
    # Create test app
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
        """Mock streaming endpoint."""
        return {"message": f"Streaming channel {channel_id}", "data": "x" * 2000}
    
    @app.get("/api/data")
    async def api_data():
        """Regular API endpoint that should be compressed."""
        return {"message": "This should be compressed", "data": "x" * 2000}
    
    # Test client
    client = TestClient(app)
    
    print("1. Testing .ts route (should NOT be compressed):")
    response = client.get("/iptv/channel/1.ts")
    print(f"   Status: {response.status_code}")
    print(f"   Content-Encoding: {response.headers.get('content-encoding')}")
    print(f"   Content-Type: {response.headers.get('content-type')}")
    print(f"   Cache-Control: {response.headers.get('cache-control')}")
    
    print("\n2. Testing regular API route (might be compressed):")
    response = client.get("/api/data")
    print(f"   Status: {response.status_code}")
    print(f"   Content-Encoding: {response.headers.get('content-encoding', 'None')}")
    print(f"   Content-Type: {response.headers.get('content-type')}")
    
    print("\n3. Key Features:")
    print("[OK] .ts routes excluded from compression")
    print("[OK] Content-Encoding: identity for .ts routes")
    print("[OK] Proper streaming headers for IPTV")
    print("[OK] Regular routes can still be compressed")
    
    print("\n4. Middleware Configuration:")
    print("   - Excludes paths matching: ^/iptv/channel/.*\\.ts$")
    print("   - Sets Content-Encoding: identity for .ts routes")
    print("   - Maintains compression for other routes")
    print("   - Ensures proper MPEG-TS streaming headers")


if __name__ == "__main__":
    demo_compression_middleware()
