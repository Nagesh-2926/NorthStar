"""
Test all endpoints through ASGI app.
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app.main import create_app
from backend.app.core.config import Settings

app = create_app(Settings())

async def test_all():
    from httpx import ASGITransport, AsyncClient
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test login
        resp = await client.post("/api/auth/login", json={
            "email": "coordinator@example.com",
            "password": "SecurePass1234"
        })
        print(f"Login: {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"Response: {resp.text}")
            return
        
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Test various endpoints
        endpoints = [
            ("GET", "/api/auth/me", None),
            ("GET", "/api/imports/template", None),
            ("GET", "/api/students/fab2f6d5-c7b1-40ef-a45a-129a2fb4d59d/cluster?enrollment_id=e1289f83-5aba-4a37-8da6-9abab2f9ae13", None),
            ("GET", "/api/students/80121607-bd6b-4370-9cbc-4153d42f85a8/cluster?enrollment_id=30e72330-146b-4137-846b-798dea6f6b62", None),
            ("GET", "/api/clusters", None),
            ("GET", "/api/analytics/clusters", None),
        ]
        
        for method, path, _ in endpoints:
            if method == "GET":
                r = await client.get(path, headers=headers)
            print(f"  {method} {path}: {r.status_code} ({len(r.content)} bytes)")
            if r.status_code != 200:
                print(f"    Response: {r.text[:200]}")

asyncio.run(test_all())
