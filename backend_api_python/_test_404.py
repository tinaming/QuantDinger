"""Quick endpoint smoke test - bypassing Docker by using 0.0.0.0."""
import requests

# Flask dev server listens on 0.0.0.0:5000, Docker on 127.0.0.1:5000
# Using 0.0.0.0 bypasses Docker port forwarding
BASE = "http://0.0.0.0:5000"
s = requests.Session()

# Login
r = s.post(f"{BASE}/api/auth/login", json={"username": "quantdinger", "password": "nodame88"})
print(f"login: {r.status_code}")
token = r.json().get("data", {}).get("token", "")
h = {"Authorization": f"Bearer {token}"}

# Test endpoints
endpoints = [
    "/health",
    "/api/coinos/skills",
    "/api/coinos/market/ticker",
    "/api/indicator/getIndicators",
    "/api/market/types",
    "/api/settings/values",
    "/api/dashboard/summary",
    "/api/credentials/list",
    "/api/strategies",
    "/api/community/indicators",
    "/api/market-modules/",
    "/api/billing/plans",
    "/api/portfolio/summary",
    "/api/global-market/overview",
    "/api/agent/v1/coinos/skills",
]

for ep in endpoints:
    try:
        r = s.get(f"{BASE}{ep}", headers=h, timeout=10)
        body_preview = r.text[:80] if r.status_code != 200 else ""
        print(f"{ep:50s} -> {r.status_code} {body_preview}")
    except Exception as e:
        print(f"{ep:50s} -> ERROR {e}")
