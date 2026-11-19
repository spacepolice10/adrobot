# Adrobot

FastAPI with SQLAlchemy 2 and a small Alpine.js frontend. Pydantic defines the
API response schema. The frontend is served by FastAPI and loads a pinned
Alpine.js release from jsDelivr.

## Local development

With Docker Desktop running and [mise](https://mise.jdx.dev/) installed, run:

```sh
mise trust
mise install
mise exec -- uv sync
docker compose up -d --wait postgres
DATABASE_URL=postgresql+psycopg://adrobot:adrobot@127.0.0.1:5433/adrobot \
  mise exec -- uv run uvicorn adrobot.main:app --reload
```

Open <http://127.0.0.1:8000/> for the frontend or
<http://127.0.0.1:8000/docs> for interactive API documentation.

Check the database connection at <http://127.0.0.1:8000/api/health>.
Compose uses a dedicated volume for PostgreSQL. The credentials in
`compose.yaml` are for local development. Run `docker compose stop postgres`
to stop the service while keeping the data.

If you omit `DATABASE_URL`, the app uses `adrobot.db` in the working directory.
The current smoke tests use temporary SQLite databases. There are no application
tables to migrate yet.

## Checks

```sh
mise exec -- uv run pytest
mise exec -- uv run ruff check .
mise exec -- uv run ruff format --check .
```

## Keitaro campaign creation

Copy `.env.example` to `.env` in the project root and fill in
`KEITARO_URL` (the tracker URL) and `KEITARO_API_KEY` (an Admin API key).
Git ignores `.env`.

Start the app with the environment file:

```sh
DATABASE_URL=postgresql+psycopg://adrobot:adrobot@127.0.0.1:5433/adrobot \
  mise exec -- uv run uvicorn adrobot.main:app --reload --env-file .env
```

Use the local app at `/docs` to call
`POST /api/campaigns` with this body, replacing the IDs with IDs from Keitaro:

```json
{
  "name": "Test campaign",
  "domain_id": 1,
  "group_id": 2,
  "traffic_source_id": 3
}
```

The endpoint requires the IDs as JSON integers and returns `201` with the
campaign's Keitaro ID. It generates an alias and creates the campaign disabled
so it can be configured before receiving traffic.
