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
| Isolated database | `MONGODB_URI` comes from the **separate** secret `mongodb-uri-staging` (the application user `habita-staging-app`, `readWrite` on `habita_ai_staging` only, see Database users), read only by the backend's service account `habita-staging-api`. The preflight refuses if that account cannot read one of its three secrets or can read any other (such as the preview's `mongodb-uri`), if the frontend's account `habita-staging-web` can read any secret, or if either holds any role on the project or its ancestors (folders, organisation). A secret name proves nothing about its content, so at startup the backend asks MongoDB for its own privileges (`connectionStatus`) and refuses to start unless they cover `habita_ai_staging` and nothing else (no other database, cluster or any-resource grant) and include no administrative action, `collMod` and `bypassDocumentValidation` included. Nothing is copied from `habita_ai`; the database starts empty and `SOURCE_INGEST_ON_STARTUP=true` ingests the public official sources (cascais.pt). |
| No silent fallback | With `APP_ENV=staging` the backend refuses to start unless `MONGODB_DB_NAME=habita_ai_staging` and `MONGODB_URI` are set (`Settings._staging_is_isolated`); without them it would otherwise default to `habita_ai`. The script also re-reads the deployed variable. |
| Built from the pushed commit | Clean tree, `git fetch`, HEAD equal to the remote branch head; images are built from `git archive <sha>` and labelled `org.opencontainers.image.revision`. The browser Maps key is passed to `docker build` by name (read from the environment), not on the command line. |

MU-9: with no stored floor the application applies `DEFAULT_FLOOR` (fail closed). The application installs the
server-side validator itself on the empty database (it creates `permit_verifications` with the rule, which `readWrite`
allows); changing it later needs the migration user (below).

### Database users: application and migration
`collMod` is needed only to **change** the MU-9 validator of `permit_verifications`, never to serve requests: the
application checks at startup that the rule for the stored floor is in force, creates the collection with it when the
database is new (`createCollection`, part of `readWrite`), and calls `collMod` only when the installed rule differs.
In staging, the two permission sets are separate:

| User | Atlas role | Used by | Stored |
|---|---|---|---|
| `habita-staging-app` | built-in `readWrite@habita_ai_staging` | the Cloud Run backend | secret `mongodb-uri-staging` |
| `habita-staging-migrate` | custom `habitaStagingMigrate` = `readWrite@habita_ai_staging` + `collMod` on `habita_ai_staging` | the owner, from a workstation: `apply-validator` after a release that changes the rule, `raise-protocol-floor` | nowhere: an Atlas temporary user (expires), URI typed at a hidden prompt |

The backend refuses to start in staging if its user holds `collMod` (or any administrative action), and refuses to start
without rollback protection if the rule in force is not the current one; the log then names `apply-validator`. Neither
user exists on the preview database, and the preview's user is never reused. Same cluster as the preview (separate
database and users); a separate cluster would also separate load and backups, at extra cost.

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
error does not echo the URI. Against a local MongoDB with authentication: the `readWrite` application user starts on an
empty database (the collection is created with the validator) and restarts without `collMod`; after the rule was changed
it refuses to start, `apply-validator` as the migration user restores it, and it starts again; an application user
holding `collMod`, a `dbOwner` of `habita_ai_staging`, or a user whose grants also cover `habita_ai` is refused.

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
# 1. Atlas project "HABITA AI" (6adfdf61d52b2b35f1de0cf3), cluster habita-ai-m0 (M0, MongoDB 8.0), Atlas CLI profile
#    "habita" (confirmed read-only 2026-10-29: the preview's user habita_app has readWrite@habita_ai only, no custom
#    roles yet). Network Access is 0.0.0.0/0 today ("temporary hackathon preview access"): Cloud Run reaches the
#    cluster with no change; the credentials are the only barrier.
#    a) application user, in the UI (Add New Database User): username habita-staging-app, "Autogenerate Secure
#       Password" (so it never appears on a command line), Database User Privileges → Specific Privileges → Add
#       Specific Privilege → role readWrite, database habita_ai_staging (the Built-in Role menu has only
#       any-database roles: do not use it),
#       Restrict Access to Specific Clusters → habita-ai-m0.
#    b) migration role only (no user yet; the user is created when a migration is needed, see Migrations):
atlas customDbRoles create habitaStagingMigrate --privilege COLL_MOD@habita_ai_staging \
  --inheritedRole readWrite@habita_ai_staging --projectId 6adfdf61d52b2b35f1de0cf3 -P habita
atlas customDbRoles describe habitaStagingMigrate --projectId 6adfdf61d52b2b35f1de0cf3 -P habita -o json   # verify
atlas dbusers describe habita-staging-app --projectId 6adfdf61d52b2b35f1de0cf3 -P habita -o json   # after a): roles, scopes
# 2. Secret mongodb-uri-staging: run in an interactive terminal (not through an agent). It reads the password with
#    getpass (hidden; never on argv, in the environment, a file, the history or any output), checks against Atlas that
#    the user is habita-staging-app with application privileges on habita_ai_staging only (app.db.staging), sends the
#    URI (cluster habita-ai-m0, database habita_ai_staging, authSource=admin) to gcloud on stdin, then lists the
#    enabled versions. It never replaces an existing secret: it shows its metadata and stops.
backend/.venv/bin/python infrastructure/create_staging_secret.py
#    After a later password change the script stops (the secret exists): adding a version and disabling the old
#    one is a separate, authorised step.
#    Readers: habita-staging-api (granted on this secret only, step 3) and, through roles/owner, the project owner;
#    nobody else holds a project or organisation role that reads secrets (checked 2026-10-30).
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

### Setup log
| Date | Step | Done by | Result (verified read-only) |
|---|---|---|---|
| 2026-10-29 | Atlas custom role `habitaStagingMigrate` (owner-authorised; profile `habita`, project 6adfdf61d52b2b35f1de0cf3) | Claude, Atlas CLI | Role did not exist before. Now: action `COLL_MOD` on `habita_ai_staging` (whole database) + inherited `readWrite@habita_ai_staging`; assigned to no user. Users unchanged (`habita_app`: `readWrite@habita_ai`, scope `habita-ai-m0`); network access unchanged; no database or data touched. |
| 2026-10-29 | Atlas user `habita-staging-app` | owner, Atlas UI (generated password) | Only role `readWrite@habita_ai_staging`; scope cluster `habita-ai-m0`; no expiry; password authentication only (no X.509/IAM/LDAP/OIDC); not assigned `habitaStagingMigrate`. `habita_app` unchanged (`readWrite@habita_ai`, `habita-ai-m0`); role and network access unchanged. |
| 2026-10-30 | Password of `habita-staging-app` replaced in Atlas (the first one appeared in a screenshot) | owner, Atlas UI | roles and scope unchanged (verified read-only) |
| 2026-10-30 | `infrastructure/create_staging_secret.py` prepared (owner-run, hidden prompt, Atlas privilege check before creation, never replaces a secret) | Claude | reviewed by Codex (3 rounds, clean); tests and local MongoDB 7/8.0 checks pass. A PTY test with a dummy password made one failed login attempt on habita-ai-m0 (nothing read or changed) |
| 2026-10-30 | Secret `mongodb-uri-staging` | owner, `create_staging_secret.py` | Created 01:49:37Z, label env=staging, automatic replication; version 1 enabled; no secret-level grants yet (content never displayed) |
| 2026-10-30 | Atlas check from the secret (read-only, URI piped from Secret Manager) | Claude | Authenticates as `habita-staging-app`; privileges only on `habita_ai_staging`, exactly the readWrite actions (Atlas adds none); `confinement_problem` OK; default database `habita_ai_staging`; listCollections on `habita_ai` refused (AtlasError 8000); no database created |
| 2026-10-30 | IAM API enabled; `habita-staging-api`, `habita-staging-web` created; `secretAccessor` for the API account on `mongodb-uri-staging`, `GOOGLE_MAPS_API_KEY`, `meta-api-key` only | Claude (owner-authorised) | `mongodb-uri-staging` readable only by the API account (plus the owner via roles/owner); preview `mongodb-uri` unchanged; web account has no secret access; neither account has project/ancestor roles or user-managed keys. Codex: staging grants correct, nothing missing for deploy |
| 2026-10-30 | Push of `mu9/structural-verification` only (334a5bd..1182201) | Claude (owner-authorised) | full tests on 1182201 (backend 6589 passed / 14 skipped / 3 xfailed; frontend 37, lint, typecheck); no credentials in the pushed diff; `origin/main` unchanged at 98af6af; full preflight passed |
| 2026-10-30 | Deploy `staging-1182201` (images from `git archive` of 1182201) | Claude (owner-authorised) | `habita-backend-staging-00001-djm` (SA habita-staging-api, `APP_ENV=staging`, `MONGODB_DB_NAME=habita_ai_staging`, secrets by reference, max 1 instance, concurrency 10) and `habita-frontend-staging-00001-gcb` (SA habita-staging-web, max 1); no IAM bindings, anonymous requests 403; backend started on Atlas: 7 collections in `habita_ai_staging`, MU-9 validator `moderate`/`error` installed with readWrite only, 27 official sources seeded, no warnings in the logs; preview still 00016/00011 at 100%. The script stopped at its authenticated health check (HTTP 401, see Troubleshooting); the preview comparison was then done by hand |
| 2026-10-30 | 401 diagnosis; official `google-cloud-cli-cloud-run-proxy` 591.0.0 installed (apt, Google repo) | Claude (owner-authorised) | account `paulinoliliptec@gmail.com` correct; `run.routes.invoke` granted on both services (testIamPermissions); identity token `aud` = `681255809395-….apps.googleusercontent.com` (not the gcloud CLI client): rejected, also through the proxy (401). No IAM, access-policy or service change |
| pending | Re-authentication with the gcloud CLI client, then the HR-004/HR-006 demo | owner action, then test | blocked on the token audience |

### Troubleshooting
- **Authenticated requests get 401 "access token could not be verified"** (seen 2026-10-30): the stored gcloud
  credential of the account was issued by another OAuth client (identity token `aud` `681255809395-….apps.googleusercontent.com`
  instead of the gcloud CLI client `32555940559.apps.googleusercontent.com`), and Cloud Run does not accept it; the
  proxy uses the same token. Fix: re-authenticate gcloud with the CLI's own client, forcing a new authorisation flow,
  `gcloud auth login --force paulinoliliptec@gmail.com`, then check (prints only claims): `gcloud auth print-identity-token | python3 -c 'import
  sys,json,base64;p=sys.stdin.read().split(".")[1];print(json.loads(base64.urlsafe_b64decode(p+"="*(-len(p)%4)))["aud"])'`.
- **This development machine is a Cloud Workstation** (`w-drakiesseai-…`, project `dra-kiesse`, europe-southwest1),
  not the owner's computer. A browser opening its port 3000 goes through Workstations port forwarding
  (`*.cloudworkstations.dev`), which needs `workstations.workstations.use` for the browser's Google account and, even
  then, cannot run the demo: the page would call `http://localhost:8081` on the browser's own computer, and CORS and
  the Maps key allow only `http://localhost:3000`. Run the two proxies on the computer where the browser runs (gcloud
  installed there, `gcloud components install cloud-run-proxy`, `gcloud auth login paulinoliliptec@gmail.com`); that
  also yields identity tokens from the gcloud CLI client.
- **Several Google accounts in the browser**: the browser never needs a Google login for staging (the proxy adds the
  identity). Open `http://localhost:3000` in a private window or a browser profile without Google accounts; opening
  the `run.app` URLs directly only shows a 403/login error by design. In the `gcloud auth login --force` account
  chooser, pick `paulinoliliptec@gmail.com` explicitly.
- **`gcloud run services proxy` asks to install `cloud-run-proxy`** (installed on this workstation 2026-10-30): the SDK here comes from apt, so install the
  component as a package: `sudo apt-get install google-cloud-cli-cloud-run-proxy`.

### Migrations (only when needed)
Needed when the backend logs `MU-9: could not install the permit_verifications validator` after a release, or to raise
the protocol floor. Not needed for the first deploy.
```bash
# Atlas UI: temporary user habita-staging-migrate, role habitaStagingMigrate, cluster habita-ai-m0, delete after 6 hours.
cd backend
read -rsp 'staging MIGRATION MongoDB URI: ' URI; echo
MONGODB_URI=$URI APP_ENV=staging MONGODB_DB_NAME=habita_ai_staging .venv/bin/python -m app.maintenance apply-validator
unset URI    # the variable lives only in this shell and the command's environment, never on its argv
```

### Publication sequence (each step separately authorised; no CI/CD involved)
1. **Secret** (owner, own interactive terminal): `backend/.venv/bin/python infrastructure/create_staging_secret.py`.
   Its Atlas check is the first real test of the staging user against `habita-ai-m0`; on STOP, its message names the
   cause without credentials. Afterwards, metadata only: `gcloud secrets versions list mongodb-uri-staging`.
2. **IAM** (step 3 of the one-time setup): IAM API, the two service accounts, three per-secret grants for the backend.
3. **Push the branch only, never `main`** (the commit approved for publication; before it, the read-only checks run
   from a copy of the preflight without its push check):
   ```bash
   git fetch origin && MAIN_BEFORE=$(git rev-parse origin/main)
   git status --porcelain                              # must be empty
   git push origin mu9/structural-verification         # explicit refspec: main is not pushed
   git fetch origin && [ "$(git rev-parse origin/main)" = "$MAIN_BEFORE" ] && echo "main unchanged"
   [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/mu9/structural-verification)" ] && echo "HEAD published"
   ```
4. **Preflight**: `infrastructure/deploy-staging.sh --preflight` (clean tree, HEAD equal to the pushed head).
5. **Deploy** (below): images built from `git archive` of that exact commit, tagged `staging-<sha>`, private services,
   preview revisions compared before and after.
6. **Real checks**: the script's own checks (401/403 anonymously, ready through IAM, database variable, preview
   unchanged), then the demo test through the proxies. Staging is operational only after these pass.

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
The proxies and the browser must run on the same machine, with gcloud signed in as an invoker (the owner is).
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
# habita-staging-api@… and habita-staging-web@…; in Atlas, drop habita_ai_staging, delete
# habita-staging-app (and any habita-staging-migrate) and the role habitaStagingMigrate.
```

### Costs
List prices at the time of writing (us-central1); check the billing console before relying on them.
- Cloud Run, request-based billing, scaled to zero when idle: nothing while unused. The free tier per billing account
  (180,000 vCPU-s, 360,000 GiB-s and 2 million requests per month) is shared with the preview; a few hours of
  evaluation stay well inside it.
- Artifact Registry: the first staging pair added about 0.24 GB compressed (repository 0.75 → 0.99 GB, 2026-10-30); beyond the free 0.5 GB, about
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
