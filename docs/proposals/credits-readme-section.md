# Proposal — README credits section (NOT applied; needs the owner's approval)

Audit (read-only, 2026-11-01/02) and the reasoning are in the HR-003 stage report. The section below would go near the
end of `README.md`. Text only: no logos or brand badges (trademark use not checked), no fake accounts, no new
Co-authored-by trailers, no history rewrite.

---

## Built by

**Garcia Monteiro Paulino** — founder, product owner and lead engineer. Every decision, approval, merge and deploy
in this repository is his, and he is responsible for the code.

### AI-assisted engineering & review

HABITA was built with AI engineering tools under human direction. They are tools, not authors: the commits are
authored by the human owner.

| Tool | Role in this project | Where its work is recorded |
|---|---|---|
| **Claude Code** (Anthropic) | implementation: backend, frontend, tests, deploy scripts, documentation | commit history; stage reports in Drive `01-CLAUDE-RELATORIOS` |
| **OpenAI Codex** | independent code review, adversarial reproduction of defects (read-only) | review records kept with the project (local `.ai-review/`); findings cited in commits and `docs/research/` |
| **Muse Code** (Meta) | research and audit of the system and its tests | audit reports (Drive) · `docs/research/` |
| **Meta Muse models** | the product's own AI: Muse Spark (reasoning, reading files), Muse Image, Muse Voice Transcribe, SAM 3.1 | `docs/architecture.md` |

Every legal answer is still checked by HABITA's deterministic verifier (MU-9); no AI tool or model can mark an answer
VERIFIED on its own.

---
