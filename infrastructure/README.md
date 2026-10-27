# infrastructure/

Deployment target: **Google Cloud Run** (two services), images in **Artifact Registry**, secrets in **Secret Manager**. Nothing has been provisioned yet.

One-time setup (build window; run with the HABITA GCP project active):
```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com
gcloud artifacts repositories create "$ARTIFACT_REGISTRY_REPO" \
  --repository-format=docker --location="$GOOGLE_CLOUD_REGION"
# Create secrets interactively. Never pass secret values as CLI args in shared shells:
gcloud secrets create MONGODB_URI --replication-policy=automatic
gcloud secrets versions add MONGODB_URI --data-file=-   # paste, then Ctrl-D
# Repeat for META_API_KEY, GOOGLE_MAPS_API_KEY
```
Deploy (later): `gcloud run deploy habita-backend --source backend --set-secrets=...`.
Dockerfiles and deploy scripts will live here or in each app folder.
