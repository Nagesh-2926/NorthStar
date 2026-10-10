"""Live HTTP end-to-end checks against the running backend (127.0.0.1:8001 -> 5433 DB).

Every request carries the Vite origin like the browser does. The ONLY write is one clearly
marked coordinator account (plus its password change). No students, enrollments, predictions,
imports, or registry files are created. Secrets (invite code, generated password, tokens) are
never printed.
"""
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8001"
ORIGIN = "http://127.0.0.1:5173"
ROOT = Path.cwd()
results = []


def check(name, cond, detail=""):
    results.append({"check": name, "pass": bool(cond), "detail": detail})
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else ""))


def env_value(key):
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


c = httpx.Client(base_url=BASE, headers={"Origin": ORIGIN}, timeout=30)

# 1. infrastructure / CORS as the browser sees it
r = c.get("/health"); check("GET /health", r.status_code == 200 and r.json() == {"status": "ok"}, r.text)
for path, method in (("/api/auth/login", "POST"), ("/api/auth/register", "POST"), ("/api/students", "GET")):
    r = c.options(path, headers={"Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "content-type,authorization",
        "Access-Control-Request-Private-Network": "true"})
    check(f"preflight {method} {path} (Chrome PNA)", r.status_code == 200 and
          r.headers.get("access-control-allow-origin") == ORIGIN, str(r.status_code))
r = c.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"})
check("simple CORS response carries allow-origin", r.headers.get("access-control-allow-origin") == ORIGIN)

# 2. protected routes without / with bad token
for path in ("/api/auth/me", "/api/students", "/api/analytics/overview", "/api/predictions"):
    r = c.get(path); check(f"no token -> 401 {path}", r.status_code == 401, str(r.status_code))
r = c.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
check("garbage token -> 401", r.status_code == 401, str(r.status_code))

# 3. registration rules (wrong invite never writes)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
email = f"audit-e2e-coordinator-{stamp}@example.com"
password = secrets.token_urlsafe(18)
r = c.post("/api/auth/register", json={"email": email, "password": password, "role": "coordinator",
                                       "invite_code": "definitely-wrong-invite"})
check("coordinator register with wrong invite -> 403", r.status_code == 403, str(r.status_code))
r = c.post("/api/auth/register", json={"email": email, "password": "short", "role": "student"})
check("weak password rejected -> 422", r.status_code == 422, str(r.status_code))
invite = env_value("COORDINATOR_INVITE_CODE")
r = c.post("/api/auth/register", json={"email": email, "password": password, "role": "coordinator",
                                       "invite_code": invite})
check("coordinator register (marked test account) -> 201", r.status_code == 201, str(r.status_code))
created_user_id = r.json().get("id") if r.status_code == 201 else None
r = c.post("/api/auth/register", json={"email": email, "password": password, "role": "coordinator",
                                       "invite_code": invite})
check("duplicate register -> 409", r.status_code == 409, str(r.status_code))

# 4. login
r = c.post("/api/auth/login", json={"email": email, "password": password + "x"})
check("login wrong password -> 401", r.status_code == 401, str(r.status_code))
r = c.post("/api/auth/login", json={"email": email.upper(), "password": password})
check("login (case-insensitive email) -> 200 + bearer token", r.status_code == 200 and
      r.json().get("token_type") == "bearer" and r.json().get("expires_in", 0) > 0, str(r.status_code))
token = r.json()["access_token"]
auth = {"Authorization": f"Bearer {token}"}
r = c.get("/api/auth/me", headers=auth)
check("GET /auth/me -> coordinator", r.status_code == 200 and r.json()["role"] == "coordinator"
      and set(r.json()) == {"id", "email", "role", "is_active", "created_at"}, str(r.status_code))

# 5. coordinator read workflows (existing data, read-only)
reads = {}
for path, params in (("/api/students", {"limit": 200}), ("/api/analytics/overview", None),
                     ("/api/analytics/risk-trends", {"days": 90}), ("/api/analytics/engagement", None),
                     ("/api/analytics/monitoring/students", {"limit": 8, "sort_by": "support_score",
                      "sort_order": "desc", "risk_filter": "review_for_support"}),
                     ("/api/predictions", {"limit": 100}), ("/api/clusters", None),
                     ("/api/analytics/clusters", None), ("/api/interventions", None),
                     ("/api/access-requests", None)):
    r = c.get(path, headers=auth, params=params)
    reads[path] = r
    size = len(r.json()) if r.status_code == 200 and isinstance(r.json(), list) else (
        sorted(r.json())[:8] if r.status_code == 200 and isinstance(r.json(), dict) else "")
    check(f"coordinator GET {path} -> 200", r.status_code == 200, f"{r.status_code} {size}")
r = c.get("/api/imports/template", headers=auth)
check("coordinator GET /imports/template -> CSV", r.status_code == 200 and "csv" in r.headers.get("content-type", ""),
      r.headers.get("content-type", ""))

students = reads["/api/students"].json() if reads["/api/students"].status_code == 200 else []
check("student list size matches DB count (28)", len(students) == 28, str(len(students)))
preds = reads["/api/predictions"].json() if reads["/api/predictions"].status_code == 200 else []
frontend_pred_fields = {"id", "enrollment_id", "model_name", "model_version", "feature_version",
                        "support_priority_score", "threshold", "priority_band", "observed_signals", "created_at"}
if preds:
    check("prediction records expose fields the frontend reads", all(frontend_pred_fields <= set(p) for p in preds))
    check("all stored scores and thresholds in [0,1]", all(0 <= p["support_priority_score"] <= 1 and
          0 <= p["threshold"] <= 1 for p in preds))
    check("priority_band values are the two the UI knows", {p["priority_band"] for p in preds} <=
          {"review_for_support", "no_flag_from_model"}, str(sorted({p["priority_band"] for p in preds})))
    xgb = [p for p in preds if p["model_name"] == "xgboost"]
    check("band agrees with score >= stored threshold", all(
        (p["support_priority_score"] >= p["threshold"]) == (p["priority_band"] == "review_for_support")
        for p in preds), f"{len(preds)} predictions")
    print("INFO prediction models/versions:", sorted({(p["model_name"], p["model_version"], round(p["threshold"], 6)) for p in preds}))
if students:
    sid = students[0]["id"]
    for path in (f"/api/students/{sid}", f"/api/predictions/{sid}", f"/api/students/{sid}/performance",
                 f"/api/students/{sid}/engagement", f"/api/students/{sid}/study-plan",
                 f"/api/students/{sid}/motivational-messages"):
        r = c.get(path, headers=auth)
        check(f"coordinator GET {path.replace(sid, '{id}')} -> 200", r.status_code == 200, str(r.status_code))
    r = c.get(f"/api/students/00000000-0000-0000-0000-000000000000", headers=auth)
    check("unknown student -> 404", r.status_code == 404, str(r.status_code))

# 6. role enforcement
r = c.get("/api/students/me", headers=auth)
check("coordinator on student-only /students/me -> 403", r.status_code == 403, str(r.status_code))
r = c.get("/api/students", headers=auth, params={"limit": 999})
check("pagination limit validated -> 422", r.status_code == 422, str(r.status_code))

# 7. password change revokes old sessions (writes only to the test account)
new_password = secrets.token_urlsafe(18)
r = c.post("/api/auth/change-password", headers=auth, json={"current_password": password,
           "new_password": new_password, "confirm_password": new_password})
check("change-password -> 200", r.status_code == 200, str(r.status_code))
r = c.get("/api/auth/me", headers=auth)
check("old token rejected after password change -> 401", r.status_code == 401, str(r.status_code))
r = c.post("/api/auth/login", json={"email": email, "password": password})
check("old password rejected -> 401", r.status_code == 401, str(r.status_code))
r = c.post("/api/auth/login", json={"email": email, "password": new_password})
check("login with new password -> 200", r.status_code == 200, str(r.status_code))

out = {"run_utc": stamp, "created_test_account": {"email": email, "user_id": created_user_id,
       "role": "coordinator", "note": "audit marker account; password not recorded"},
       "passed": sum(x["pass"] for x in results), "failed": sum(not x["pass"] for x in results),
       "results": results}
Path(sys.argv[1]).write_text(json.dumps(out, indent=2), encoding="utf-8")
print(f"\n{out['passed']} passed, {out['failed']} failed")
