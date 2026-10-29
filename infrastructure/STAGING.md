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

## Private staging for HR-004 / HR-006 (prepared, not run)
`infrastructure/deploy-staging.sh` deploys the pushed head of `mu9/structural-verification` to two **new, private**
services, `habita-backend-staging` and `habita-frontend-staging`, on database `habita_ai_staging`.

| Requirement | How it is met |
|---|---|
| No anonymous access | `--no-allow-unauthenticated --invoker-iam-check`; the preflight refuses if the project or any ancestor grants a role to `allUsers`/`allAuthenticatedUsers`; before a redeploy and after every deploy it checks that neither service grants `allUsers`/`allAuthenticatedUsers` or has the invoker IAM check disabled, and that an anonymous request gets 401/403. Only principals with `roles/run.invoker` (the project owner has it) can reach them, through `gcloud run services proxy`. |
| Preview untouched | The script only deploys the two `*-staging` names, refuses to reuse a service without the `env=staging` label, and compares the preview services' revisions and traffic before and after. Images get new `staging-<sha>` tags; no existing tag is replaced. |
| Bounded | `--min 0 --max 1` (service level, across revisions) and `--min-instances 0 --max-instances 1` (revision level), `--cpu 1 --memory 512Mi`; concurrency 10 (backend, timeout 300 s for the model calls) and 40 (frontend). One instance keeps the in-process rate limiter (`backend/app/core/rate_limit.py`) close to exact; Cloud Run may briefly exceed the maximum during spikes or revision changes, so it is a bound, not a guarantee. |
| Isolated database | `MONGODB_URI` comes from the **separate** secret `mongodb-uri-staging` (an Atlas user limited to `habita_ai_staging`, see setup), read only by the backend's service account `habita-staging-api`. The preflight refuses if that account cannot read one of its three secrets or can read any other (such as the preview's `mongodb-uri`), if the frontend's account `habita-staging-web` can read any secret, or if either holds any role on the project or its ancestors (folders, organisation). A secret name proves nothing about its content, so at startup the backend asks MongoDB for its own privileges (`connectionStatus`) and refuses to start unless they cover `habita_ai_staging` and nothing else (no other database, cluster or any-resource grant). Nothing is copied from `habita_ai`; the database starts empty and `SOURCE_INGEST_ON_STARTUP=true` ingests the public official sources (cascais.pt). |
| No silent fallback | With `APP_ENV=staging` the backend refuses to start unless `MONGODB_DB_NAME=habita_ai_staging` and `MONGODB_URI` are set (`Settings._staging_is_isolated`); without them it would otherwise default to `habita_ai`. The script also re-reads the deployed variable. |
| Built from the pushed commit | Clean tree, `git fetch`, HEAD equal to the remote branch head; images are built from `git archive <sha>` and labelled `org.opencontainers.image.revision`. The browser Maps key is passed to `docker build` by name (read from the environment), not on the command line. |

MU-9: with no stored floor the application applies `DEFAULT_FLOOR` (fail closed). The server-side validator is
installed by `python -m app.maintenance raise-protocol-floor …` against `habita_ai_staging` (optional, needs the URI).

### Browser addresses and the proxy
The frontend is built with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8081` and the backend allows only the CORS
origin `http://localhost:3000`. All API calls are made by the browser (no server-side fetch), so with both proxies
running the browser talks to `localhost:3000` and `localhost:8081` only. `gcloud run services proxy` sends its identity
token in `X-Serverless-Authorization`, so the application's own `Authorization: Bearer <matter token>` reaches the
backend unchanged (checked in the proxy's source). Residual: gcloud hands the proxy its identity token as a
`-token` argument, visible to other processes of the same machine for its lifetime (up to 1 h). It is your user identity token, so it
can invoke any Cloud Run service you may invoke, not only staging; run the proxies on your own workstation only. Open `http://localhost:3000`, not `127.0.0.1`: CORS and the Maps key allow `localhost` only. The
proxy renews its token every 55 minutes, with a brief reconnect.

Checked locally (2026-10-29, containers, no Cloud Run): frontend image built for these addresses serves `/`,
`/property/<id>` and `/privacy`; its bundle carries `http://localhost:8081`; the backend with the staging variables and a
local MongoDB starts, writes only `habita_ai_staging`, answers CORS for `http://localhost:3000` (also on error
responses) and refuses `http://127.0.0.1:3000`; without `MONGODB_DB_NAME`, or with `habita_ai`, it does not start and the
error does not echo the URI. Against a local MongoDB with authentication: a user with the role below starts; a user
whose grants also cover `habita_ai`, or a `dbOwner` of `habita_ai_staging`, is refused; a plain `readWrite` user is refused by MU-9, which needs `collMod` to
install its validator.

### Google Maps keys (reviewed 2026-10-29, unchanged)
- `habita-browser-maps` (inlined in the frontend bundle by design): Maps JavaScript and Places only; referrers are the
  two preview URLs and `http://localhost:3000/*`. The proxy on port 3000 works with no key change, so the script pins
  that port. A referrer can be forged outside a browser, so this restriction limits embedding, not spending: cap the
  daily quota of those APIs (see Costs).
- `habita-server-geocoding` (secret `GOOGLE_MAPS_API_KEY`): Geocoding only, no application restriction (Cloud Run has
  no fixed egress IP). In staging it is reachable only through the private backend.

### One-time setup by the owner (each step needs separate authorisation)
```bash
P=habita-ai-512916; API=habita-staging-api@$P.iam.gserviceaccount.com
# 1. Atlas: custom role "habitaStagingApp" = built-in readWrite@habita_ai_staging + action collMod on
#    habita_ai_staging (MU-9 installs a validator); database user "habita-staging" with that role only.
#    Network access as for the preview user.
# 2. Its URI as a new secret, typed at a hidden prompt (never on the command line or in the history):
read -rsp 'staging MongoDB URI: ' URI; echo
printf '%s' "$URI" | gcloud secrets create mongodb-uri-staging --project $P --replication-policy=automatic --data-file=-
unset URI
# 3. Runtime service accounts (the IAM API is disabled on the project today and must be enabled first):
gcloud services enable iam.googleapis.com --project $P
gcloud iam service-accounts create habita-staging-api --project $P --display-name="HABITA staging backend"
gcloud iam service-accounts create habita-staging-web --project $P --display-name="HABITA staging frontend (no access)"
for s in mongodb-uri-staging GOOGLE_MAPS_API_KEY meta-api-key; do
  gcloud secrets add-iam-policy-binding $s --project $P --member=serviceAccount:$API --role=roles/secretmanager.secretAccessor
done
# 4. Read-only check before authorising the deploy:
infrastructure/deploy-staging.sh --preflight
```

### Deploy, open and test
```bash
git fetch origin && git status          # clean, on mu9/structural-verification, HEAD pushed
export BROWSER_MAPS_KEY=$(gcloud services api-keys get-key-string \
  "$(gcloud services api-keys list --project habita-ai-512916 --filter='displayName=habita-browser-maps' --format='value(name)')" \
  --format='value(keyString)')          # not printed
infrastructure/deploy-staging.sh        # tests, build, push, deploy, checks
# one terminal each:
gcloud run services proxy habita-backend-staging  --region us-central1 --project habita-ai-512916 --port 8081
gcloud run services proxy habita-frontend-staging --region us-central1 --project habita-ai-512916 --port 3000
```
Then in the browser, at `http://localhost:3000`: resolve a public demo address (e.g. "Praça 5 de Outubro, Cascais");
HR-004: the map loads, post-its appear and follow the current matter version; HR-006: the property report and its PDF
download. Another evaluator needs `roles/run.invoker` on both services (`gcloud run services add-iam-policy-binding`,
an IAM change: authorise it separately) and gcloud on their machine.

### Rollback and removal
The preview is never involved, so rolling back staging means removing it:
```bash
P=habita-ai-512916; R=us-central1-docker.pkg.dev/$P/habita-preview; T=staging-<sha>
gcloud run services delete habita-backend-staging  --region us-central1 --project $P --quiet
gcloud run services delete habita-frontend-staging --region us-central1 --project $P --quiet
# Remove the staging images: untag first (`images delete --delete-tags` would drop every tag on that digest, preview
# tags included), then delete the digest only if no tag is left on it (an untagged digest is still stored and billed).
tags_json() { gcloud artifacts docker images list $R/$1 --include-tags --format=json 2>/dev/null; }
for img in backend frontend; do
  d=$(tags_json $img | jq -r --arg t "$T" '.[] | select((.tags // []) | index($t)) | .version')
  [ -n "$d" ] || continue
  gcloud artifacts docker tags delete $R/$img:$T --quiet
  left=$(tags_json $img | jq -r --arg d "$d" '.[] | select(.version == $d) | (.tags // []) | length')
  [ "$left" = 0 ] && gcloud artifacts docker images delete $R/$img@$d --quiet
done
# Back to an earlier staging revision instead: gcloud run services update-traffic <service> --to-revisions <rev>=100
# Full clean-up (optional): gcloud secrets delete mongodb-uri-staging; gcloud iam service-accounts delete
# habita-staging-api@… and habita-staging-web@…; in Atlas, drop habita_ai_staging, the user and the role.
```

### Costs
List prices at the time of writing (us-central1); check the billing console before relying on them.
- Cloud Run, request-based billing, scaled to zero when idle: nothing while unused. The free tier per billing account
  (180,000 vCPU-s, 360,000 GiB-s and 2 million requests per month) is shared with the preview; a few hours of
  evaluation stay well inside it.
- Artifact Registry: about 1.1 GB per staging image pair on top of the existing ~0.75 GB; beyond the free 0.5 GB, about
  US$0.10 per GB-month. Remove old staging images as under Rollback (untagging alone keeps them billed).
- Paid APIs, the only real exposure: Geocoding and Maps JavaScript (each with a monthly free allowance, then a few
  dollars per 1,000 calls) and the Meta Model API (pricing not verified). Private access limits callers to invokers;
  the in-process limits (30 resolutions and 6 permit runs per minute) bound a runaway client.
- Controls to set (owner, separately authorised; the budget API is disabled on the project and the billing account
  was not readable from this workstation): a budget alert on the billing account (`gcloud billing budgets create`, or
  *Billing → Budgets & alerts*), and daily request caps for Geocoding, Maps JavaScript and Places
  (*APIs & Services → Quotas*). After the evaluation, remove staging (above).

## Procedure for the existing preview (do not run without authorisation)
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
- Preview: ingress is `all` and both preview services grant `allUsers` the invoker role, so anyone with the URL can
  use the Google and Meta keys through the API (rate limits apply). The staging services are private. Keep `--min-instances 0` outside demos (billing).
- The browser key ends up in the frontend bundle by design; it must stay HTTP-referrer restricted.
- Pointing a new version at `habita_ai` shares data with the current demo; see Database isolation.
- Webhooks on the GitHub repository could not be listed without owner credentials; check *Settings → Webhooks*
  before assuming no external integration reacts to pushes.
