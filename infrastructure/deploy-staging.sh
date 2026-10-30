#!/usr/bin/env bash
# Manual staging deploy of the pushed branch head (HR-004 map post-its, HR-006 PDF report). NOT run by any automation.
# Creates two NEW, PRIVATE Cloud Run services next to the preview, on an ISOLATED database (habita_ai_staging) reached
# with its own MongoDB user. Nothing is copied from the preview database (habita_ai); the preview services are never
# touched (checked before and after). Access is through `gcloud run services proxy` on localhost only: the browser uses
# http://localhost:3000 (frontend) and http://localhost:8081 (API), which the CORS setting and the browser Maps key allow.
# Requires the owner's explicit authorisation: it creates resources and deploys. See infrastructure/STAGING.md.
# `--preflight` runs only the read-only checks of step 0 and exits.
set -euo pipefail

P=habita-ai-512916
REGION=us-central1
BRANCH=mu9/structural-verification
R=$REGION-docker.pkg.dev/$P/habita-preview
DB=habita_ai_staging
MONGO_SECRET=mongodb-uri-staging
SA_API=habita-staging-api@$P.iam.gserviceaccount.com # reads the four backend secrets, nothing else
MAPS_SECRET=maps-static-api-key # dedicated key: Maps Static + Street View Static only (HR-006 PDF images)
SA_WEB=habita-staging-web@$P.iam.gserviceaccount.com # no permissions at all
BACKEND=habita-backend-staging
FRONTEND=habita-frontend-staging
WEB_PORT=3000 # must stay 3000: the browser key allows http://localhost:3000/*
API_PORT=8081
[ "${1:-}" = --preflight ] || : "${BROWSER_MAPS_KEY:?export BROWSER_MAPS_KEY (the habita-browser-maps key; it is never printed)}"

run() { gcloud --project "$P" "$@"; }
fail() { echo "STOP: $*" >&2; exit 1; }
preview_revisions() {
  run run services list --region "$REGION" --filter='metadata.name~preview' \
    --format='value(metadata.name,status.latestReadyRevisionName,status.traffic[0].revisionName)'
}
# Outputs are captured before matching: with pipefail, `gcloud | grep -q` can hide a match behind SIGPIPE.
private_or_fail() { # a Cloud Run service must have its invoker IAM check on and no public member
  local policy disabled
  policy=$(run run services get-iam-policy "$1" --region "$REGION" --format=json)
  ! grep -Eq 'allUsers|allAuthenticatedUsers' <<<"$policy" || fail "$1 is publicly invokable."
  disabled=$(run run services describe "$1" --region "$REGION" \
    --format='value(metadata.annotations."run.googleapis.com/invoker-iam-disabled")')
  [ "$disabled" != true ] || fail "$1 has the invoker IAM check disabled."
}
no_inherited_roles_or_fail() { # the project and every ancestor (folders, organisation) must give the account nothing
  local roles
  roles=$(gcloud projects get-ancestors-iam-policy "$P" --flatten='policy.bindings[].members' \
    --filter="policy.bindings.members:serviceAccount:$1" --format='value(id,policy.bindings.role)')
  [ -z "$roles" ] || fail "$1 has roles on the project or its ancestors ($roles): only per-secret grants are allowed."
}

# 0. Preconditions (read-only)
[ -z "$(git status --porcelain)" ] || fail "working tree not clean."
git fetch -q origin "$BRANCH"
SHA=$(git rev-parse HEAD)
[ "$SHA" = "$(git rev-parse "origin/$BRANCH")" ] || fail "HEAD is not the pushed head of $BRANCH: push first."
T=staging-${SHA:0:7}
run secrets describe "$MONGO_SECRET" --format='value(name)' >/dev/null || fail "secret $MONGO_SECRET missing."
run secrets describe "$MAPS_SECRET" --format='value(name)' >/dev/null || fail "secret $MAPS_SECRET missing."
for sa in "$SA_API" "$SA_WEB"; do
  run iam service-accounts describe "$sa" --format='value(email)' >/dev/null || fail "service account $sa missing."
  no_inherited_roles_or_fail "$sa"
done
for secret in $(run secrets list --format='value(name.basename())'); do
  policy=$(run secrets get-iam-policy "$secret" --format=json)
  [[ "$policy" != *"$SA_WEB"* ]] || fail "$SA_WEB can read secret $secret: the frontend needs none."
  readers=$(jq -r '.bindings[]? | select(.role == "roles/secretmanager.secretAccessor") | .members[]' <<<"$policy")
  case "$secret" in "$MONGO_SECRET" | GOOGLE_MAPS_API_KEY | meta-api-key | "$MAPS_SECRET")
    grep -qxF "serviceAccount:$SA_API" <<<"$readers" || fail "$SA_API cannot read secret $secret: the backend needs it." ;;
    *) [[ "$policy" != *"$SA_API"* ]] || fail "$SA_API can read secret $secret (e.g. the preview's mongodb-uri)." ;;
  esac
done
public=$(gcloud projects get-ancestors-iam-policy "$P" --flatten='policy.bindings[].members' \
  --filter='policy.bindings.members:allUsers OR policy.bindings.members:allAuthenticatedUsers' \
  --format='value(id,policy.bindings.role)')
[ -z "$public" ] || fail "the project or an ancestor grants a role to allUsers/allAuthenticatedUsers ($public)."
for s in "$BACKEND" "$FRONTEND"; do
  found=$(run run services list --region "$REGION" --filter="metadata.name=$s" --format='value(metadata.name,metadata.labels.env)')
  [ -n "$found" ] || continue
  [ "$(awk '{print $2}' <<<"$found")" = staging ] || fail "$s exists but is not labelled env=staging."
  private_or_fail "$s" # a redeploy must not publish the new revision on a service made public meanwhile
done
PREVIEW_BEFORE=$(preview_revisions)
[ "${1:-}" != --preflight ] || { echo "Preflight passed for $T: nothing was built or deployed."; exit 0; }

# 1. Tests (no credentials)
(cd backend && .venv/bin/pytest -q -p no:cacheprovider)
(cd frontend && npm test && npm run lint && npm run typecheck)

# 2. Images from the committed tree only (git archive), labelled with the commit. The Maps key is passed by name, so
#    docker reads it from the environment instead of the command line (it ends up in the public bundle by design).
SRC=$(mktemp -d)
trap 'rm -rf "$SRC"' EXIT
git archive "$SHA" | tar -x -C "$SRC"
DOCKER_BUILDKIT=1 docker build -q -f "$SRC/infrastructure/docker/backend.Dockerfile" \
  --label "org.opencontainers.image.revision=$SHA" -t "$R/backend:$T" "$SRC/backend"
NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=$BROWSER_MAPS_KEY DOCKER_BUILDKIT=1 docker build -q \
  -f "$SRC/infrastructure/docker/frontend.Dockerfile" --label "org.opencontainers.image.revision=$SHA" \
  --build-arg "NEXT_PUBLIC_API_BASE_URL=http://localhost:$API_PORT" --build-arg NEXT_PUBLIC_GOOGLE_MAPS_API_KEY \
  -t "$R/frontend:$T" "$SRC/frontend"
docker push -q "$R/backend:$T"
docker push -q "$R/frontend:$T"

# 3. Private services: IAM-only invocation, one instance (service and revision level), bounded resources (the rate
#    limiter is per process)
COMMON=(--region "$REGION" --no-allow-unauthenticated --invoker-iam-check --ingress all
  --min 0 --max 1 --min-instances 0 --max-instances 1 --cpu 1 --memory 512Mi --labels "env=staging,commit=${SHA:0:7}")
run run deploy "$BACKEND" --image "$R/backend:$T" --service-account "$SA_API" "${COMMON[@]}" \
  --concurrency 10 --timeout 300 \
  --set-env-vars "APP_ENV=staging,MONGODB_DB_NAME=$DB,SOURCE_INGEST_ON_STARTUP=true,BACKEND_CORS_ORIGINS=http://localhost:$WEB_PORT" \
  --set-secrets "MONGODB_URI=$MONGO_SECRET:latest,GOOGLE_MAPS_API_KEY=GOOGLE_MAPS_API_KEY:latest,META_API_KEY=meta-api-key:latest,MAPS_STATIC_API_KEY=$MAPS_SECRET:latest"
run run deploy "$FRONTEND" --image "$R/frontend:$T" --service-account "$SA_WEB" "${COMMON[@]}" \
  --concurrency 40 --timeout 60

# 4. Checks: staging database, private, anonymous refused, authenticated ready, preview unchanged
db=$(run run services describe "$BACKEND" --region "$REGION" --format=json \
  | jq -r '.spec.template.spec.containers[0].env[] | select(.name == "MONGODB_DB_NAME") | .value')
[ "$db" = "$DB" ] || fail "$BACKEND is not configured with MONGODB_DB_NAME=$DB."
for s in "$BACKEND" "$FRONTEND"; do
  private_or_fail "$s"
  url=$(run run services describe "$s" --region "$REGION" --format='value(status.url)')
  code=$(curl -s -o /dev/null -w '%{http_code}' "$url/")
  [ "$code" = 403 ] || [ "$code" = 401 ] || fail "$s answered $code to an anonymous request (expected 401/403)."
done
[ "$(preview_revisions)" = "$PREVIEW_BEFORE" ] || fail "preview revisions changed during the deploy: investigate."
BACKEND_URL=$(run run services describe "$BACKEND" --region "$REGION" --format='value(status.url)')
# The token stays in a shell variable (not exported); printf is a builtin, so it reaches curl on stdin, never argv.
token=$(gcloud auth print-identity-token) && [ -n "$token" ] || fail "gcloud could not issue an identity token."
code=$(printf 'Authorization: Bearer %s\n' "$token" | curl -s -o /dev/null -w '%{http_code}' -H @- "$BACKEND_URL/health/ready")
unset token
[ "$code" = 200 ] || fail "authenticated /health/ready answered $code: if 401, the gcloud credential's identity tokens are \
not accepted by Cloud Run (STAGING.md, Troubleshooting); the services are deployed and private."

cat <<EOF
Staging $T deployed (database $DB). Open it through the local proxies, one terminal each:
  gcloud run services proxy $BACKEND  --region $REGION --project $P --port $API_PORT
  gcloud run services proxy $FRONTEND --region $REGION --project $P --port $WEB_PORT
then browse http://localhost:$WEB_PORT (not 127.0.0.1: CORS and the Maps key allow localhost only).
EOF
