import requests
import json

BASE = "http://localhost:8005"

# Test 1 - Health check
r = requests.get(f"{BASE}/health")
print(f"Health: {r.status_code} {r.json()}")

# Test 2 - Invalid signature (expect 401)
r = requests.post(
    f"{BASE}/webhook/jira",
    json={
        "webhookEvent": "jira:issue_created",
        "issue": {
            "key": "B1-1001",
            "fields": {"project": {"key": "B1"}}
        }
    },
    headers={"X-Hub-Signature": "sha256=invalid"}
)
print(f"Invalid signature: {r.status_code} {r.json()}")

# Test 3 - No signature (expect 401)
r = requests.post(
    f"{BASE}/webhook/jira",
    json={
        "webhookEvent": "jira:issue_created",
        "issue": {
            "key": "B1-1001",
            "fields": {"project": {"key": "B1"}}
        }
    }
)
print(f"No signature: {r.status_code} {r.json()}")