"""Compare frontend API calls (services.js) with backend OpenAPI routes. Read-only; no DB."""
import os, re, sys
os.environ["DATABASE_URL"] = "sqlite://"
sys.dont_write_bytecode = True
sys.path.insert(0, os.getcwd())
from backend.app.main import create_app

spec = create_app().openapi()["paths"]
norm = lambda p: re.sub(r"\{[^}]+\}", "{}", p)
backend = {(m.upper(), norm(p)) for p, ops in spec.items() for m in ops}
src = open("frontend/src/api/services.js", encoding="utf-8").read()
calls = re.findall(r"api\.(get|post|put|patch|delete)\(\s*[`'\"]([^`'\"]+)", src)
calls += [("post", u) for u in re.findall(r"uploadCsv\('([^']+)'", src)]
used, missing = set(), []
for m, p in calls:
    key = (m.upper(), norm("/api" + re.sub(r"\$\{[^}]+\}", "{x}", p)))
    used.add(key)
    if key not in backend:
        missing.append(key)
print("frontend calls:", len(calls), "| missing on backend:", missing or "none")
print("backend ops not called from services.js:", sorted(backend - used))
