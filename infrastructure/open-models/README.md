# Fallback models for the reasoning model (afinamentos)

When Meta's Muse Spark API is **unavailable** (timeout, transport error, 5xx, 429 after retries), the backend's
`FallbackChatModel` passes the same call to the next configured model, in order: **Modal**, then **Baseten**. A
refusal (4xx) or a malformed answer never falls back. Every draft, whoever wrote it, still goes through the
deterministic MU-9 verifier and final gate; the record (`model_id` on checklist, draft and verification) names the
model that answered.

Each provider is off unless its three backend settings are set:

| Provider | Settings | What it is | State |
|---|---|---|---|
| Baseten | `BASETEN_MODEL_BASE_URL=https://inference.baseten.co/v1`, `BASETEN_MODEL_API_KEY` (Secret Manager `baseten-api-key`), `BASETEN_MODEL_ID=meta-models/muse-spark-open-1026` | **Muse Spark open**, Meta's open model, through Baseten's OpenAI-compatible Model APIs (hackathon key and credits) | Key stored, real calls tested, **chosen fallback**; not yet deployed |
| Modal | `MODAL_MODEL_BASE_URL`, `MODAL_MODEL_API_KEY`, `MODAL_MODEL_ID` | Our own vLLM server, `modal_vllm.py` (default `meta-llama/Llama-3.3-70B-Instruct` on 2×H100, scales to zero) | Prepared, **off**: GPU billing and cold starts outweigh it while Baseten covers outages |

Keys go to Secret Manager, never to the repository.

## Comparative run (2026-11-02)
The full permit flow (planning, investigation with tools, draft, MU-9 verification and review) on the same three
questions for a Cascais property, once per model, in memory. Script kept outside the repository; results below.

| Question | Muse Spark (Meta) | Muse Spark open (Baseten) |
|---|---|---|
| Convert into two residential units | VERIFIED, with conditions | REJECTED |
| Change of use, ground floor from shop to home (PT) | VERIFIED, with conditions | REJECTED |
| Renovate the kitchen and the bathroom | REJECTED | REJECTED |
| Model time per analysis | about 125 s | **about 60 s** |
| Per call (median / slowest) | 6.7 s / 61.9 s | **2.5 s / 34.1 s** |
| False VERIFIED | 0 | **0** |

Both models reach the same conclusion ("conditional: confirm the plan category with the Câmara"). Muse Spark open
follows HABITA's citation rules less closely: it labels a case fact as a general planning explanation and restates
plan rules in its own words instead of quoting the official text, so MU-9 refuses those drafts. **As a fallback it is
safe and fast: during a Meta outage HABITA keeps answering, mostly as "not verified", never with a false VERIFIED.** It
is not a replacement for the primary model today; prompt tuning for it is on the afinamentos list. Cost of the run:
about 100k Baseten tokens from the hackathon credits.

## Limits
- **Timing**: every attempt has a total deadline (not only httpx's per-read timeouts): `META_TIMEOUT_SECONDS` (90 s)
  for Muse Spark, `FALLBACK_TIMEOUT_SECONDS` (45 s) for each fallback, which tries once. Worst case of one call through
  the chain: 2 × 90 + 0.5 (retry pause) + 45 + 45 ≈ 271 s, under Cloud Run's 300 s. At startup a fallback whose worst
  case would pass 290 s is not wired (an error in the logs), e.g. with `META_TIMEOUT_SECONDS=120` only the first
  fallback stays. Residual: `META_TIMEOUT_SECONDS` of 150 s or more makes Muse Spark's own two attempts pass 300 s
  (pre-existing setting; default 90 s).
- **Reasoning tokens**: Muse Spark open reasons before answering, and the reasoning counts against `max_tokens`; HABITA
  sends no `max_tokens`, so answers are not cut.
- **Scope**: only the permit workflow (planning, investigation, draft, review) falls back. Reading the user's photos
  and plans stays on Muse Spark (vision, and those private files go only where the files notice says).
- **Privacy, before enabling**: during a Meta outage the question, the property data and the evidence would reach
  Baseten (a US provider). The privacy page and the processors list must say so before the deploy.
- **Modal** (if enabled later): GPU time is billed while a container is up; a container scaled to zero takes minutes to
  load a 70B model, so the first call after idle passes on to Baseten. For a demo day, deploy with
  `HABITA_FALLBACK_WARM=1` and redeploy without it afterwards. Llama weights need the Llama licence accepted on Hugging
  Face. For sensitive data, a model on Google Cloud in an EU region (the provider HABITA already uses) is the better
  candidate than Modal; to be studied after the hackathon.
