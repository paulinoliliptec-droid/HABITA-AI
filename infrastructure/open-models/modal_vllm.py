"""HABITA AI: open-weight fallback for the reasoning model, served by vLLM on Modal (afinamentos, NOT DEPLOYED).

It answers only when Muse Spark is unavailable (backend ``FallbackChatModel``); every answer still goes through the
deterministic MU-9 verifier. Nothing here runs until the owner deploys it with their own Modal account.

    modal secret create habita-hf HF_TOKEN=...            # a Hugging Face token that accepted the Llama licence
    modal secret create habita-fallback VLLM_API_KEY=...  # the key the backend sends (MODAL_MODEL_API_KEY)
    modal deploy infrastructure/open-models/modal_vllm.py

Backend settings afterwards: ``MODAL_MODEL_BASE_URL=<the printed URL>/v1``, ``MODAL_MODEL_API_KEY`` (Secret Manager)
and ``MODAL_MODEL_ID`` = ``MODEL`` below.

Costs: the GPU is billed while a container is up. By default it scales to zero: the first call after idle waits for a
cold start (minutes for this size), longer than the backend's fallback deadline (``FALLBACK_TIMEOUT_SECONDS``, 45 s), so that call
passes on to Baseten while Modal warms up. To have Modal answer at once (demo day), deploy with
``HABITA_FALLBACK_WARM=1`` (one container always up, billed all the time) and redeploy without it afterwards.
"""

import os
import subprocess

import modal

MODEL = os.environ.get("HABITA_FALLBACK_MODEL", "meta-llama/Llama-3.3-70B-Instruct")
GPU = os.environ.get("HABITA_FALLBACK_GPU", "H100:2")
WARM = int(os.environ.get("HABITA_FALLBACK_WARM", "0"))
VLLM = "0.11.0"
# vLLM's chat template for Llama 3.1+ JSON tool calls (its tool-calling docs pair it with ``llama3_json``).
TOOL_TEMPLATE = "/root/tool_chat_template_llama3.1_json.jinja"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("curl")
    .pip_install(f"vllm=={VLLM}", "huggingface_hub[hf_transfer]")
    .run_commands(f"curl -fsSL -o {TOOL_TEMPLATE} https://raw.githubusercontent.com/vllm-project/vllm/v{VLLM}/examples/"
                  "tool_chat_template_llama3.1_json.jinja")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)
weights = modal.Volume.from_name("habita-fallback-weights", create_if_missing=True)
app = modal.App("habita-fallback")


@app.function(
    image=image,
    gpu=GPU,
    secrets=[modal.Secret.from_name("habita-hf"), modal.Secret.from_name("habita-fallback")],
    volumes={"/root/.cache/huggingface": weights},
    min_containers=WARM,
    scaledown_window=15 * 60,
    timeout=60 * 60,
)
@modal.concurrent(max_inputs=16)
@modal.web_server(port=8000, startup_timeout=20 * 60)
def serve() -> None:
    tensor_parallel = GPU.split(":")[1] if ":" in GPU else "1"
    subprocess.Popen(
        [
            "vllm", "serve", MODEL,
            "--host", "0.0.0.0", "--port", "8000",
            "--served-model-name", MODEL,
            "--api-key", os.environ["VLLM_API_KEY"],
            "--tensor-parallel-size", tensor_parallel,
            # The workflow needs tool calls (investigation) and strict JSON schemas (checklist, draft, review).
            "--enable-auto-tool-choice", "--tool-call-parser", "llama3_json", "--chat-template", TOOL_TEMPLATE,
            "--max-model-len", "32768",
        ]
    )
