"""
Debug the HTTP login request with verbose logging.
"""
import requests
import json

BASE = "http://127.0.0.1:8001/api"

# Test with different email formats
tests = [
    ("coordinator@example.com", "SecurePass1234"),
    ("demo.coordinator@demo.example.com", "SecurePass1234"),
    ("vinnukanna37@gmail.com", "SecurePass1234"),
]

for email, password in tests:
    print(f"\nTesting: {email} / {password}")
    resp = requests.post(
        f"{BASE}/auth/login",
        json={"email": email, "password": password}
    )
    print(f"  Status: {resp.status_code}")
    print(f"  Response: {resp.text[:300]}")
    
    if resp.status_code == 200:
        token = resp.json()["access_token"]
        print(f"  Got token: {token[:50]}...")
        
        # Test /api/auth/me
        me_resp = requests.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {token}"})
        print(f"  /api/auth/me: {me_resp.status_code}")
        if me_resp.status_code == 200:
            print(f"  User: {me_resp.json()}")
        break
