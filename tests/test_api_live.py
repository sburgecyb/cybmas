import requests
import json

BASE = "http://localhost:8000"

import requests

BASE = "http://localhost:8000"

# Test 1 - Health check
r = requests.get(f"{BASE}/health")
print(f"1. Health: {r.status_code} {r.json()}")

# Test 2 - Login with existing user
r = requests.post(f"{BASE}/api/auth/login", json={
    "email": "testeng@company.com",
    "password": "Test1234!"
})
print(f"2. Login: {r.status_code}")
if r.status_code != 200:
    print(f"   Error: {r.json()}")
    exit(1)

data = r.json()
token = data.get('access_token')
print(f"   Token: {'Yes' if token else 'No'}")
print(f"   Role: {data.get('role')}")

# Test 3 - Get current user
r = requests.get(f"{BASE}/api/auth/me",
    headers={"Authorization": f"Bearer {token}"}
)
print(f"3. Me: {r.status_code} {r.json()}")

# Test 4 - Get sessions
r = requests.get(f"{BASE}/api/sessions",
    headers={"Authorization": f"Bearer {token}"}
)
print(f"4. Sessions: {r.status_code}")

# Test 5 - Wrong password
r = requests.post(f"{BASE}/api/auth/login", json={
    "email": "testeng@company.com",
    "password": "WrongPassword"
})
print(f"5. Wrong password: {r.status_code}")

# Test 6 - No token
r = requests.get(f"{BASE}/api/sessions")
print(f"6. No token: {r.status_code}")

print("\nDone")

# Test 1 - Health check
# r = requests.get(f"{BASE}/health")
# print(f"Health: {r.status_code} {r.json()}")

# # Test 2 - Register a new engineer
# r = requests.post(f"{BASE}/api/auth/register", json={
#     "email": "testeng@company.com",
#     "password": "Test1234!",
#     "full_name": "Test Engineer"
# })
# print(f"Register: {r.status_code} {r.json()}")

# # Test 3 - Login
# r = requests.post(f"{BASE}/api/auth/login", json={
#     "email": "testeng@company.com",
#     "password": "Test1234!"
# })
# print(f"Login: {r.status_code}")
# data = r.json()
# token = data.get('access_token')
# print(f"Token received: {'Yes' if token else 'No'}")
# print(f"Role: {data.get('role')}")

# # Test 4 - Get current user (authenticated)
# r = requests.get(f"{BASE}/api/auth/me",
#     headers={"Authorization": f"Bearer {token}"}
# )
# print(f"Me: {r.status_code} {r.json()}")

# # Test 5 - Get sessions (authenticated)
# r = requests.get(f"{BASE}/api/sessions",
#     headers={"Authorization": f"Bearer {token}"}
# )
# print(f"Sessions: {r.status_code} {r.json()}")

# # Test 6 - Wrong password (expect 401)
# r = requests.post(f"{BASE}/api/auth/login", json={
#     "email": "testeng@company.com",
#     "password": "WrongPassword"
# })
# print(f"Wrong password: {r.status_code} {r.json()}")

# # Test 7 - No token (expect 401)
# r = requests.get(f"{BASE}/api/sessions")
# print(f"No token: {r.status_code}")

# r = requests.get(f"{BASE}/api/auth/me",
#     headers={"Authorization": f"Bearer {token}"}
# )
# print(f"Me status: {r.status_code}")
# print(f"Me response: {r.text}")

# r = requests.get(f"{BASE}/api/sessions")
# print(f"No token: {r.status_code}")

# Add this debug to test_api_live.py temporarily
# import jwt as pyjwt

# # Decode token without verification to see what's inside
# parts = token.split('.')
# import base64, json
# payload_b64 = parts[1] + '=' * (4 - len(parts[1]) % 4)
# payload = json.loads(base64.b64decode(payload_b64))
# print(f"Token sub (email in token): '{payload['sub']}'")

# # Add this to test_api_live.py
# import asyncio
# import asyncpg
# import os
# os.environ['DATABASE_URL'] = 'postgresql+asyncpg://postgres:sa@127.0.0.1:5432/multi_agent'

# async def debug_db():
#     pool = await asyncpg.create_pool(
#         'postgresql://postgres:sa@127.0.0.1:5432/multi_agent'
#     )
#     # Try exact query the /me endpoint uses
#     row = await pool.fetchrow(
#         "SELECT email, full_name, role FROM users WHERE email = $1",
#         'testeng@company.com'
#     )
#     print(f"Direct DB query result: {row}")
    
#     # Try without filter to see all users
#     rows = await pool.fetch("SELECT email, role FROM users")
#     print(f"All users: {[dict(r) for r in rows]}")
#     await pool.close()

#asyncio.run(debug_db())