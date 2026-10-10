"""Non-destructive live HTTP checks against the running backend (http://127.0.0.1:8001).

Replaces the previous audit's e2e_api.py, which created a coordinator account. This script
creates no users and logs nobody in. Every request is either unauthenticated, rejected by
validation or the invite check before any database write, or a CORS preflight. Authenticated
workflows are covered by the SQLite-backed backend test suite instead.

    .venv\\Scripts\\python.exe -B live_http_readonly.py [out.json]
"""
import json
import sys

import httpx

BASE = "http://127.0.0.1:8001"
ALLOWED = ["http://127.0.0.1:5173", "http://localhost:5173"]
UNLISTED = "https://untrusted.example"
results = []


def check(name, cond, detail=""):
    results.append({"check": name, "pass": bool(cond), "detail": str(detail)})
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail != "" else ""))


c = httpx.Client(base_url=BASE, timeout=20)
pre = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type",
       "Access-Control-Request-Private-Network": "true"}

r = c.get("/health")
check("health is 200 and reveals only status", r.status_code == 200 and r.json() == {"status": "ok"}, r.text)

for origin in ALLOWED:
    for path in ("/api/auth/login", "/api/auth/register"):
        r = c.options(path, headers={"Origin": origin, **pre})
        check(f"PNA preflight {path} from {origin}", r.status_code == 200 and
              r.headers.get("access-control-allow-origin") == origin and
              "access-control-allow-credentials" not in r.headers, r.status_code)
r = c.options("/api/students", headers={"Origin": ALLOWED[0], **pre,
              "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
check("PNA preflight GET /api/students with Authorization header", r.status_code == 200, r.status_code)

r = c.options("/api/auth/login", headers={"Origin": UNLISTED, **pre})
check("unlisted origin preflight rejected", r.status_code == 400 and
      "access-control-allow-origin" not in r.headers, r.status_code)
r = c.post("/api/auth/login", headers={"Origin": UNLISTED},
           json={"email": "nobody@example.com", "password": "not-a-real-password"})
check("unlisted origin gets no allow-origin on actual request", "access-control-allow-origin" not in r.headers,
      r.status_code)

h = {"Origin": ALLOWED[0]}
r = c.post("/api/auth/login", headers=h, json={})
check("login with missing fields -> 422", r.status_code == 422, r.status_code)
r = c.post("/api/auth/login", headers=h, json={"email": "nobody@example.com", "password": "not-a-real-password"})
check("login with unknown account -> 401 'Invalid email or password'", r.status_code == 401 and
      r.json().get("detail") == "Invalid email or password" and
      r.headers.get("access-control-allow-origin") == ALLOWED[0], r.status_code)
r = c.post("/api/auth/register", headers=h, json={"email": "not-an-email", "password": "x", "role": "student"})
check("register with invalid body -> 422 (no write)", r.status_code == 422, r.status_code)
r = c.post("/api/auth/register", headers=h, json={"email": "never-created@example.com",
           "password": "LongEnoughPassword123", "role": "coordinator", "invite_code": "definitely-wrong"})
check("coordinator register with wrong invite -> 403 (checked before any write)", r.status_code == 403, r.status_code)

for path in ("/api/auth/me", "/api/students", "/api/students/me", "/api/analytics/overview",
             "/api/predictions", "/api/interventions", "/api/imports/template", "/api/access-requests"):
    r = c.get(path, headers=h)
    check(f"no token -> 401 {path}", r.status_code == 401, r.status_code)
r = c.get("/api/auth/me", headers={**h, "Authorization": "Bearer not-a-real-token"})
check("malformed token -> 401", r.status_code == 401, r.status_code)

spec = c.get("/openapi.json").json()
for op, path in (("post", "/api/auth/login"), ("post", "/api/auth/register"), ("get", "/api/auth/me")):
    check(f"route registered {op.upper()} {path}", op in spec["paths"].get(path, {}))

out = {"passed": sum(x["pass"] for x in results), "failed": sum(not x["pass"] for x in results),
       "results": results}
print(f"\n{out['passed']} passed, {out['failed']} failed")
if len(sys.argv) > 1:
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
sys.exit(1 if out["failed"] else 0)
