"""Local CPU backend for the future Strategy Coach.

Two commands:
    python coach_model.py download   # fetch the pinned model into models/
    python coach_model.py smoke      # short local generation check

The model (Qwen/Qwen3-0.6B) runs on the CPU with PyTorch and Transformers.
"download" is the only command that uses the network. "smoke" reads only
local files and never downloads anything. The game does not need this
module or its dependencies (see requirements-coach.txt).

LocalGenerator (through get_generator) is the reusable part: it loads the
model lazily, once, and generates an answer for chat messages. Importing
this module does not import torch or load any weights.
"""
import argparse
import importlib.util
import json
import os
import platform
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
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


class CoachSetupError(RuntimeError):
    """The coach cannot run: a dependency or the local model is missing.

    The message tells the user what to install or run.
    """


@dataclass(frozen=True)
class Generation:
    """The result of one local generation."""

    text: str  # the answer, special tokens removed
    raw_text: str  # the answer with special tokens, to look for <think>
    prompt_tokens: int
    generated_tokens: int
    max_new_tokens: int
    thinking_off: bool  # the chat template closed the thinking block
    load_seconds: float  # time to load the model in this call (0 if loaded)
    generate_seconds: float

    def settings(self) -> dict:
        """Model and generation settings, for reports."""
        return {
            "model": MODEL_ID,
            "revision": MODEL_REVISION,
            "device": "cpu",
            "dtype": "float32",
            "local_files_only": True,
            "inference_mode": True,
            "enable_thinking": False,
            "do_sample": False,
            "max_new_tokens": self.max_new_tokens,
        }


class LocalGenerator:
    """Runs the pinned local model on the CPU.

    The model is loaded lazily on the first generate() call and then kept.
    It only reads local files: nothing is downloaded and nothing is
    printed. Setup problems raise CoachSetupError.
    """

    def __init__(self):
        self._torch = None
        self._tokenizer = None
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> float:
        """Load the model once. Returns the seconds this call spent."""
        if self._model is not None:
            return 0.0
        missing = missing_dependencies()
        if missing:
            raise CoachSetupError(install_help(missing))
        problem = model_problem()
        if problem:
            raise CoachSetupError(download_help(problem))
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as error:
            raise CoachSetupError(install_help([str(error)])) from error

        started = time.perf_counter()
        # local_files_only: never contact the Hub, even if files are missing.
        tokenizer = AutoTokenizer.from_pretrained(
            MODEL_DIR, local_files_only=True
        )
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR, local_files_only=True, dtype=torch.float32
        )
        model.to(torch.device("cpu"))
        model.eval()
        # Greedy decoding. The model's own config asks for sampling
        # (temperature 0.6 and so on). Neutral values on this loaded copy
        # keep generate() from warning that they are ignored. Nothing is
        # written to disk.
        model.generation_config.do_sample = False
        model.generation_config.temperature = 1.0
        model.generation_config.top_p = 1.0
        model.generation_config.top_k = 50
        self._torch, self._tokenizer, self._model = torch, tokenizer, model
        return time.perf_counter() - started

    def generate(self, messages: list,
                 max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS) -> Generation:
        """Generate one answer for chat messages (system / user turns)."""
        if (isinstance(max_new_tokens, bool)
                or not isinstance(max_new_tokens, int)
                or not 1 <= max_new_tokens <= MAX_NEW_TOKENS_LIMIT):
            raise ValueError(
                f"max_new_tokens must be a whole number from 1 to "
                f"{MAX_NEW_TOKENS_LIMIT}, got {max_new_tokens!r}."
            )
        if not messages or not all(
            isinstance(message, dict)
            and isinstance(message.get("role"), str)
            and isinstance(message.get("content"), str)
            for message in messages
        ):
            raise ValueError(
                "messages must be a non-empty list of "
                "{'role': ..., 'content': ...} dictionaries."
            )

        load_seconds = self._load()
        torch, tokenizer, model = self._torch, self._tokenizer, self._model

        # enable_thinking=False: Qwen3 answers directly, without <think>.
        chat_text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        thinking_off = chat_text.endswith("<think>\n\n</think>\n\n")
        inputs = tokenizer(chat_text, return_tensors="pt").to("cpu")

        torch.manual_seed(0)
        started = time.perf_counter()
        with torch.inference_mode():
            output_ids = model.generate(
                **inputs, do_sample=False, max_new_tokens=max_new_tokens
            )
        generate_seconds = time.perf_counter() - started

        prompt_length = inputs["input_ids"].shape[1]
        new_ids = output_ids[0][prompt_length:]
        return Generation(
            text=tokenizer.decode(new_ids, skip_special_tokens=True).strip(),
            raw_text=tokenizer.decode(new_ids, skip_special_tokens=False),
            prompt_tokens=int(prompt_length),
            generated_tokens=int(len(new_ids)),
            max_new_tokens=max_new_tokens,
            thinking_off=thinking_off,
            load_seconds=round(load_seconds, 2),
            generate_seconds=round(generate_seconds, 2),
        )

    def weights_on_cpu(self) -> bool:
        return self.loaded and all(
            parameter.device.type == "cpu"
            for parameter in self._model.parameters()
        )

    def environment(self) -> dict:
        """Library versions and device, for reports. Needs a loaded model."""
        import huggingface_hub
        import safetensors
        import tokenizers
        import transformers

        torch = self._torch
        return {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "huggingface_hub": huggingface_hub.__version__,
            "tokenizers": tokenizers.__version__,
            "safetensors": safetensors.__version__,
            "device": "cpu",
            "torch_threads": torch.get_num_threads(),
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
        }


@lru_cache(maxsize=1)
def get_generator() -> LocalGenerator:
    """The shared generator: the model is loaded at most once per process."""
    return LocalGenerator()


def smoke(prompt: str, max_new_tokens: int, output: str | None) -> int:
    """Generate one short answer with the local model and check it."""
    missing = missing_dependencies()
    if missing:
        print(install_help(missing), file=sys.stderr)
        return 2
    problem = model_problem()
    if problem:
        print(download_help(problem), file=sys.stderr)
        return 2

    generator = get_generator()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    try:
        result = generator.generate(messages, max_new_tokens)
    except CoachSetupError as error:
        print(error, file=sys.stderr)
        return 2
    environment = generator.environment()
    answer = result.text

    checks = [
        {"check": "answer is not empty", "passed": bool(answer)},
        {
            "check": "chat template turned thinking off",
            "passed": result.thinking_off,
        },
        {
            "check": "no thinking block in the answer",
            "passed": "<think>" not in result.raw_text
            and "</think>" not in result.raw_text,
        },
        {
            "check": f"at most {max_new_tokens} new tokens",
            "passed": result.generated_tokens <= max_new_tokens,
        },
        {
            "check": "answer is in Latin letters (simple English check)",
            "passed": looks_english(answer),
        },
        {
            "check": "all model weights are on the CPU",
            "passed": generator.weights_on_cpu(),
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
        "environment": environment,
        "generation": {
            "local_files_only": True,
            "inference_mode": True,
            "enable_thinking": False,
            "do_sample": False,
            "max_new_tokens": max_new_tokens,
        },
        "prompt": {"system": SYSTEM_PROMPT, "user": prompt},
        "answer": answer,
        "generated_tokens": result.generated_tokens,
        "seconds": {
            "load": result.load_seconds,
            "generate": result.generate_seconds,
        },
        "checks": checks,
        "result": "PASS" if passed else "FAIL",
    }

    print(f"model:    {MODEL_ID} @ {MODEL_REVISION}")
    print(f"device:   cpu (float32), torch {environment['torch']}, "
          f"transformers {environment['transformers']}")
    print(f"offline:  HF_HUB_OFFLINE={environment['HF_HUB_OFFLINE']}")
    print(f"prompt:   {prompt}")
    print(f"answer:   {answer}")
    print(f"tokens:   {result.generated_tokens} of max {max_new_tokens}")
    print(
        f"seconds:  load {result.load_seconds:.2f}, "
        f"generate {result.generate_seconds:.2f}"
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
