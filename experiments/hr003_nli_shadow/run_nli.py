"""HR-003 NLI shadow experiment (NOT RUN: needs the owner's word to download the weights).

Isolated: its own venv (never the backend's), CPU only, pinned model revision. Reads the benchmark cases and the
fixture excerpts they cite, scores every (statement sentence, cited sentence) pair, keeps the best pair per
statement, and writes labels next to the gold. It never imports or changes MU-9's verdict path.

    python3 -m venv $SCRATCH/nli-venv && $SCRATCH/nli-venv/bin/pip install "torch==2.*" "transformers==4.*" sentencepiece
    $SCRATCH/nli-venv/bin/python run_nli.py cases.json excerpts.json > nli_results.json

``excerpts.json`` = {"E13": "...", ...}, exported once from ``run_benchmark.py``'s fixture records (no backend import
here, so the experiment can't touch the runtime).
"""
import json
import re
import sys

MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
REVISION = "b5113eb38a"  # pinned; checked 2026-11-02 (MIT)
LABELS = {"entailment": "SUPPORTED", "neutral": "INSUFFICIENT", "contradiction": "CONTRADICTED"}


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.;!?])\s+", text) if s.strip()]


def main(cases_path: str, excerpts_path: str) -> None:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer  # only inside the isolated venv
    import torch

    tok = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL, revision=REVISION).eval()
    id2label = {i: l.lower() for i, l in model.config.id2label.items()}
    cases = json.load(open(cases_path, encoding="utf-8"))["cases"]
    excerpts = json.load(open(excerpts_path, encoding="utf-8"))
    sets = json.load(open(excerpts_path.replace("excerpts", "sets"), encoding="utf-8"))
    out = []
    for case in cases:
        premises = [s for eid in sets.get(case["cites"], []) for s in sentences(excerpts.get(eid, ""))]
        best = {"label": "INSUFFICIENT", "score": 0.0, "premise": None}
        for premise in premises:
            enc = tok(premise, case["text"], return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                probs = torch.softmax(model(**enc).logits[0], dim=-1).tolist()
            for i, p in enumerate(probs):
                label = LABELS.get(id2label[i], "INSUFFICIENT")
                if label != "INSUFFICIENT" and p > best["score"]:
                    best = {"label": label, "score": round(p, 4), "premise": premise}
        out.append({"id": case["id"], "cat": case["cat"], "gold": case["gold"], **best})
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
