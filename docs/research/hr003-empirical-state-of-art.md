# HR-003 — empirical state of the art: citation manifest (2026-11-01)

Source: owner's study `20261101-HR003-SOTA-EMPIRICO` (Drive). The references below are **as given by that study**;
the builder did not re-read the papers or re-check every DOI in this stage (status column). Numbers from papers are
not HABITA KPIs and do not transfer to Cascais/PT-PT without our own measurement.

| # | Reference | Empirical claim used | Hypothesis it supports here | Transfer limit | Status |
|---|---|---|---|---|---|
| E1 | Magesh et al. 2025, JELS, doi:10.1111/jels.12413 | legal RAG tools hallucinate 17–33 % | official source ≠ correct interpretation | US legal research | from study |
| E2 | Gao et al. 2023 ALCE, EMNLP, doi:10.18653/v1/2023.emnlp-main.398 | about half of answers lack full citation support | claim→passage support, not "document found" | ELI5, EN | from study |
| E3 | Min et al. 2023 FActScore, arXiv:2305.14251 | atomic-fact precision | claim-level atoms (MU-9 claims.py) | biographies | from study |
| E4 | Koreeda & Manning 2021 ContractNLI, doi:10.18653/v1/2021.findings-emnlp.164 | negation/exceptions hard for NLI | 3-way labels + spans | EN NDAs | from study |
| E5 | COLIEE 2025 overview | best statute entailment acc. 0.9041; multi-article retrieval weak | multi-passage rules | Japanese law | from study |
| E6 | Canaverde et al. 2026 LegalBench.PT, NLLP | PT-PT legal QA benchmark | PT-PT language baseline | exam questions, no PDM labels; licence to confirm | from study |
| E7 | Ru et al. 2024 RAGChecker, NeurIPS D&B | retrieval vs generation failure split | measure where the failure is | labels/retrieval dependent | from study |
| E8 | Niu et al. 2024 RAGTruth, doi:10.18653/v1/2024.acl-long.585 | small tuned detectors competitive | future detector on own cases | no PT, no permits | from study |
| E9 | Zha et al. 2023 AlignScore, ACL | factual alignment scorer | NLI SHADOW candidate (B5) | EN; old deps | from study |
| E10 | Ribeiro et al. 2020 CheckList, ACL | MFT/INV/DIR behavioural tests | metamorphic tests (`mr_of` in the dev set) | method only | from study |
| E11 | Pipitone & Houir Alami 2024 LegalBench-RAG, arXiv:2408.10343 | span-level retrieval ground truth | citation precision | EN contracts; retrieval only | from study |
| E12 | Chalkidis et al. 2022 LexGLUE | domain models help, varies by task | don't assume a general model reads PT law | EN | from study |
| E13 | Dal Pont et al. 2025, CLSR | obligation extraction ~93 % precision (5 experts) | explicit deontic operator/subject/exception | EU AI Act, small sample | from study |
| E14 | RoBERTaLexPT 2024, doi:10.21814/lm.16.2.457 | PT legal models beat larger general ones | future PT model | PT-BR | from study |
| E15 | de Martim 2025 SAT-Graph RAG, doi:10.3233/FAIA251598 | qualitative PoC | temporal norm graph (option C) | not quantitative | from study |

## Repositories (not cloned or installed in this stage)
| Repo | Licence (per study) | Use here | Decision |
|---|---|---|---|
| princeton-nlp/ALCE | MIT | method for citation precision/recall | method reused in our runner, no code imported |
| marcotcr/checklist | MIT | MFT/INV/DIR method | method reused (`mr_of` pairs), no code imported |
| yuh-zha/AlignScore | MIT (code); weights to check | NLI SHADOW (B5) | owner decision needed (download, isolated venv) |
| zeroentropy-ai/legalbenchrag | MIT code; datasets separate licences | retrieval spans | not used (EN contracts) |
| BeatrizCanaverde/LegalBench.PT | not confirmed | PT-PT baseline | not used until the licence is read |
| amazon-science/RAGChecker, ParticleMedia/RAGTruth, google-research/true, stanfordnlp/contract-nli, shmsw25/FActScore, hmartim/sat-graph-api, thiagordp/obligation_extraction_for_compliance, HazyResearch/legalbench | see study | design references | not used in this stage |

No dependency was added to the backend.
