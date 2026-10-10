"""Reproduce the login 'API could not be reached' root cause in-process (no server, no DB).

Builds the project's CORS configuration with and without allow_private_network and sends the
same preflight Chrome sends for a cross-origin POST /api/auth/login from the Vite dev origin.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def build(allow_private_network: bool) -> TestClient:
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type"],
                       allow_private_network=allow_private_network)

    @app.post("/api/auth/login")
    def login():
        return {}
    return TestClient(app)


base = {"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"}
for flag in (False, True):
    client = build(flag)
    for pna in (False, True):
        headers = dict(base, **({"Access-Control-Request-Private-Network": "true"} if pna else {}))
        r = client.options("/api/auth/login", headers=headers)
        print(f"allow_private_network={flag!s:5}  PNA header={pna!s:5}  -> {r.status_code} {r.text!r}")
