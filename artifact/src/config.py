"""Shared configuration for the Attest pipeline (E03 Evidence-Bearing Explanations)."""
import os

SRC = os.path.dirname(os.path.abspath(__file__))
ART = os.path.dirname(SRC)
DATA = os.path.join(ART, "data")
REPOS = os.path.join(DATA, "repos")
RESULTS = os.path.join(ART, "results")
CACHE = os.path.join(RESULTS, "llm_cache")
GENERATED = os.path.join(os.path.dirname(ART), "manuscript", "generated")

SEED = 20261109          # sampling seed
LLM_SEED = 7             # decoding seed (temperature 0)

# Explainer conditions: name -> (backend, model id)
EXPLAINERS = {
    "coder14b": ("ollama", "qwen2.5-coder:14b"),
    "general14b": ("ollama", "qwen2.5:14b"),
}
FRONTIER = ("anthropic", "claude-haiku-5-5")   # optional capped condition (<=300 calls)
FRONTIER_CAP = 300
EXTRACTOR = ("ollama", "qwen2.5-coder:14b")
EXTRACTOR_SECOND = ("ollama", "qwen2.5:14b")
PROBER = ("ollama", "qwen2.5-coder:14b")
JUDGE = ("ollama", "gemma2:9b")        # round 2: different family from every explainer/extractor
JUDGE_V1 = ("ollama", "qwen2.5:14b")   # round 1 judge (same model as the general14b explainer)

# Corpus A (Python + Java repositories; never executed)
PY_REPOS = ["click", "requests", "tqdm", "more-itertools", "attrs", "boltons"]
JAVA_REPOS = ["gson", "commons-lang"]
PY_PER_REPO = 25
JAVA_PER_REPO = 20
MIN_LINES, MAX_LINES = 5, 45

# Corpus B (EvalPlus; canonical solutions executed in the sandbox only)
N_HUMANEVAL = 40
N_MBPP = 40

SECOND_EXTRACTOR_N = 100     # explanations re-extracted by the second model
JUDGE_N = 120                # explanations judged for the H2 proxy
PLANTED_PER_TYPE = 50        # template claims per type (half true / half perturbed)

CLAIM_TYPES = ["structural", "dataflow", "behavioural", "intent"]
OUTCOMES = ["true", "false", "undischargeable", "unverifiable"]

PROBE_TIMEOUT_S = 5

for _d in (DATA, REPOS, RESULTS, CACHE, GENERATED):
    os.makedirs(_d, exist_ok=True)
