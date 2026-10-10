"""
Test login directly through the ASGI app, bypassing HTTP layer.
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app.main import create_app
from backend.app.core.config import Settings

# Create the app
settings = Settings()
app = create_app(settings)

# Test login through the app directly
async def test_login():
    from httpx import ASGITransport, AsyncClient
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test login
        resp = await client.post("/api/auth/login", json={
            "email": "coordinator@example.com",
            "password": "SecurePass1234"
        })
        print(f"Login status: {resp.status_code}")
        print(f"Login response: {resp.text[:500]}")
        
        if resp.status_code == 200:
            data = resp.json()
            token = data["access_token"]
            
            # Test /api/auth/me
            me_resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            print(f"\n/api/auth/me status: {me_resp.status_code}")
            print(f"Response: {me_resp.text[:500]}")
            
            # Test CSV template
            template_resp = await client.get("/imports/template", headers={"Authorization": f"Bearer {token}"})
            print(f"\nTemplate status: {template_resp.status_code}")
            print(f"Content length: {len(template_resp.content)} bytes")

asyncio.run(test_login())
