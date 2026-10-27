# Demo runbook

Goal: the demo works even if Google quota, a cold start or the network misbehave on stage.

## Before the demo (T–30 min)

1. **Warm the services.** Scaling to zero is right for the preview, but not on stage:
   ```bash
   gcloud run services update habita-backend-preview  --region us-central1 --min-instances 1
   gcloud run services update habita-frontend-preview --region us-central1 --min-instances 1
   ```
   Set both back to `--min-instances 0` afterwards (an always-on instance is billed).
2. **Check readiness:** `curl https://habita-backend-preview-988261836110.us-central1.run.app/health/ready` should return `{"status":"ready"}` (Atlas reachable).
3. **Seed the hero properties.** Resolve the three example addresses once (each costs one or two paid Geocoding calls). Note the returned `property_id`s:
   ```bash
   BE=https://habita-backend-preview-988261836110.us-central1.run.app
   for a in "Praça 5 de Outubro, Cascais" "Avenida dos Aliados, Porto" "Largo da Sé, Funchal"; do
     curl -s -X POST $BE/api/property/resolve-location -H 'Content-Type: application/json' \
       -d "{\"address\":\"$a\"}" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["property_id"], d["formatted_address"])'
   done
   ```
4. Open each workspace URL (`/property/<id>`) once in the demo browser to warm the map and check it renders.

## On stage

1. Lead with the **workspace URLs** of the seeded properties. They're served from Atlas with no Google calls on the backend (only the browser map load).
2. Do **one live search** (type a Cascais address, pick a suggestion) to show the full path.
3. **Fallbacks:**
   - If the live search fails, go back to a seeded URL.
   - If the map fails (key/referrer), the panel still shows the address, jurisdiction and authority.
   - A `rate_limited` message means the in-app spend limit (30 resolutions/min) was hit: wait for the shown delay.
