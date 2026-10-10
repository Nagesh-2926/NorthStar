# Production deployment checklist

This repository does not define an application hosting platform or production hostname. Its Compose file runs PostgreSQL only; the React and FastAPI services must be deployed on a platform selected by the operator. This guide records the required runtime configuration, but does not imply that a live deployment has been created or verified.

## Infrastructure and secrets

- Provision PostgreSQL 16 on a private network. Do not publish its listener to the public internet. The local Compose port binding is loopback-only for development.
- Provision separate frontend and API services, with a TLS-terminating HTTPS ingress in front of both. Configure platform health checks and restart policies.
- Store `DATABASE_URL`, `JWT_SECRET_KEY`, `COORDINATOR_INVITE_CODE`, and any LLM credentials in the host's secret manager. Never put them in source control, a frontend build variable, an image, or logs. Use a unique random JWT secret of at least 32 characters and a separate coordinator invite secret.
- Set `CORS_ORIGINS` to the exact HTTPS origin(s) serving the frontend, with no wildcard and no development origins. Keep `allow_credentials` disabled unless the authentication design is deliberately changed and reviewed.
- Set `LLM_PROVIDER=disabled` unless an approved provider is configured. If enabling one, provide its key only to the backend secret store. The AI assistant requires a configured provider; it does not substitute fabricated answers when disabled.
- Set `VITE_API_BASE_URL` to the public HTTPS API base ending in `/api` before building the frontend. This URL is public configuration, not a secret.

## Release and startup order

1. Build an immutable backend release from the pinned `backend/requirements.txt` and `ml/requirements.txt`, retaining the versioned artifacts in `ml/saved_models/`.
2. Build the frontend with the production `VITE_API_BASE_URL` using `npm ci` and `npm run build`, then publish only `frontend/dist` behind HTTPS.
3. Back up the production database and take a tested restore point before schema changes.
4. Run the migration once as a release job, using the same production `DATABASE_URL`: `python -m alembic -c backend/alembic.ini upgrade head`.
5. Start the backend with the platform's supported process manager, for example `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`. Use the platform's secure secret injection and health/restart policy; do not run development reload mode.
6. Verify `GET /health` through the production API ingress. It checks PostgreSQL readiness but does not validate every model artifact or external LLM.
7. Run authenticated coordinator and student smoke tests with dedicated non-production test accounts and authorized test records. Confirm the coordinator CSV validates against real active enrollments and do not use the OULAD training export as an upload.

## Before enabling public access

- Verify the production API hostname, frontend hostname, certificate/HTTPS redirect, exact CORS origin, database network ACL, database backups, and secret rotation procedures.
- Confirm logs omit credentials, bearer tokens, student records, and uploaded CSV contents. Route-level errors should remain sanitized.
- Verify database migrations at Alembic head, model artifact availability, an authenticated health/readiness check, and startup recovery after a controlled service restart.
- Complete the coordinator upload and student-ownership smoke tests on the actual deployment. A successful static frontend request alone is not a release sign-off.

The current application stores bearer tokens in browser `localStorage`; production hosting should apply a reviewed Content Security Policy and a narrow script policy. Changing token storage to cookies requires a separate CSRF and session-design review.
