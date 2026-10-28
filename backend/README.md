# backend/

Python 3.12 + FastAPI.

## Run

```bash
cd backend
python3 -m venv .venv          # if ensurepip is missing: python3 virtualenv.pyz .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Configuration comes from the repo-root `.env` (git-ignored) or the process environment. See `../docs/environment.md`.

| Variable | Needed for | Without it |
|---|---|---|
| `GOOGLE_MAPS_API_KEY` | Geocoding (server key) | `POST /api/property/resolve-location` returns `503 service_not_configured` |
| `MONGODB_URI` | Persisting properties | Startup fails, unless `ALLOW_EPHEMERAL_STORAGE=true` (local dev/tests: in-memory store) |
| `BACKEND_CORS_ORIGINS` | Browser access | Defaults to `http://localhost:3000` |
| `META_API_KEY` | Permit Intelligence (Muse Spark) | `/api/permit/*/continue` returns `503 service_not_configured`; `/api/permit/status` reports `available: false` |
| `META_TEXT_MODEL` | Reasoning model | Defaults to `muse-spark-1.3` (contributor variants are refused) |

## Test

```bash
pytest
```

Google is never called in the default suite: `httpx.MockTransport` serves realistic Geocoding payloads (`tests/fixtures.py`).

Live smoke test against real Google Maps and MongoDB Atlas (opt-in; it upserts one Cascais property):

```bash
P=habita-ai-512916
HABITA_LIVE_TESTS=1 \
  MONGODB_URI="$(gcloud secrets versions access latest --secret mongodb-uri --project $P)" \
  NEXT_PUBLIC_GOOGLE_MAPS_API_KEY="$(gcloud secrets versions access latest --secret NEXT_PUBLIC_GOOGLE_MAPS_API_KEY --project $P)" \
  pytest tests/test_live_smoke.py
```

## Layout

```
app/
  main.py                      app factory, lifespan wiring, CORS, /health
  core/                        settings, structured errors
  api/property.py              /api/property routes
  schemas/property.py          request/response models
  integrations/maps/           Google Geocoding client
  services/property_location.py   address → location → jurisdiction → persisted property
  services/jurisdiction/       jurisdiction contract, resolver, per-country adapters
  db/property_repository.py    MongoDB + in-memory repositories
```

## API

`POST /api/property/resolve-location` with `{"address": "..."}` or `{"place_id": "..."}` returns the resolved property:
- `property_id`, `formatted_address`, `coordinates`, `precision`, `place_id`, and `partial_match` for this request only;
- `jurisdiction`: `id`, `levels[]` (`type`, `id`, `name`, `label`), `local_authority` (`id`, `name`, `kind`, `jurisdiction_id`, `competence`, `sources[]`) and `coverage`, plus a display summary (`country`, `region`, `municipality`, `city`);
- `provenance`: request, geocode lookups, adapter and version;
- `resolved_at`, `expires_at`.

See `docs/architecture.md` §4.1 and §9.1 for identity, snapshot and jurisdiction semantics.

`GET /api/property/{property_id}` returns a saved property (no `partial_match`), refreshing it from Google first if its snapshot has expired or was purged. A merged duplicate's ID returns the property it was merged into.

`GET /health` (liveness) and `GET /health/ready` (storage reachable).

Errors always have the shape `{"error": {"code": "...", "message": "..."}}`, including unexpected failures. Codes: `validation_error`, `address_not_found`, `not_found`, `rate_limited` (429, `Retry-After`), `service_not_configured`, `storage_unavailable`, `upstream_error`, `internal_error`.

The app refuses to start without `MONGODB_URI` unless `ALLOW_EPHEMERAL_STORAGE=true`.

## Permit Intelligence (HR-002)

| Endpoint | Purpose |
|---|---|
| `GET /api/permit/status` | Whether the reasoning model is configured |
| `POST /api/permit/matters` | Create a matter: `{"property_id", "question"}` |
| `GET /api/permit/matters/{id}` | Current state, missing inputs, draft, progress |
| `POST /api/permit/matters/{id}/continue` | Run until NEEDS_INPUT, VERIFIED, ESCALATE or FAILED (resumable) |
| `POST /api/permit/matters/{id}/inputs` | Supply requested information: `{"inputs": {key: answer}}` |
| `GET /api/permit/matters/{id}/checklist` · `/evidence` · `/verification` | Persisted checklist, evidence records, latest verification report |

Live Meta test (opt-in): `HABITA_META_LIVE=1 META_API_KEY=… pytest tests/test_permit_live.py`.

## Official sources and planning context (HR-003)

`GET /api/property/{property_id}/planning-context` returns the planning context (`status`: `resolved`, `partial`, `requires_manual_confirmation` or `not_supported`; instrument and version; classification only when an official layer determined it; documents to consult; reasons; competent authority; verification and retrieval dates) and the trusted official sources that apply to the property.

Live source test (opt-in, fetches cascais.pt): `HABITA_LIVE_TESTS=1 pytest tests/test_sources_live.py`.

## Maintenance

```bash
python -m app.maintenance purge-expired     # remove expired Google-derived fields (also automatic)
python -m app.maintenance list-duplicates   # properties flagged as possible duplicates
python -m app.maintenance merge <keep> <duplicate>   # fold a reviewed duplicate; its ID keeps working (safe to re-run)
python -m app.maintenance resume-merges     # complete interrupted merges (also automatic at startup)
python -m app.maintenance ingest-sources [jurisdiction]   # seed the source registry; fetch, snapshot and index trusted PDFs
python -m app.maintenance list-sources      # registry with status and latest snapshot
python -m app.maintenance set-source-status <source_id> <status> <operator> <reason…>   # operator lifecycle change
```

`POST /internal/maintenance/run` (header `X-Maintenance-Token`) runs the purge and resumes merges, for a scheduler. It is disabled (404) unless `MAINTENANCE_TOKEN` is set. Cleanup is best effort during the hackathon; expired data is never *served* regardless.
