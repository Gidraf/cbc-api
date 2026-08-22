# CBC API Runtime (FastAPI)

This runtime is designed to boot as a complete local platform with Docker Compose.

## What Is Included

- FastAPI API service
- Redis queue-backed async worker
- MinIO object storage for diagram artifacts
- Playwright browser service for agent browsing workflows
- Provider config and per-stage model routing for `openai`, `anthropic`, `gemini`, `ollama`
- Notes-first pipeline and mixed-assessment question contract validation
- Frontend React UI in `frontend-web` that consumes all API routes

## One-Command Boot

From project root:

```bash
docker compose up --build
```

Services:

- API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Playwright browser endpoint: `http://localhost:3000`
- MinIO: external VM endpoint configured via `.env`

## Optional Environment Setup

Copy `.env.example` to `.env` and set any provider keys you want to use.

```bash
cp .env.example .env
```

Set external MinIO settings in `.env`:

- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_SECURE`
- `MINIO_PUBLIC_BASE_URL`

If no Gemini key is configured, default stage bindings bootstrap to Ollama.

## Main Endpoints

- `POST /auth/login`
- `GET /auth/me`
- `GET /health`
- `GET /admin/config`
- `PUT /admin/providers/{provider}/config`
- `POST /admin/pipeline-bindings/{stage}`
- `POST /pipeline/generate` (sync)
- `POST /pipeline/enqueue` (async)
- `GET /pipeline/jobs/{job_id}`
- `POST /agents/browse`
- `GET /review/queue`
- `POST /review/{run_id}/decision`
- `GET /human-review/queue`
- `POST /human-review/{run_id}/decision`
- `GET /production/ready`

## Auth and Roles

Roles supported by token login:

- `admin`
- `operator`
- `reviewer`
- `developer`

Developer role can also authenticate via `x-api-key` using `DEVELOPER_API_KEY`.

Set these in root `.env`:

- `JWT_SECRET`
- `JWT_EXP_MINUTES`
- `ADMIN_PASSWORD`
- `OPERATOR_PASSWORD`
- `REVIEWER_PASSWORD`
- `DEVELOPER_PASSWORD`
- `DEVELOPER_API_KEY`

## Quick API Flow

1. Configure provider key/base URL:

```bash
curl -X PUT http://localhost:8000/admin/providers/gemini/config \
	-H 'content-type: application/json' \
	-d '{"api_key":"YOUR_GEMINI_KEY"}'
```

2. Bind stage to provider/model:

```bash
curl -X POST http://localhost:8000/admin/pipeline-bindings/notes_generation \
	-H 'content-type: application/json' \
	-d '{"provider":"gemini","model":"gemini-2.5-flash"}'
```

Repeat binding for all stages, or inspect defaults via `GET /admin/config`.

3. Run synchronous generation:

```bash
curl -X POST http://localhost:8000/pipeline/generate \
	-H 'content-type: application/json' \
	-d '{
		"request_id":"req_01",
		"trace_id":"trc_01",
		"tenant_id":"cbc_default",
		"actor":{"type":"admin","id":"usr_admin_01"},
		"curriculum":{
			"level":"Middle School",
			"grade":"7",
			"subject":"Integrated Science",
			"subject_code":"ISCI",
			"pathway":null,
			"track":null,
			"strand":"Matter",
			"sub_strand":"Classification of Matter",
			"slo_id":"MS-G7-ISCI-MAT-CLM-01"
		},
		"controls":{
			"idempotency_key":"idem_01",
			"deadline_ms":120000,
			"max_regen_attempts":2,
			"environment":"prod"
		}
	}'
```

4. Run asynchronous generation:

```bash
curl -X POST http://localhost:8000/pipeline/enqueue \
	-H 'content-type: application/json' \
	-d '{...same payload...}'
```

Then query:

```bash
curl http://localhost:8000/pipeline/jobs/<job_id>
```

5. Agent browsing with Playwright:

```bash
curl -X POST http://localhost:8000/agents/browse \
	-H 'content-type: application/json' \
	-d '{"url":"https://example.com"}'
```

## Notes

- This stack is contract-first and extensible.
- Stage generators currently return deterministic baseline outputs.
- MinIO bucket bootstrap is handled by API startup and worker startup checks against your external VM MinIO.
