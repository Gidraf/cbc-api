# CBC API Full Local Stack

This repository now includes a dockerized, multi-service runtime you can boot with Compose.

## Boot

```bash
docker compose up --build
```

If your environment uses legacy Compose binary:

```bash
docker-compose up --build
```

## Services

- Frontend UI: http://localhost:5173
- API: http://localhost:8000
- Swagger Docs: http://localhost:8000/docs
- Redis: localhost:6379
- Playwright Browser Service: http://localhost:3000
- External MinIO on your VM (configured through `.env`)
- External PostgreSQL on your VM (configured through `.env`)

## Core Features

- Admin model/provider config: `openai`, `anthropic`, `gemini`, `ollama`
- Per-pipeline stage model routing
- Sync and async generation execution
- Redis-backed job queue and worker
- MinIO diagram storage
- Playwright browsing endpoint for agent workflows
- Authenticated login UI with role-based visibility (admin/operator/reviewer/developer)
- Reviewer, human-review, and production-ready workflow operations

## First Setup

1. Copy env file:

```bash
cp .env.example .env
```

2. Optionally set provider keys in `.env`.
3. Set your VM MinIO values in `.env` (`MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_PUBLIC_BASE_URL`).
4. Set auth values in `.env` (`JWT_SECRET`, `ADMIN_PASSWORD`, `OPERATOR_PASSWORD`, `REVIEWER_PASSWORD`, `DEVELOPER_PASSWORD`, `DEVELOPER_API_KEY`).
5. Set Postgres VM connection in `.env` (`DATABASE_URL`).

6. Start stack:

```bash
docker compose up --build
```

### If Docker Build Fails With SSL Certificate Verify Errors

When `pip install` fails with `CERTIFICATE_VERIFY_FAILED`, your network likely uses a custom root CA.

1. Export your root CA certificate as PEM and base64 encode it:

```bash
base64 -i /path/to/your-root-ca.pem | tr -d '\n'
```

2. Set `CUSTOM_CA_CERT_B64` in `.env` to that value.

3. Rebuild:

```bash
docker-compose build --no-cache
docker-compose up -d
```

7. Open docs and configure model routing:

- Open frontend: http://localhost:5173

- GET /admin/config
- PUT /admin/providers/{provider}/config
- POST /admin/pipeline-bindings/bootstrap

## Example Bulk Stage Routing

```bash
curl -X POST http://localhost:8000/admin/pipeline-bindings/bootstrap \
  -H 'content-type: application/json' \
  -d '{"provider":"gemini","model":"gemini-2.5-flash"}'
```

## Automatic Migrations

- On API and worker startup, migrations run automatically against `DATABASE_URL`.
- No Docker Postgres image is used in this stack.
