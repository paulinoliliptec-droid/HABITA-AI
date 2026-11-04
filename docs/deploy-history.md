# Deployment history

Moved from the README on 2026-11-04 so that the README stays readable for the hackathon judges. Nothing was
removed: revisions, checks and rollbacks of the public demo and the private staging, as they were recorded.

## Private staging (authenticated)
A private staging runs on Cloud Run (`habita-backend-staging`, `habita-frontend-staging`) on an isolated database
(`habita_ai_staging`, its own least-privilege MongoDB user): no anonymous access, no public URL to open. It runs
commit `5734adc` (deployed and tested end to end on 2026-10-30).

## Public demo (original)
**https://habita-frontend-preview-jcyiz2arua-uc.a.run.app** — updated on 2026-11-03 (owner-authorised) to commit `f88957d`:
backend revision `00077` and frontend revision `00082` let the reader run the copilot on Muse Spark Open (Meta's open
weights on Baseten); checked on the candidates (health 3×200, a real copilot answer in PT from
`meta-models/muse-spark-open-1026` in 9 s, the frontend warmed 15×200, then 30×200 live). Rollback: backend `00075`,
frontend `00080`. Before that, updated on 2026-11-03 to commit `878f82d`:
backend revision `00075` and frontend revision `00080` speak the copilot's answers in the ElevenLabs voice and send a
dictated question by itself after 10 s of silence; checked on the candidates (health 3×200, a real copilot answer in
PT from Rua Frederico Arouca 30 and its ElevenLabs audio, the frontend warmed 15×200, then 30×200 live). Rollback:
backend `00073`, frontend `00078`. Before that, frontend updated on 2026-11-03 to commit
`8f8a345` (revision `00078`: the live copilot button and panel moved to the bottom-right corner; warmed 15×200, then
30×200 live; rollback revision `00076`; backend unchanged). Before that, updated on 2026-11-03 to commit
`3d30d65`: backend revision `00073` and frontend revision `00076` add the Meta terms confirmation (18+, restricted
territories, India for Muse Image) before the demo and the workspace, and the live report copilot (bottom-right); checked
on the candidates (health 3×200, fallback enabled, a real copilot answer from a Cascais report, the confirmation on
`/demo`, the frontend warmed 20×200, then 30×200 live). Rollback: backend `00071`, frontend `00074`. Before that, updated on 2026-11-03 (owner-authorised): backend
commit `be61e53` (revision `00071`: the Baseten fallback switched on — Muse Spark open answers only when Muse Spark is
unavailable, same MU-9 verifier; partial coverage for New York City, Paris and Singapore with their authority, official
sources, official market prices, and the aerial view on IGN and NYS orthophotos; safe rollback revisions `00069`,
`00067` and `00065`; `00063` and older are NOT safe rollbacks: they bring back the old verifier with the known
false-VERIFIED paths), frontend commit `3c97c8c` (revision `00074`: the owner's logo, the landing page with a photo of
Cascais and a large demo button with a note for the jury, Rua Frederico Arouca 30 as the reference address, New York,
Paris and Singapore as partial-coverage examples; rollback revision `00072`). Checked on the candidates before the
switch: health 3×200, the fallback logged as enabled, Paris and Cascais resolved with their authority, Paris prices,
one real aerial analysis of 5 Rue de Turenne, Paris (IGN, three buildings, 15 s, attribution in the image), the
frontend warmed 20×200 and then 30×200 live. Also live: with the aerial view (DGT orthophotos + Meta SAM 3.1), dictation (Muse Voice Transcribe),, with the reasoning graph, the spoken report, the property profile, request types, photos and plans, costs and price, before/after concepts, and views from a plan (3D, realistic, 3D with one more bedroom in the room the user chooses). The MU-9 migration of its database
ran on 2026-10-30 (verified backup, audit, nothing deleted). Known open item: phone layout needs polish.
Tested there on 2026-10-30: address search in Cascais, map and satellite view, post-its, a real permit question (VERIFIED under the
current protocol) and the PDF with road map, satellite and Street View. A frontend rollback to its previous revision
is one command (`infrastructure/STAGING.md`); a backend rollback must not go to a revision older than `00065`. Historical results verified under the old protocol are never shown
as current VERIFIED: they read as superseded (legacy, not revalidated), with their original provenance.

Access requires an authorised Google account and the official proxy, on the computer where the browser runs:
```bash
gcloud components install cloud-run-proxy
gcloud run services proxy habita-backend-staging  --region us-central1 --project habita-ai-512916 --port 8081
gcloud run services proxy habita-frontend-staging --region us-central1 --project habita-ai-512916 --port 3000
# then open http://localhost:3000 (a private window avoids conflicts between several Google accounts)
```
Procedure, checks, rollback and costs: [`infrastructure/STAGING.md`](infrastructure/STAGING.md).

