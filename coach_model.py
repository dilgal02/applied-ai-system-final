"""Local CPU backend for the future Strategy Coach.

Two commands:
    python coach_model.py download   # fetch the pinned model into models/
    python coach_model.py smoke      # short local generation check

The model (Qwen/Qwen3-0.6B) runs on the CPU with PyTorch and Transformers.
"download" is the only command that uses the network. "smoke" reads only
local files and never downloads anything. The game does not need this
module or its dependencies (see requirements-coach.txt).
"""
import argparse
import importlib.util
import json
import os
import platform
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

MODEL_ID = "Qwen/Qwen3-0.6B"
# Full commit hash on the Hugging Face Hub: everyone gets the same files.
MODEL_REVISION = "c1899de289a04d12100db370d81485cdf75e47ca"
MODEL_DIR = PROJECT_ROOT / "models" / "Qwen3-0.6B"
# Written into MODEL_DIR after a download, to check the local files later.
REVISION_FILE = "REVISION"
ALLOW_PATTERNS = [
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "LICENSE",
    "README.md",
]
REQUIRED_FILES = (
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
)
DEPENDENCIES = ("torch", "transformers", "huggingface_hub")

SYSTEM_PROMPT = "You are a helpful assistant. Answer in English."
DEFAULT_PROMPT = (
    "In one or two short sentences, explain what binary search is."
)
DEFAULT_MAX_NEW_TOKENS = 64
MAX_NEW_TOKENS_LIMIT = 256


def relative(path: Path) -> str:
    """A project-relative path for messages and reports."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def install_help(missing: list) -> str:
    return (
        f"Missing coach dependencies: {', '.join(missing)}.\n"
        "Install them into the project's virtual environment:\n"
        "    python -m pip install -r requirements-coach.txt"
    )


def download_help(problem: str) -> str:
    return (
        f"{problem}\n"
        f"Download the model once (about 1.5 GB) into "
        f"{relative(MODEL_DIR)}:\n"
        "    python coach_model.py download"
    )


def missing_dependencies() -> list:
    """Names of coach dependencies that are not installed."""
    return [name for name in DEPENDENCIES
            if importlib.util.find_spec(name) is None]


def model_problem() -> str | None:
    """Why the local model can't be used, or None if it is ready."""
    if not MODEL_DIR.is_dir():
        return f"The model folder {relative(MODEL_DIR)} does not exist."
    missing = [name for name in REQUIRED_FILES
               if not (MODEL_DIR / name).is_file()]
    if missing:
        return f"Model files are missing: {', '.join(missing)}."
    marker = MODEL_DIR / REVISION_FILE
    found = marker.read_text().strip() if marker.is_file() else None
    if found != MODEL_REVISION:
        return (
            f"The local model is not the pinned revision "
            f"(found {found}, expected {MODEL_REVISION})."
        )
    return None


def download() -> int:
    """Download the pinned model revision into MODEL_DIR."""
    missing = missing_dependencies()
    if missing:
        print(install_help(missing), file=sys.stderr)
        return 2
    from huggingface_hub import snapshot_download

    print(f"Downloading {MODEL_ID} at revision {MODEL_REVISION}")
    print(f"into {relative(MODEL_DIR)} ...")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_download(
            repo_id=MODEL_ID,
            revision=MODEL_REVISION,
            local_dir=MODEL_DIR,
            allow_patterns=ALLOW_PATTERNS,
        )
    except Exception as error:
        print(
            f"Download failed: {type(error).__name__}: {error}\n"
            "Check the internet connection, and that HF_HUB_OFFLINE is "
            "not set for this command.",
            file=sys.stderr,
        )
        return 1
    (MODEL_DIR / REVISION_FILE).write_text(MODEL_REVISION + "\n")
    problem = model_problem()
    if problem:
        print(f"Download incomplete: {problem}", file=sys.stderr)
        return 1
    print("Done. Run a local check with: python coach_model.py smoke")
    return 0


def looks_english(text: str) -> bool:
    """Simple check: almost all letters are basic Latin letters."""
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    latin = sum(char.isascii() for char in letters)
    return latin / len(letters) >= 0.95


def smoke(prompt: str, max_new_tokens: int, output: str | None) -> int:
    """Load the local model on the CPU and generate one short answer."""
    missing = missing_dependencies()
    if missing:
        print(install_help(missing), file=sys.stderr)
        return 2
    problem = model_problem()
    if problem:
        print(download_help(problem), file=sys.stderr)
        return 2

    try:
        import huggingface_hub
        import safetensors
        import tokenizers
        import torch
        import transformers
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as error:
        print(install_help([str(error)]), file=sys.stderr)
        return 2

    device = torch.device("cpu")
    torch.manual_seed(0)

    started = time.perf_counter()
    # local_files_only: never contact the Hub, even if files are missing.
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_DIR, local_files_only=True, dtype=torch.float32
    )
    model.to(device)
    model.eval()
    load_seconds = time.perf_counter() - started

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    # enable_thinking=False: Qwen3 answers directly, without a <think> part.
    chat_text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    thinking_off = chat_text.endswith("<think>\n\n</think>\n\n")
    inputs = tokenizer(chat_text, return_tensors="pt").to(device)

    # Greedy decoding with a hard length limit, so the check is repeatable.
    # The model's own config asks for sampling (temperature 0.6 and so on).
    # Neutral values on this loaded copy keep generate() from warning that
    # those sampling settings are ignored. Nothing is written to disk.
    model.generation_config.do_sample = False
    model.generation_config.temperature = 1.0
    model.generation_config.top_p = 1.0
    model.generation_config.top_k = 50

    started = time.perf_counter()
    with torch.inference_mode():
        output_ids = model.generate(
            **inputs, do_sample=False, max_new_tokens=max_new_tokens
        )
    generate_seconds = time.perf_counter() - started

    new_ids = output_ids[0][inputs["input_ids"].shape[1]:]
    answer = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
    raw_answer = tokenizer.decode(new_ids, skip_special_tokens=False)

    checks = [
        {"check": "answer is not empty", "passed": bool(answer)},
        {
            "check": "chat template turned thinking off",
            "passed": thinking_off,
        },
        {
            "check": "no thinking block in the answer",
            "passed": "<think>" not in raw_answer
            and "</think>" not in raw_answer,
        },
        {
            "check": f"at most {max_new_tokens} new tokens",
            "passed": len(new_ids) <= max_new_tokens,
        },
        {
            "check": "answer is in Latin letters (simple English check)",
            "passed": looks_english(answer),
        },
        {
            "check": "all model weights are on the CPU",
            "passed": all(p.device.type == "cpu" for p in model.parameters()),
        },
        {
            "check": "local files match the pinned revision",
            "passed": model_problem() is None,
        },
    ]
    passed = all(item["passed"] for item in checks)

    report = {
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "local_dir": relative(MODEL_DIR),
            "dtype": "float32",
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "huggingface_hub": huggingface_hub.__version__,
            "tokenizers": tokenizers.__version__,
            "safetensors": safetensors.__version__,
            "device": str(device),
            "torch_threads": torch.get_num_threads(),
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
        },
        "generation": {
            "local_files_only": True,
            "inference_mode": True,
            "enable_thinking": False,
            "do_sample": False,
            "max_new_tokens": max_new_tokens,
        },
        "prompt": {"system": SYSTEM_PROMPT, "user": prompt},
        "answer": answer,
        "generated_tokens": int(len(new_ids)),
        "seconds": {
            "load": round(load_seconds, 2),
            "generate": round(generate_seconds, 2),
        },
        "checks": checks,
        "result": "PASS" if passed else "FAIL",
    }

    print(f"model:    {MODEL_ID} @ {MODEL_REVISION}")
    print(f"device:   {device} (float32), torch {torch.__version__}, "
          f"transformers {transformers.__version__}")
    print(f"offline:  HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE')}")
    print(f"prompt:   {prompt}")
    print(f"answer:   {answer}")
    print(f"tokens:   {len(new_ids)} of max {max_new_tokens}")
    print(
        f"seconds:  load {load_seconds:.2f}, "
        f"generate {generate_seconds:.2f}"
    )
    for item in checks:
        mark = "ok" if item["passed"] else "FAIL"
        print(f"check:    [{mark}] {item['check']}")
    print(f"result:   {report['result']}")

    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"report saved: {output}")
    return 0 if passed else 1


def max_tokens(value: str) -> int:
    number = int(value)
    if not 1 <= number <= MAX_NEW_TOKENS_LIMIT:
        raise argparse.ArgumentTypeError(
            f"must be between 1 and {MAX_NEW_TOKENS_LIMIT}"
        )
    return number


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Local CPU backend for the Strategy Coach."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "download", help="download the pinned model into models/"
    )
    smoke_parser = commands.add_parser(
        "smoke", help="run a short local generation check (no downloads)"
    )
    smoke_parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    smoke_parser.add_argument(
        "--max-new-tokens", type=max_tokens, default=DEFAULT_MAX_NEW_TOKENS
    )
    smoke_parser.add_argument("--output", help="save a JSON report here")
    args = parser.parse_args(argv)

    if args.command == "download":
        return download()
    return smoke(args.prompt, args.max_new_tokens, args.output)


if __name__ == "__main__":
    sys.exit(main())
