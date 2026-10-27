# HABITA AI
Global AI operating system for property intelligence, jurisdiction discovery, permitting, and affordability.

Built for the Meta Global AI Developer Hackathon.

## Repository layout
| Path | Purpose |
|---|---|
| `frontend/` | Next.js + React web app |
| `backend/` | Python FastAPI API and agent orchestration |
| `docs/` | Architecture and environment docs |
| `infrastructure/` | Google Cloud Run / Artifact Registry / Secret Manager setup |

## Stack
Next.js · FastAPI · MongoDB Atlas · Google Maps Platform · Meta Model API (Muse Spark, SAM 3.1, Muse Voice Transcribe, Muse Image) · Google Cloud Run

## Getting started
1. `cp .env.example .env` and fill in your values locally. **Never commit secrets.**
2. Read [`docs/environment.md`](docs/environment.md) and [`docs/architecture.md`](docs/architecture.md).

Status: first vertical slice built (*Property → Location → Jurisdiction*). See `backend/README.md` and `frontend/README.md` to run it.
