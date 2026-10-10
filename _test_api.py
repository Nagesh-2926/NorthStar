import requests
import json

BASE = "http://127.0.0.1:8001/api"

print("Testing login...")
resp = requests.post(
    f"{BASE}/auth/login",
    json={"email": "demo.coordinator@demo.example.com", "password": "SecurePass1234"}
)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text[:500]}")

if resp.status_code == 200:
    data = resp.json()
    token = data["access_token"]
    print(f"\nGot token: {token[:50]}...")
    
    # Test /api/auth/me
    print("\nTesting /api/auth/me...")
    me_resp = requests.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {token}"})
    print(f"Status: {me_resp.status_code}")
    print(f"Response: {me_resp.text[:500]}")
    
    # Test CSV template download
    print("\nTesting CSV template download...")
    template_resp = requests.get(
        f"{BASE}/imports/template",
        headers={"Authorization": f"Bearer {token}"}
    )
    print(f"Status: {template_resp.status_code}")
    print(f"Content-Type: {template_resp.headers.get('Content-Type')}")
    print(f"Content length: {len(template_resp.content)} bytes")
    
    # Test cluster endpoint with valid student
    print("\nTesting cluster endpoint with valid student...")
    cluster_resp = requests.get(
        f"{BASE}/students/fab2f6d5-c7b1-40ef-a45a-129a2fb4d59d/cluster",
        params={"enrollment_id": "e1289f83-5aba-4a37-8da6-9abab2f9ae13"},
        headers={"Authorization": f"Bearer {token}"}
    )
    print(f"Status: {cluster_resp.status_code}")
    print(f"Response: {cluster_resp.text[:500]}")
    
    # Test cluster endpoint with invalid student (from user's error)
    print("\nTesting cluster endpoint with invalid student...")
    cluster_resp2 = requests.get(
        f"{BASE}/students/80121607-bd6b-4370-9cbc-4153d42f85a8/cluster",
        params={"enrollment_id": "30e72330-146b-4137-846b-798dea6f6b62"},
        headers={"Authorization": f"Bearer {token}"}
    )
    print(f"Status: {cluster_resp2.status_code}")
    print(f"Response: {cluster_resp2.text[:500]}")
else:
    print("Login failed!")
