#!/usr/bin/env bash
# Manual staging deploy of the current commit (HR-004 map post-its, HR-006 PDF report). NOT run by any automation.
# Creates two NEW Cloud Run services next to the preview, on an ISOLATED database (habita_ai_staging):
# no data from the preview database (habita_ai) and no private property data is copied. The staging database starts
# empty; on startup the backend seeds the official-source registry and ingests the public official sources.
# Requires the owner's explicit authorisation: it creates resources and deploys.
set -euo pipefail

P=habita-ai-512916
REGION=us-central1
R=$REGION-docker.pkg.dev/$P/habita-preview
T=staging-$(git rev-parse --short HEAD)
DB=habita_ai_staging
: "${BROWSER_MAPS_KEY:?export BROWSER_MAPS_KEY (the HTTP-referrer restricted browser key)}"

[ -z "$(git status --porcelain)" ] || { echo "Working tree not clean: images are built from committed code only." >&2; exit 1; }
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/mu9/structural-verification)" ] \
  || { echo "HEAD is not the pushed branch head: push first so the deployed code is the published code." >&2; exit 1; }

# 1. Tests (no credentials)
(cd backend && .venv/bin/pytest -q -p no:cacheprovider)
(cd frontend && npm test && npm run lint && npm run typecheck)

# 2. Backend image and service (secrets by reference; the database name isolates staging)
DOCKER_BUILDKIT=1 docker build -f infrastructure/docker/backend.Dockerfile -t "$R/backend:$T" backend
docker push "$R/backend:$T"
gcloud run deploy habita-backend-staging --image "$R/backend:$T" --region "$REGION" --project "$P" \
  --set-env-vars "APP_ENV=staging,MONGODB_DB_NAME=$DB,SOURCE_INGEST_ON_STARTUP=true" \
  --set-secrets "MONGODB_URI=mongodb-uri:latest,GOOGLE_MAPS_API_KEY=GOOGLE_MAPS_API_KEY:latest,META_API_KEY=meta-api-key:latest" \
  --min-instances 0 --max-instances 2 --allow-unauthenticated
BACKEND_URL=$(gcloud run services describe habita-backend-staging --region "$REGION" --project "$P" --format='value(status.url)')

# 3. Frontend image and service
DOCKER_BUILDKIT=1 docker build -f infrastructure/docker/frontend.Dockerfile \
  --build-arg "NEXT_PUBLIC_API_BASE_URL=$BACKEND_URL" --build-arg "NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=$BROWSER_MAPS_KEY" \
  -t "$R/frontend:$T" frontend
docker push "$R/frontend:$T"
gcloud run deploy habita-frontend-staging --image "$R/frontend:$T" --region "$REGION" --project "$P" \
  --min-instances 0 --max-instances 2 --allow-unauthenticated
FRONTEND_URL=$(gcloud run services describe habita-frontend-staging --region "$REGION" --project "$P" --format='value(status.url)')

# 4. CORS for the new frontend origin, then a smoke check
gcloud run services update habita-backend-staging --region "$REGION" --project "$P" \
  --update-env-vars "BACKEND_CORS_ORIGINS=$FRONTEND_URL"
curl -fsS "$BACKEND_URL/health/ready" && echo
echo "Staging: $FRONTEND_URL (backend $BACKEND_URL, database $DB)"
