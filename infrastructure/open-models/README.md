# Open-weight fallback models (afinamentos — prepared, not deployed)

When Meta's Muse Spark API is **unavailable** (timeout, transport error, 5xx, 429 after retries), the backend's
`FallbackChatModel` passes the same call to open-weight models, in order: **Modal**, then **Baseten**. A refusal (4xx)
or a malformed answer never falls back. Every draft, whoever wrote it, still goes through the deterministic MU-9
verifier and final gate; the record (`model_id` on checklist, draft and verification) names the model that answered.

Each provider is off unless its three backend settings are set:

| Provider | Settings | What it is |
|---|---|---|
| Modal | `MODAL_MODEL_BASE_URL`, `MODAL_MODEL_API_KEY`, `MODAL_MODEL_ID` | Our own vLLM server, `modal_vllm.py` (default `meta-llama/Llama-3.3-70B-Instruct` on 2×H100, scales to zero) |
| Baseten | `BASETEN_MODEL_BASE_URL`, `BASETEN_MODEL_API_KEY`, `BASETEN_MODEL_ID` | Baseten Model APIs (`https://inference.baseten.co/v1`, a hosted Llama slug) or a dedicated deployment's `/v1` URL |

Keys go to Secret Manager, never to the repository.

## Status and limits

- **Not deployed and not tested against a real endpoint**: no Modal or Baseten account or credentials on this
  workstation. Tested with fakes and a mocked HTTP transport (`backend/tests/test_model_fallback.py`).
- **Costs**: Modal bills GPU time while a container is up; Baseten bills per token (Model APIs) or per GPU minute
  (dedicated). Needs the owner's authorisation before any deploy.
- **Timing**: every attempt has a total deadline (not only httpx's per-read timeouts): `META_TIMEOUT_SECONDS` (90 s)
  for Muse Spark, `FALLBACK_TIMEOUT_SECONDS` (45 s) for each fallback, which tries once. Worst case of one call through
  the chain: 2 × 90 + 0.5 (retry pause) + 45 + 45 ≈ 271 s, under Cloud Run's 300 s. At startup a fallback whose worst
  case would pass 290 s is not wired (an error in the logs), e.g. with `META_TIMEOUT_SECONDS=120` only Modal stays.
  A Modal container scaled to zero takes minutes to load a 70B model, so the first call after idle passes on to Baseten while Modal warms up. For demo day, deploy with
  `HABITA_FALLBACK_WARM=1` (one container always up, billed all the time) and redeploy without it afterwards.
- **Quality**: an open-weight model may follow the strict schemas and citation rules less well than Muse Spark; MU-9
  then answers NOT VERIFIED (fail-closed), never a weaker VERIFIED. To be measured before relying on it.
- **Scope**: only the permit workflow (planning, investigation, draft, review) falls back. Reading the user's photos
  and plans stays on Muse Spark (vision, and those private files go only where the files notice says).
- **Privacy, before enabling**: the question, the property data and the evidence would then also reach Modal or Baseten
  (US providers). The privacy page and the processors list must say so first.
- **Licence**: Llama weights need the Llama licence accepted on Hugging Face; check its terms for the deployed use.
