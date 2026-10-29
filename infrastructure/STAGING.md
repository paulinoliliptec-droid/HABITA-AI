# Manual publication to Cloud Run staging

Nothing deploys automatically: the repository has no GitHub Actions, and Cloud Build is not enabled on the project.
Every step below is run by hand by someone authorised for project `habita-ai-512916`. Running it **is a deploy**:
it needs the owner's explicit authorisation each time.

## What exists (read-only check, 2026-10-29)
| Service | Region | Image tag | Revision | Notes |
|---|---|---|---|---|
| `habita-backend-preview` | us-central1 | `habita-preview/backend:hr003-98af6af` | 00016 | env `APP_ENV=preview`, `MONGODB_DB_NAME=habita_ai`; secrets `GOOGLE_MAPS_API_KEY`, `mongodb-uri`, `meta-api-key` (latest) |
| `habita-frontend-preview` | us-central1 | `habita-preview/frontend:hr003-98af6af` | 00011 | API URL and browser Maps key inlined at build |

There is no production service. The preview services are the staging environment; they run `98af6af` (before MU-9,
HR-004 and HR-006).

## Database isolation
- The preview backend uses database `habita_ai` on the Atlas cluster behind the `mongodb-uri` secret; its official
  source snapshots and seeded demo properties live there.
- The live tests write to `MONGODB_DB_NAME`: run them with a separate database, e.g.
  `MONGODB_DB_NAME=habita_ai_livetest`, never `habita_ai`. `test_permit_commit_atlas.py` uses a throwaway database
  that it drops.
- Each new code version that changes stored schemas: check `SCHEMA_VERSION` / snapshot compatibility before pointing
  it at `habita_ai`, or deploy it against a new database (`habita_ai_staging`) and re-run
  `python -m app.maintenance ingest-sources` there.

## Procedure (do not run without authorisation)
```bash
P=habita-ai-512916; R=us-central1-docker.pkg.dev/$P/habita-preview; T=staging-$(git rev-parse --short HEAD)
git status --porcelain            # must be empty: images are built from committed code only

# 1. Tests first (no credentials needed)
(cd backend && .venv/bin/pytest -q) && (cd frontend && npm test && npm run lint && npm run typecheck && npm run build)

# 2. Images (local Docker; the Dockerfiles live in infrastructure/docker/)
DOCKER_BUILDKIT=1 docker build -f infrastructure/docker/backend.Dockerfile -t $R/backend:$T backend
BACKEND_URL=$(gcloud run services describe habita-backend-preview --region us-central1 --project $P --format='value(status.url)')
DOCKER_BUILDKIT=1 docker build -f infrastructure/docker/frontend.Dockerfile \
  --build-arg NEXT_PUBLIC_API_BASE_URL=$BACKEND_URL \
  --build-arg NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=<browser key, HTTP-referrer restricted> \
  -t $R/frontend:$T frontend
docker push $R/backend:$T && docker push $R/frontend:$T

# 3. New revisions (secrets stay in Secret Manager; nothing secret on the command line)
gcloud run deploy habita-backend-preview  --image $R/backend:$T  --region us-central1 --project $P
gcloud run deploy habita-frontend-preview --image $R/frontend:$T --region us-central1 --project $P

# 4. Smoke: /health/ready, resolve a Cascais address, open the workspace, download a property PDF.
# 5. Rollback: gcloud run services update-traffic <service> --to-revisions <previous revision>=100
```

## Risks
- The backend image now needs `reportlab` (pinned in `backend/requirements.txt`); the image was built and imported
  locally (`docker build` + `import app.main, reportlab`), not deployed.
- Ingress is `all`; when unauthenticated invocation is allowed (check the services' IAM), anyone with the URL can use
  the Google and Meta keys through the API (rate limits apply). Keep `--min-instances 0` outside demos (billing).
- The browser key ends up in the frontend bundle by design; it must stay HTTP-referrer restricted.
- Pointing a new version at `habita_ai` shares data with the current demo; see Database isolation.
- Webhooks on the GitHub repository could not be listed without owner credentials; check *Settings → Webhooks*
  before assuming no external integration reacts to pushes.
