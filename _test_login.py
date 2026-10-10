"""
Test the login endpoint directly to debug the 401 error.
"""
import requests
import json

BASE = "http://127.0.0.1:8001/api"

# Test 1: Login with correct credentials
print("Test 1: Login with demo.coordinator@demo.example.com / SecurePass1234")
resp = requests.post(
    f"{BASE}/auth/login",
    json={"email": "demo.coordinator@demo.example.com", "password": "SecurePass1234"}
)
print(f"  Status: {resp.status_code}")
print(f"  Response: {resp.text[:500]}")

# Test 2: Login with vinnukanna37@gmail.com
print("\nTest 2: Login with vinnukanna37@gmail.com / SecurePass1234")
resp2 = requests.post(
    f"{BASE}/auth/login",
    json={"email": "vinnukanna37@gmail.com", "password": "SecurePass1234"}
)
print(f"  Status: {resp2.status_code}")
print(f"  Response: {resp2.text[:500]}")

# Test 3: Login with different password
print("\nTest 3: Login with demo.coordinator@demo.example.com / password123")
resp3 = requests.post(
    f"{BASE}/auth/login",
    json={"email": "demo.coordinator@demo.example.com", "password": "password123"}
)
print(f"  Status: {resp3.status_code}")
print(f"  Response: {resp3.text[:500]}")

# Test 4: Login with empty password
print("\nTest 4: Login with demo.coordinator@demo.example.com / (empty)")
resp4 = requests.post(
    f"{BASE}/auth/login",
    json={"email": "demo.coordinator@demo.example.com", "password": ""}
)
print(f"  Status: {resp4.status_code}")
print(f"  Response: {resp4.text[:500]}")

# Test 5: Login with no body
print("\nTest 5: Login with no body")
resp5 = requests.post(f"{BASE}/auth/login")
print(f"  Status: {resp5.status_code}")
print(f"  Response: {resp5.text[:500]}")

# Test 6: Login with form data instead of JSON
print("\nTest 6: Login with form data")
resp6 = requests.post(
    f"{BASE}/auth/login",
    data={"email": "demo.coordinator@demo.example.com", "password": "SecurePass1234"}
)
print(f"  Status: {resp6.status_code}")
print(f"  Response: {resp6.text[:500]}")
