# Environment & Workstation Setup

## Environment variables

The template is in [`/.env.example`](../.env.example) and holds placeholders only.

| Variable | Used by | Secret? | Description |
|---|---|---|---|
| `MONGODB_URI` | backend | **Yes** | Atlas SRV connection string for the separate **"HABITA AI"** Atlas project. Use a dedicated DB user with least privilege. |
| `MONGODB_DB_NAME` | backend | No | Database name (default `habita_ai`). |
| `META_API_KEY` | backend | **Yes** | Meta Model API key. Sent as `Authorization: Bearer <key>`. Meta's docs call this `MODEL_API_KEY`; we use `META_API_KEY` to avoid naming collisions. |
| `META_API_BASE_URL` | backend | No | `https://api.meta.ai/v1` |
| `META_TEXT_MODEL` | backend | No | Reasoning/agent model for Permit Intelligence; default `muse-spark-1.3`. Never a `-contributor` variant. |
| `META_REASONING_EFFORT` | backend | No | Optional `reasoning_effort` (`minimal`…`max`); omitted when unset. |
| `META_IMAGE_MODEL` | backend | No | `muse-image-1.0` |
| `META_TRANSCRIBE_MODEL` | backend | No | `muse-voice-transcribe-1.0` |
| `META_SEGMENTATION_MODEL` | backend | No | `sam-3.1` |
| `GOOGLE_MAPS_API_KEY` | backend | **Yes** | Server-side key for Geocoding/Places. Restrict to required APIs. |
| `MAPS_STATIC_API_KEY` | backend | No | Key for the Maps Static API (HR-006 PDF location maps). Unset: `GOOGLE_MAPS_API_KEY` is tried; without a key allowed to call the Static API the PDF says the maps are unavailable. Restrict to the Maps Static API and set a daily quota. |
| `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` | frontend | Public by design | Browser key for the Maps JavaScript API. Restrict by HTTP referrer **and** API. Keep it separate from the server key. |
| `GOOGLE_CLOUD_PROJECT` | infra | No | GCP project ID used for Cloud Run, Artifact Registry and Secret Manager. |
| `GOOGLE_CLOUD_REGION` | infra | No | Deployment region, e.g. `us-central1`. |
| `ARTIFACT_REGISTRY_REPO` | infra | No | Docker repo for built images. |
| `CLOUD_RUN_BACKEND_SERVICE` / `CLOUD_RUN_FRONTEND_SERVICE` | infra | No | Cloud Run service names. |
| `GOOGLE_APPLICATION_CREDENTIALS` | local only | **Yes (file)** | Optional. Prefer `gcloud auth application-default login`. Never on Cloud Run, which uses the service identity. |
| `NEXT_PUBLIC_API_BASE_URL` | frontend | No | Backend base URL. |
| `BACKEND_CORS_ORIGINS` | backend | No | Comma-separated allowed origins. |
| `SOURCE_INGEST_ON_STARTUP` | backend | No | `true` fetches and indexes the trusted Cascais documents once at startup, in the background (useful with the in-memory store). Default `false`: use `python -m app.maintenance ingest-sources`. |
| `SOURCE_FETCH_TIMEOUT_SECONDS` | backend | No | Timeout for official-source fetches (default 60). |
| `APP_ENV` | both | No | `development` / `production`. |

### Secret handling rules
- Real values live only in local `.env` / `frontend/.env.local` (git-ignored) and in **Google Secret Manager** for Cloud Run.
- Only `.env.example` is tracked. `.gitignore` blocks `.env` and `.env.*`.
- Never paste keys into prompts, commit messages, logs, or issue text. Don't `cat` env files in shared terminals.
- If a secret leaks, rotate it first, then clean up.

## Workstation (verified 2026-10-27)

| Tool | Status |
|---|---|
| OS | Ubuntu 24.04.5 LTS (Google Cloud Workstation) |
| Node.js / npm | v24.22.1 / 11.19.1 |
| Python | 3.12.3 |
| git | 2.43.0. HTTPS push to `origin` verified (credential store). |
| GitHub CLI `gh` | **Not installed.** Optional; git auth already works. |
| Docker | 29.9.2 |
| gcloud SDK | 590.0.0. Active project must be checked; see below. |
| Claude Code | 2.1.311 (`~/.local/bin/claude`, config `~/.claude`) |
| Codex CLI | 0.155.1 (`~/.npm-global/bin/codex`, config `~/.codex`), logged in |
| Muse Code | 1.4.13 (`~/.local/bin/muse`), installed via Meta's official `https://dev.meta.ai/install.sh`. **Login pending.** |

### Coding-agent coexistence
The three agents are separate binaries with separate config/credential stores and no shared command names, so they don't conflict. Guidelines:
- Run only one agent at a time on a given working tree, or give each agent its own git worktree/branch.
- Commit often so each agent's changes can be reviewed and reverted.
- Each agent may scaffold its own instruction file (`CLAUDE.md`, `AGENTS.md`, Muse `init`). Keep shared conventions in `docs/` and point those files at it.

### Pending manual steps
```bash
muse login                                   # interactive device-code login
gcloud config set project <habita-project>   # confirm the active project is the HABITA one
gcloud auth application-default login        # local ADC for SDKs
```
