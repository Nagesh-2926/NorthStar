"""Read-only snapshot of the isolated NorthStar database (127.0.0.1:5433 only).

Run through the launcher so DATABASE_URL points at 5433 without editing .env:
    .venv\\Scripts\\python.exe -m scripts.with_isolated_db -- .venv\\Scripts\\python.exe -B <this file> [out.json]

Refuses any target other than 127.0.0.1:5433. Uses a read-only session. Prints counts and
labels only: no emails (except the known audit marker pattern), hashes, or credentials.
"""
import json
import os
import sys
from urllib.parse import urlsplit

import psycopg

url = os.environ.get("DATABASE_URL", "")
parts = urlsplit(url)
if (parts.hostname, parts.port) != ("127.0.0.1", 5433):
    sys.exit(f"refusing target {parts.hostname}:{parts.port}; only 127.0.0.1:5433 is allowed")

TABLES = ["users", "students", "enrollments", "predictions", "interventions", "study_plans",
          "dataset_imports", "imported_feature_snapshots", "behavioral_clusters",
          "student_access_requests", "academic_records", "engagement_records", "grade_predictions",
          "motivational_messages"]
snap = {"target": f"{parts.hostname}:{parts.port}{parts.path}"}
with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"), connect_timeout=5) as conn:
    conn.read_only = True
    snap["server_port_inside_container"] = conn.execute("select inet_server_port()").fetchone()[0]
    snap["transaction_read_only"] = conn.execute("show transaction_read_only").fetchone()[0]
    snap["alembic_version"] = conn.execute("select version_num from alembic_version").fetchone()[0]
    snap["counts"] = {t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in TABLES}
    snap["users_by_role"] = dict(conn.execute("select role, count(*) from users group by 1 order by 1").fetchall())
    snap["prediction_versions"] = [list(r) for r in conn.execute(
        "select model_name, model_version, feature_version, count(*) from predictions group by 1,2,3 order by 1,2")]
    snap["lstm_rows_labelled_1_2_0"] = conn.execute(
        "select count(*) from predictions where model_name='lstm_weekly' and model_version='1.2.0'").fetchone()[0]
    marker = conn.execute(
        "select role, is_active, token_version from users where email = lower(%s)",
        ("audit-e2e-coordinator-20261010T045341Z@example.com",)).fetchall()
    snap["audit_marker_account"] = [{"role": r[0], "is_active": r[1], "token_version": r[2]} for r in marker]
    conn.rollback()

print(json.dumps(snap, indent=2, default=str))
if len(sys.argv) > 1:
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=2, default=str)
